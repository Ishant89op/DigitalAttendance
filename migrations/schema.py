"""
Schema migration — idempotent DDL plus one-time security upgrades.

Run via:  python main.py db
Or automatically called at API startup.

v3 (security hardening):
  - auth_sessions: server-side sessions (only token digests are stored)
  - login_credentials: lockout counters, forced password change, temp-password expiry
  - classrooms: PINs stored as scrypt hashes; plaintext access_pin column removed
  - evidence_files: ownership record for every uploaded dispute PDF
  - Legacy defaults (password = own ID, admin/admin123, PIN 1234) are disabled;
    an admin issues one-time passwords instead.
  - No credentials are seeded by SQL any more. The first admin account is
    bootstrapped from ADMIN_LOGIN_PASSWORD or a generated one-time password.
"""

import asyncio
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

SCHEMA_SQL = """

-- ─────────────────────────────────────────────
-- EXTENSIONS
-- ─────────────────────────────────────────────
CREATE EXTENSION IF NOT EXISTS "pgcrypto";


-- ─────────────────────────────────────────────
-- USERS (reserved for SSO integration)
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
-- password_hash NULL = account exists but has no usable password yet
-- (admin must issue a one-time password).
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS login_credentials (
    role          TEXT NOT NULL CHECK (role IN ('admin', 'teacher', 'student')),
    principal_id  TEXT NOT NULL,
    password_hash TEXT,
    created_at    TIMESTAMPTZ DEFAULT NOW(),
    updated_at    TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (role, principal_id)
);

ALTER TABLE login_credentials ALTER COLUMN password_hash DROP NOT NULL;
ALTER TABLE login_credentials ADD COLUMN IF NOT EXISTS failed_attempts      INTEGER NOT NULL DEFAULT 0;
ALTER TABLE login_credentials ADD COLUMN IF NOT EXISTS locked_until         TIMESTAMPTZ;
ALTER TABLE login_credentials ADD COLUMN IF NOT EXISTS must_change_password BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE login_credentials ADD COLUMN IF NOT EXISTS temp_expires_at      TIMESTAMPTZ;
ALTER TABLE login_credentials ADD COLUMN IF NOT EXISTS last_login_at        TIMESTAMPTZ;


-- ─────────────────────────────────────────────
-- AUTH SESSIONS
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS auth_sessions (
    token_hash           TEXT PRIMARY KEY,
    role                 TEXT NOT NULL CHECK (role IN ('admin', 'teacher', 'student', 'classroom')),
    principal_id         TEXT NOT NULL,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at           TIMESTAMPTZ NOT NULL,
    revoked_at           TIMESTAMPTZ,
    ip                   TEXT,
    user_agent           TEXT,
    must_change_password BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS idx_auth_sessions_principal
    ON auth_sessions (role, principal_id) WHERE revoked_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_auth_sessions_expiry
    ON auth_sessions (expires_at);


-- ─────────────────────────────────────────────
-- DEPARTMENTS
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS departments (
    dept_id   TEXT PRIMARY KEY,
    dept_name TEXT NOT NULL
);


-- ─────────────────────────────────────────────
-- STUDENTS
-- face_encoding holds an AES-256-GCM encrypted template (see core/security.py).
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
    capacity     INTEGER
);

ALTER TABLE classrooms ADD COLUMN IF NOT EXISTS access_pin_hash  TEXT;
ALTER TABLE classrooms ADD COLUMN IF NOT EXISTS pin_failed_attempts INTEGER NOT NULL DEFAULT 0;
ALTER TABLE classrooms ADD COLUMN IF NOT EXISTS pin_locked_until TIMESTAMPTZ;


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

CREATE INDEX IF NOT EXISTS idx_course_teachers_teacher
    ON course_teachers (teacher_id, course_id);


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

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'one_active_per_room') THEN
        ALTER TABLE lecture_sessions DROP CONSTRAINT one_active_per_room;
    END IF;
END$$;

CREATE INDEX IF NOT EXISTS idx_lecture_classroom_status
    ON lecture_sessions (classroom_id, status);
CREATE INDEX IF NOT EXISTS idx_lecture_course_status
    ON lecture_sessions (course_id, status);
CREATE INDEX IF NOT EXISTS idx_lecture_start_time
    ON lecture_sessions (start_time DESC);


-- ─────────────────────────────────────────────
-- RECOGNITION SESSIONS
-- ─────────────────────────────────────────────
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
    student_id TEXT NOT NULL REFERENCES students(student_id) ON DELETE CASCADE,
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
-- AUDIT LOG (append-only by convention; no API deletes it)
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

ALTER TABLE attendance_disputes ADD COLUMN IF NOT EXISTS evidence_file TEXT;

CREATE INDEX IF NOT EXISTS idx_disputes_student
    ON attendance_disputes (student_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_disputes_status
    ON attendance_disputes (status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_disputes_course
    ON attendance_disputes (course_id);


-- ─────────────────────────────────────────────
-- EVIDENCE FILES (who uploaded what — gates every download)
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS evidence_files (
    file_name   TEXT PRIMARY KEY,
    student_id  TEXT NOT NULL REFERENCES students(student_id) ON DELETE CASCADE,
    sha256      TEXT NOT NULL,
    size_bytes  INTEGER NOT NULL,
    original_name TEXT,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);


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


-- ─────────────────────────────────────────────
-- LEGACY CREDENTIAL CLEAN-UP
-- Old builds seeded every account with password = its own ID (unsalted
-- SHA-256) and admin/admin123. Those are publicly guessable, so they are
-- disabled here; an admin issues one-time passwords instead.
-- ─────────────────────────────────────────────
UPDATE login_credentials
SET password_hash = NULL, must_change_password = TRUE, updated_at = NOW()
WHERE password_hash IS NOT NULL
  AND password_hash !~ '^scrypt\\$'
  AND (
        password_hash = encode(digest(principal_id, 'sha256'), 'hex')
     OR (role = 'admin' AND password_hash = encode(digest('admin123', 'sha256'), 'hex'))
  );

-- Every student/teacher gets a credential row (disabled until a password is issued).
INSERT INTO login_credentials (role, principal_id, password_hash, must_change_password)
SELECT 'student', s.student_id, NULL, TRUE FROM students s
ON CONFLICT (role, principal_id) DO NOTHING;

INSERT INTO login_credentials (role, principal_id, password_hash, must_change_password)
SELECT 'teacher', t.teacher_id, NULL, TRUE FROM teachers t
ON CONFLICT (role, principal_id) DO NOTHING;
"""


