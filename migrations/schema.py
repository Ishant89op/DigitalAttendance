"""
Schema migration — idempotent DDL.

Run via:  python -m migrations.schema
Or automatically called at API startup.

Changes from v2:
  - FIXED: Removed UNIQUE(classroom_id, status) constraint which broke lecture_sessions
    after the first closed lecture per classroom.
  - ADDED: access_pin column to classrooms for classroom-device login.
  - ADDED: upcoming lectures view helper index.
  - ADDED: recognition_sessions table for persistent camera process tracking.
    - ADDED: attendance_disputes workflow table.
    - ADDED: defaulter_reminders table for weekly reminder tracking.
"""

SCHEMA_SQL = """

-- ─────────────────────────────────────────────
-- EXTENSIONS
-- ─────────────────────────────────────────────
CREATE EXTENSION IF NOT EXISTS "pgcrypto";


-- ─────────────────────────────────────────────
-- USERS
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS users (
    id           TEXT PRIMARY KEY DEFAULT gen_random_uuid()::TEXT,
    name         TEXT NOT NULL,
    email        TEXT UNIQUE NOT NULL,
    role         TEXT NOT NULL CHECK (role IN ('admin', 'teacher', 'student')),
    password_hash TEXT NOT NULL,
    created_at   TIMESTAMPTZ DEFAULT NOW()
);


-- ─────────────────────────────────────────────
-- LOGIN CREDENTIALS
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS login_credentials (
    role          TEXT NOT NULL CHECK (role IN ('admin', 'teacher', 'student')),
    principal_id  TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    created_at    TIMESTAMPTZ DEFAULT NOW(),
    updated_at    TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (role, principal_id)
);


-- ─────────────────────────────────────────────
-- DEPARTMENTS
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS departments (
    dept_id   TEXT PRIMARY KEY,
    dept_name TEXT NOT NULL
);


-- ─────────────────────────────────────────────
-- STUDENTS
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS students (
    student_id    TEXT PRIMARY KEY,
    user_id       TEXT REFERENCES users(id) ON DELETE SET NULL,
    name          TEXT NOT NULL,
    email         TEXT,
    department    TEXT NOT NULL,
    semester      INTEGER NOT NULL CHECK (semester BETWEEN 1 AND 12),
    face_encoding BYTEA,
    registered_at TIMESTAMPTZ,
    created_at    TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_students_semester_dept
    ON students (semester, department);


-- ─────────────────────────────────────────────
-- TEACHERS
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS teachers (
    teacher_id  TEXT PRIMARY KEY,
    user_id     TEXT REFERENCES users(id) ON DELETE SET NULL,
    name        TEXT NOT NULL,
    email       TEXT,
    department  TEXT NOT NULL,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);


-- ─────────────────────────────────────────────
-- CLASSROOMS
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS classrooms (
    classroom_id TEXT PRIMARY KEY,
    room_number  TEXT NOT NULL,
    building     TEXT,
    capacity     INTEGER,
    access_pin   TEXT DEFAULT '1234'
);

-- Add access_pin column if it doesn't exist (for existing deployments)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'classrooms' AND column_name = 'access_pin'
    ) THEN
        ALTER TABLE classrooms ADD COLUMN access_pin TEXT DEFAULT '1234';
    END IF;
END$$;


-- ─────────────────────────────────────────────
-- DEFAULT LOGIN CREDENTIAL SEEDING
-- ─────────────────────────────────────────────
INSERT INTO login_credentials (role, principal_id, password_hash)
VALUES (
    'admin',
    'admin',
    encode(digest('admin123', 'sha256'), 'hex')
)
ON CONFLICT (role, principal_id) DO NOTHING;

INSERT INTO login_credentials (role, principal_id, password_hash)
SELECT
    'student',
    s.student_id,
    encode(digest(s.student_id, 'sha256'), 'hex')
FROM students s
WHERE NOT EXISTS (
    SELECT 1
    FROM login_credentials lc
    WHERE lc.role = 'student'
      AND lc.principal_id = s.student_id
);

INSERT INTO login_credentials (role, principal_id, password_hash)
SELECT
    'teacher',
    t.teacher_id,
    encode(digest(t.teacher_id, 'sha256'), 'hex')
FROM teachers t
WHERE NOT EXISTS (
    SELECT 1
    FROM login_credentials lc
    WHERE lc.role = 'teacher'
      AND lc.principal_id = t.teacher_id
);


-- ─────────────────────────────────────────────
-- COURSES
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS courses (
    course_id   TEXT PRIMARY KEY,
    course_name TEXT NOT NULL,
    department  TEXT NOT NULL,
    semester    INTEGER NOT NULL,
    credits     INTEGER DEFAULT 3
);

CREATE INDEX IF NOT EXISTS idx_courses_semester_dept
    ON courses (semester, department);


-- ─────────────────────────────────────────────
-- COURSE-TEACHER ASSIGNMENTS
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS course_teachers (
    id         SERIAL PRIMARY KEY,
    course_id  TEXT NOT NULL REFERENCES courses(course_id) ON DELETE CASCADE,
    teacher_id TEXT NOT NULL REFERENCES teachers(teacher_id) ON DELETE CASCADE,
    UNIQUE (course_id, teacher_id)
);


-- ─────────────────────────────────────────────
-- WEEKLY SCHEDULE
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS weekly_schedule (
    schedule_id  SERIAL PRIMARY KEY,
    course_id    TEXT NOT NULL REFERENCES courses(course_id) ON DELETE CASCADE,
    classroom_id TEXT NOT NULL REFERENCES classrooms(classroom_id) ON DELETE CASCADE,
    day_of_week  TEXT NOT NULL CHECK (
        day_of_week IN ('Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday')
    ),
    start_time   TIME NOT NULL,
    end_time     TIME NOT NULL,
    CONSTRAINT valid_time_range CHECK (end_time > start_time)
);

CREATE INDEX IF NOT EXISTS idx_schedule_classroom_day
    ON weekly_schedule (classroom_id, day_of_week);


-- ─────────────────────────────────────────────
-- LECTURE SESSIONS
-- NOTE: The old UNIQUE(classroom_id, status) constraint has been removed.
-- It incorrectly limited each classroom to one closed lecture forever.
-- Active-lecture uniqueness is enforced in application logic (lecture_service.py).
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS lecture_sessions (
    lecture_id   SERIAL PRIMARY KEY,
    course_id    TEXT NOT NULL REFERENCES courses(course_id),
    classroom_id TEXT NOT NULL REFERENCES classrooms(classroom_id),
    teacher_id   TEXT REFERENCES teachers(teacher_id),
    status       TEXT NOT NULL DEFAULT 'active'
                     CHECK (status IN ('active', 'closed')),
    start_time   TIMESTAMPTZ DEFAULT NOW(),
    end_time     TIMESTAMPTZ
);

-- Drop the broken constraint if it exists from a previous deployment
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'one_active_per_room'
    ) THEN
        ALTER TABLE lecture_sessions DROP CONSTRAINT one_active_per_room;
    END IF;
END$$;

CREATE INDEX IF NOT EXISTS idx_lecture_classroom_status
    ON lecture_sessions (classroom_id, status);

CREATE INDEX IF NOT EXISTS idx_lecture_start_time
    ON lecture_sessions (start_time DESC);


-- -------------------------------------------------------------
-- RECOGNITION SESSIONS
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS recognition_sessions (
    classroom_id TEXT PRIMARY KEY REFERENCES classrooms(classroom_id) ON DELETE CASCADE,
    pid          INTEGER NOT NULL,
    started_at   TIMESTAMPTZ DEFAULT NOW(),
    updated_at   TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_recognition_sessions_pid
    ON recognition_sessions (pid);


-- ─────────────────────────────────────────────
-- ATTENDANCE
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS attendance (
    id         BIGSERIAL PRIMARY KEY,
    lecture_id INTEGER NOT NULL REFERENCES lecture_sessions(lecture_id),
    student_id TEXT NOT NULL REFERENCES students(student_id),
    timestamp  TIMESTAMPTZ DEFAULT NOW(),
    source     TEXT DEFAULT 'face_recognition'
                   CHECK (source IN ('face_recognition', 'manual_override')),
    marked_by  TEXT,
    UNIQUE (student_id, lecture_id)
);

CREATE INDEX IF NOT EXISTS idx_attendance_lecture
    ON attendance (lecture_id);
CREATE INDEX IF NOT EXISTS idx_attendance_student
    ON attendance (student_id);
CREATE INDEX IF NOT EXISTS idx_attendance_timestamp
    ON attendance (timestamp);


-- ─────────────────────────────────────────────
-- AUDIT LOG
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS audit_log (
    log_id     BIGSERIAL PRIMARY KEY,
    event_type TEXT NOT NULL,
    actor_id   TEXT,
    target_id  TEXT,
    detail     JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_audit_event_type ON audit_log (event_type);
CREATE INDEX IF NOT EXISTS idx_audit_created_at ON audit_log (created_at DESC);


-- ─────────────────────────────────────────────
-- ATTENDANCE DISPUTES
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS attendance_disputes (
    dispute_id       BIGSERIAL PRIMARY KEY,
    student_id       TEXT NOT NULL REFERENCES students(student_id) ON DELETE CASCADE,
    course_id        TEXT REFERENCES courses(course_id) ON DELETE SET NULL,
    lecture_id       INTEGER REFERENCES lecture_sessions(lecture_id) ON DELETE SET NULL,
    reason           TEXT NOT NULL,
    evidence         TEXT,
    status           TEXT NOT NULL DEFAULT 'open'
                        CHECK (status IN ('open', 'approved', 'rejected')),
    reviewer_id      TEXT,
    reviewer_role    TEXT CHECK (reviewer_role IN ('teacher', 'admin')),
    resolution_note  TEXT,
    created_at       TIMESTAMPTZ DEFAULT NOW(),
    reviewed_at      TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_disputes_student
    ON attendance_disputes (student_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_disputes_status
    ON attendance_disputes (status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_disputes_course
    ON attendance_disputes (course_id);


-- ─────────────────────────────────────────────
-- DEFAULTER REMINDERS
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS defaulter_reminders (
    reminder_id       BIGSERIAL PRIMARY KEY,
    student_id        TEXT NOT NULL REFERENCES students(student_id) ON DELETE CASCADE,
    course_id         TEXT NOT NULL REFERENCES courses(course_id) ON DELETE CASCADE,
    percentage        NUMERIC(5,2) NOT NULL,
    week_start        DATE NOT NULL,
    status            TEXT NOT NULL DEFAULT 'pending'
                         CHECK (status IN ('pending', 'sent')),
    delivery_channel  TEXT NOT NULL DEFAULT 'in_app',
    message           TEXT,
    created_at        TIMESTAMPTZ DEFAULT NOW(),
    sent_at           TIMESTAMPTZ,
    UNIQUE (student_id, course_id, week_start)
);

CREATE INDEX IF NOT EXISTS idx_reminders_status
    ON defaulter_reminders (status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_reminders_week
    ON defaulter_reminders (week_start DESC);

"""


async def run_migrations() -> None:
    """Execute schema SQL against the connected pool."""
    from core.database import get_conn
    import logging
    logger = logging.getLogger(__name__)

    async with get_conn() as conn:
        await conn.execute(SCHEMA_SQL)
    logger.info("Schema migration complete.")


if __name__ == "__main__":
    import asyncio
    from core.database import init_pool, close_pool

    async def main():
        await init_pool()
        await run_migrations()
        await close_pool()

    asyncio.run(main())