async def _migrate_classroom_pins(conn) -> None:
    """Hash legacy plaintext PINs (strong ones) and drop the plaintext column."""
    has_plain = await conn.fetchval(
        """
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'classrooms' AND column_name = 'access_pin'
        """
    )
    if not has_plain:
        return

    from core.security import hash_secret, pin_problems

    rows = await conn.fetch("SELECT classroom_id, access_pin FROM classrooms WHERE access_pin IS NOT NULL")
    for row in rows:
        pin = (row["access_pin"] or "").strip()
        if pin and not pin_problems(pin):
            pin_hash = await asyncio.to_thread(hash_secret, pin)
            await conn.execute(
                "UPDATE classrooms SET access_pin_hash = $1 WHERE classroom_id = $2 AND access_pin_hash IS NULL",
                pin_hash, row["classroom_id"],
            )
        else:
            logger.warning(
                "Classroom %s had a weak legacy PIN; device login is disabled until an admin sets a new PIN.",
                row["classroom_id"],
            )
    await conn.execute("ALTER TABLE classrooms DROP COLUMN access_pin")
    logger.info("Classroom PINs migrated to scrypt hashes; plaintext column removed.")


async def _bootstrap_admin(conn) -> None:
    """
    Guarantee there is a usable admin account without shipping a default
    password. Uses ADMIN_LOGIN_ID / ADMIN_LOGIN_PASSWORD when provided,
    otherwise writes a one-time password to instance/initial_admin_password.txt.
    """
    from config.settings import security as sec_cfg
    from core.security import generate_temporary_password, hash_secret, password_problems

    usable = await conn.fetchval(
        "SELECT 1 FROM login_credentials WHERE role = 'admin' AND password_hash IS NOT NULL LIMIT 1"
    )
    if usable:
        return

    admin_id = os.getenv("ADMIN_LOGIN_ID", "admin").strip() or "admin"
    env_password = os.getenv("ADMIN_LOGIN_PASSWORD", "")
    if env_password and not password_problems(env_password, admin_id):
        password, must_change, source = env_password, False, "ADMIN_LOGIN_PASSWORD"
    else:
        if env_password:
            logger.warning("ADMIN_LOGIN_PASSWORD does not meet the password policy; ignoring it.")
        password, must_change, source = generate_temporary_password(), True, "generated"

    pw_hash = await asyncio.to_thread(hash_secret, password)
    await conn.execute(
        """
        INSERT INTO login_credentials (role, principal_id, password_hash, must_change_password, updated_at)
        VALUES ('admin', $1, $2, $3, NOW())
        ON CONFLICT (role, principal_id) DO UPDATE
        SET password_hash = EXCLUDED.password_hash,
            must_change_password = EXCLUDED.must_change_password,
            failed_attempts = 0, locked_until = NULL, updated_at = NOW()
        """,
        admin_id, pw_hash, must_change,
    )

    if source == "generated":
        path = Path(sec_cfg.instance_dir)
        path.mkdir(parents=True, exist_ok=True)
        secret_file = path / "initial_admin_password.txt"
        secret_file.write_text(
            f"AttendX initial admin login\nID: {admin_id}\nOne-time password: {password}\n"
            "You will be asked to set a new password on first sign-in. Delete this file afterwards.\n",
            encoding="utf-8",
        )
        try:
            os.chmod(secret_file, 0o600)
        except OSError:
            pass
        logger.warning("Admin account '%s' bootstrapped. One-time password written to %s", admin_id, secret_file)
    else:
        logger.info("Admin account '%s' bootstrapped from ADMIN_LOGIN_PASSWORD.", admin_id)


async def _encrypt_legacy_faces(conn) -> None:
    """Older builds stored raw float32 embeddings; encrypt them in place."""
    from core.security import encrypt_face_template, is_encrypted_template

    rows = await conn.fetch("SELECT student_id, face_encoding FROM students WHERE face_encoding IS NOT NULL")
    migrated = 0
    for row in rows:
        blob = bytes(row["face_encoding"])
        if not is_encrypted_template(blob):
            await conn.execute(
                "UPDATE students SET face_encoding = $1 WHERE student_id = $2",
                encrypt_face_template(row["student_id"], blob), row["student_id"],
            )
            migrated += 1
    if migrated:
        logger.info("Encrypted %d legacy face template(s) at rest.", migrated)


async def run_migrations() -> None:
    """Execute schema SQL and one-time security upgrades against the pool."""
    from core.database import get_conn

    async with get_conn() as conn:
        # Serialise concurrent migrators (API + recognizer starting together).
        async with conn.transaction():
            await conn.execute("SELECT pg_advisory_xact_lock(727274)")
            await conn.execute(SCHEMA_SQL)
            await _migrate_classroom_pins(conn)
            await _encrypt_legacy_faces(conn)
            await _bootstrap_admin(conn)
    logger.info("Schema migration complete.")


if __name__ == "__main__":
    from core.database import init_pool, close_pool

    async def main():
        await init_pool()
        await run_migrations()
        await close_pool()

    asyncio.run(main())
