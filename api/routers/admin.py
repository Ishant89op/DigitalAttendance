"""Admin management endpoints (admin role only)."""

from __future__ import annotations

from typing import Literal

import asyncpg
from fastapi import APIRouter, Depends, File, HTTPException, Path, Request, UploadFile
from pydantic import BaseModel, Field

from config.settings import uploads as upload_cfg
from core.auth import Principal, audit, require, revoke_all_sessions, to_thread
from core.database import get_conn, transaction
from core.security import ID_PATTERN, hash_secret, pin_problems
from services.csv_service import (
    CsvImportError,
    import_course_teachers,
    import_courses,
    import_schedule,
    import_students,
    import_teachers,
)

router = APIRouter(prefix="/admin", tags=["Admin"], dependencies=[Depends(require("admin"))])

AdminOnly = Depends(require("admin"))
def Name(): return Field(min_length=1, max_length=120)
def Dept(): return Field(min_length=1, max_length=32, pattern=r"^[A-Za-z0-9 &._\-]+$")
def Email(): return Field(default=None, max_length=254, pattern=r"^[^@\s<>\"']+@[^@\s<>\"']+\.[A-Za-z]{2,}$")


def _clean(value: str) -> str:
    return " ".join(value.split())


# ─────────────────────────────────────────────
# STUDENTS
# ─────────────────────────────────────────────

class StudentCreate(BaseModel):
    student_id: str = Field(pattern=ID_PATTERN)
    name:       str = Name()
    email:      str | None = Email()
    department: str = Dept()
    semester:   int = Field(ge=1, le=12)



class StudentUpdate(BaseModel):
    name:       str = Name()
    email:      str | None = Email()
    department: str = Dept()
    semester:   int = Field(ge=1, le=12)



@router.post("/students", summary="Add a single student")
async def add_student(data: StudentCreate, request: Request, admin: Principal = AdminOnly):
    try:
        async with transaction() as conn:
            await conn.execute(
                """
                INSERT INTO students (student_id, name, email, department, semester)
                VALUES ($1, $2, $3, $4, $5)
                """,
                data.student_id, _clean(data.name), data.email, data.department, data.semester,
            )
            await conn.execute(
                """
                INSERT INTO login_credentials (role, principal_id, password_hash, must_change_password)
                VALUES ('student', $1, NULL, TRUE)
                ON CONFLICT (role, principal_id) DO NOTHING
                """,
                data.student_id,
            )
            await audit("student_created", admin.user_id, data.student_id, {}, request, conn=conn)
    except asyncpg.UniqueViolationError:
        raise HTTPException(status_code=409, detail="A student with this ID already exists.")
    return {"message": "Student created. Issue a one-time password so they can sign in.",
            "student_id": data.student_id}


@router.get("/students", summary="List students")
async def list_students(department: str | None = None, semester: int | None = None):
    async with get_conn() as conn:
        rows = await conn.fetch(
            """
            SELECT s.student_id, s.name, s.email, s.department, s.semester,
                   (s.face_encoding IS NOT NULL) AS face_registered,
                   s.registered_at,
                   (lc.password_hash IS NOT NULL) AS has_password,
                   lc.last_login_at
            FROM   students s
            LEFT   JOIN login_credentials lc ON lc.role = 'student' AND lc.principal_id = s.student_id
            WHERE  ($1::TEXT IS NULL OR s.department = $1)
              AND  ($2::INT  IS NULL OR s.semester   = $2)
            ORDER  BY s.name
            """,
            department, semester,
        )
    return [dict(r) for r in rows]


@router.put("/students/{student_id}", summary="Update a student")
async def update_student(data: StudentUpdate, request: Request, student_id: str = Path(pattern=ID_PATTERN),
                         admin: Principal = AdminOnly):
    async with transaction() as conn:
        result = await conn.execute(
            "UPDATE students SET name=$1, email=$2, department=$3, semester=$4 WHERE student_id=$5",
            _clean(data.name), data.email, data.department, data.semester, student_id,
        )
        if result == "UPDATE 0":
            raise HTTPException(status_code=404, detail="Student not found.")
        await audit("student_updated", admin.user_id, student_id, {}, request, conn=conn)
    return {"message": "Updated", "student_id": student_id}


@router.delete("/students/{student_id}", summary="Delete a student")
async def delete_student(request: Request, student_id: str = Path(pattern=ID_PATTERN), admin: Principal = AdminOnly):
    try:
        async with transaction() as conn:
            await revoke_all_sessions("student", student_id, conn=conn)
            await conn.execute(
                "DELETE FROM login_credentials WHERE role='student' AND principal_id=$1", student_id,
            )
            await conn.execute("DELETE FROM attendance WHERE student_id=$1", student_id)
            result = await conn.execute("DELETE FROM students WHERE student_id=$1", student_id)
            if result == "DELETE 0":
                raise HTTPException(status_code=404, detail="Student not found.")
            await audit("student_deleted", admin.user_id, student_id, {}, request, conn=conn)
    except asyncpg.ForeignKeyViolationError:
        raise HTTPException(status_code=409, detail="Student still has linked records.")
    return {"message": "Deleted", "student_id": student_id}


@router.delete("/students/{student_id}/face", summary="Erase a student's face template")
async def erase_face(request: Request, student_id: str = Path(pattern=ID_PATTERN), admin: Principal = AdminOnly):
    async with transaction() as conn:
        result = await conn.execute(
            "UPDATE students SET face_encoding = NULL, registered_at = NULL WHERE student_id = $1",
            student_id,
        )
        if result == "UPDATE 0":
            raise HTTPException(status_code=404, detail="Student not found.")
        await audit("face_erased", admin.user_id, student_id, {}, request, conn=conn)
    return {"message": "Face template erased.", "student_id": student_id}


# ─────────────────────────────────────────────
# TEACHERS
# ─────────────────────────────────────────────

class TeacherCreate(BaseModel):
    teacher_id: str = Field(pattern=ID_PATTERN)
    name:       str = Name()
    email:      str | None = Email()
    department: str = Dept()


@router.post("/teachers", summary="Add a single teacher")
async def add_teacher(data: TeacherCreate, request: Request, admin: Principal = AdminOnly):
    try:
        async with transaction() as conn:
            await conn.execute(
                "INSERT INTO teachers (teacher_id, name, email, department) VALUES ($1, $2, $3, $4)",
                data.teacher_id, _clean(data.name), data.email, data.department,
            )
            await conn.execute(
                """
                INSERT INTO login_credentials (role, principal_id, password_hash, must_change_password)
                VALUES ('teacher', $1, NULL, TRUE)
                ON CONFLICT (role, principal_id) DO NOTHING
                """,
                data.teacher_id,
            )
            await audit("teacher_created", admin.user_id, data.teacher_id, {}, request, conn=conn)
    except asyncpg.UniqueViolationError:
        raise HTTPException(status_code=409, detail="A teacher with this ID already exists.")
    return {"message": "Teacher created. Issue a one-time password so they can sign in.",
            "teacher_id": data.teacher_id}


@router.get("/teachers", summary="List teachers")
async def list_teachers():
    async with get_conn() as conn:
        rows = await conn.fetch(
            """
            SELECT t.teacher_id, t.name, t.email, t.department,
                   (lc.password_hash IS NOT NULL) AS has_password,
                   lc.last_login_at,
                   COALESCE(ARRAY_AGG(ct.course_id ORDER BY ct.course_id)
                            FILTER (WHERE ct.course_id IS NOT NULL), '{}') AS courses
            FROM teachers t
            LEFT JOIN login_credentials lc ON lc.role = 'teacher' AND lc.principal_id = t.teacher_id
            LEFT JOIN course_teachers ct ON ct.teacher_id = t.teacher_id
            GROUP BY t.teacher_id, lc.password_hash, lc.last_login_at
            ORDER BY t.name
            """
        )
    return [dict(r) for r in rows]


# ─────────────────────────────────────────────
# COURSES
# ─────────────────────────────────────────────

class CourseCreate(BaseModel):
    course_id:   str = Field(pattern=ID_PATTERN)
    course_name: str = Name()
    department:  str = Dept()
    semester:    int = Field(ge=1, le=12)
    credits:     int = Field(default=3, ge=0, le=12)


@router.post("/courses", summary="Add a single course")
async def add_course(data: CourseCreate, request: Request, admin: Principal = AdminOnly):
    try:
        async with transaction() as conn:
            await conn.execute(
                """
                INSERT INTO courses (course_id, course_name, department, semester, credits)
                VALUES ($1, $2, $3, $4, $5)
                """,
                data.course_id, _clean(data.course_name), data.department, data.semester, data.credits,
            )
            await audit("course_created", admin.user_id, data.course_id, {}, request, conn=conn)
    except asyncpg.UniqueViolationError:
        raise HTTPException(status_code=409, detail="A course with this ID already exists.")
    return {"message": "Course created", "course_id": data.course_id}


@router.get("/courses", summary="List courses")
async def list_courses():
    async with get_conn() as conn:
        rows = await conn.fetch(
            "SELECT course_id, course_name, department, semester, credits "
            "FROM courses ORDER BY department, semester, course_name"
        )
    return [dict(r) for r in rows]


class AssignmentRequest(BaseModel):
    course_id:  str = Field(pattern=ID_PATTERN)
    teacher_id: str = Field(pattern=ID_PATTERN)


@router.post("/course-teachers", summary="Assign a teacher to a course")
async def assign_teacher(data: AssignmentRequest, request: Request, admin: Principal = AdminOnly):
    try:
        async with transaction() as conn:
            await conn.execute(
                """
                INSERT INTO course_teachers (course_id, teacher_id) VALUES ($1, $2)
                ON CONFLICT (course_id, teacher_id) DO NOTHING
                """,
                data.course_id, data.teacher_id,
            )
            await audit("teacher_assigned", admin.user_id, data.teacher_id,
                        {"course_id": data.course_id}, request, conn=conn)
    except asyncpg.ForeignKeyViolationError:
        raise HTTPException(status_code=404, detail="Course or teacher not found.")
    return {"message": "Assigned", **data.model_dump()}


# ─────────────────────────────────────────────
# CLASSROOMS
# ─────────────────────────────────────────────

class ClassroomCreate(BaseModel):
    classroom_id: str = Field(pattern=ID_PATTERN)
    room_number:  str = Field(min_length=1, max_length=40)
    building:     str | None = Field(default=None, max_length=80)
    capacity:     int | None = Field(default=None, ge=1, le=2000)
    access_pin:   str | None = Field(default=None, max_length=12)


class PinUpdate(BaseModel):
    pin: str = Field(min_length=1, max_length=12)


def _check_pin(pin: str) -> None:
    problems = pin_problems(pin)
    if problems:
        raise HTTPException(status_code=400, detail=" ".join(problems))


@router.post("/classrooms", summary="Add or update a classroom")
async def add_classroom(data: ClassroomCreate, request: Request, admin: Principal = AdminOnly):
    pin_hash = None
    if data.access_pin:
        _check_pin(data.access_pin)
        pin_hash = await to_thread(hash_secret, data.access_pin)
    async with transaction() as conn:
        await conn.execute(
            """
            INSERT INTO classrooms (classroom_id, room_number, building, capacity, access_pin_hash)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (classroom_id) DO UPDATE
              SET room_number = EXCLUDED.room_number,
                  building    = EXCLUDED.building,
                  capacity    = EXCLUDED.capacity,
                  access_pin_hash = COALESCE(EXCLUDED.access_pin_hash, classrooms.access_pin_hash)
            """,
            data.classroom_id, data.room_number.strip(), data.building, data.capacity, pin_hash,
        )
        if pin_hash:
            await revoke_all_sessions("classroom", data.classroom_id, conn=conn)
        await audit("classroom_saved", admin.user_id, data.classroom_id,
                    {"pin_changed": bool(pin_hash)}, request, conn=conn)
    return {"message": "Classroom saved", "classroom_id": data.classroom_id}


@router.get("/classrooms", summary="List classrooms")
async def list_classrooms():
    async with get_conn() as conn:
        rows = await conn.fetch(
            """
            SELECT classroom_id, room_number, building, capacity,
                   (access_pin_hash IS NOT NULL) AS has_pin,
                   (pin_locked_until IS NOT NULL AND pin_locked_until > NOW()) AS pin_locked
            FROM classrooms
            ORDER BY classroom_id
            """
        )
    return [dict(r) for r in rows]


@router.put("/classrooms/{classroom_id}/pin", summary="Set a classroom device PIN")
async def update_classroom_pin(data: PinUpdate, request: Request, classroom_id: str = Path(pattern=ID_PATTERN),
                               admin: Principal = AdminOnly):
    _check_pin(data.pin)
    pin_hash = await to_thread(hash_secret, data.pin)
    async with transaction() as conn:
        result = await conn.execute(
            """
            UPDATE classrooms
            SET access_pin_hash = $1, pin_failed_attempts = 0, pin_locked_until = NULL
            WHERE classroom_id = $2
            """,
            pin_hash, classroom_id,
        )
        if result == "UPDATE 0":
            raise HTTPException(status_code=404, detail="Classroom not found.")
        await revoke_all_sessions("classroom", classroom_id, conn=conn)
        await audit("classroom_pin_changed", admin.user_id, classroom_id, {}, request, conn=conn)
    return {"message": "PIN updated. Devices using the old PIN were signed out.", "classroom_id": classroom_id}


# ─────────────────────────────────────────────
# SCHEDULE
# ─────────────────────────────────────────────

class ScheduleEntry(BaseModel):
    course_id:    str = Field(pattern=ID_PATTERN)
    classroom_id: str = Field(pattern=ID_PATTERN)
    day_of_week:  Literal["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    start_time:   str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    end_time:     str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")


@router.post("/schedule", summary="Add a schedule entry")
async def add_schedule(data: ScheduleEntry, request: Request, admin: Principal = AdminOnly):
    if data.end_time <= data.start_time:
        raise HTTPException(status_code=400, detail="End time must be after start time.")
    try:
        async with transaction() as conn:
            await conn.execute(
                """
                INSERT INTO weekly_schedule (course_id, classroom_id, day_of_week, start_time, end_time)
                VALUES ($1, $2, $3, $4::TIME, $5::TIME)
                """,
                data.course_id, data.classroom_id, data.day_of_week, data.start_time, data.end_time,
            )
            await audit("schedule_added", admin.user_id, data.classroom_id, data.model_dump(), request, conn=conn)
    except asyncpg.ForeignKeyViolationError:
        raise HTTPException(status_code=404, detail="Course or classroom not found.")
    return {"message": "Schedule entry added"}


@router.get("/schedule/{classroom_id}", summary="Get schedule for a classroom")
async def get_schedule(classroom_id: str = Path(pattern=ID_PATTERN)):
    async with get_conn() as conn:
        rows = await conn.fetch(
            """
            SELECT ws.schedule_id, ws.course_id, c.course_name,
                   ws.day_of_week, ws.start_time::TEXT, ws.end_time::TEXT
            FROM   weekly_schedule ws
            JOIN   courses c ON c.course_id = ws.course_id
            WHERE  ws.classroom_id = $1
            ORDER  BY ARRAY_POSITION(ARRAY['Monday','Tuesday','Wednesday','Thursday',
                                           'Friday','Saturday','Sunday'], ws.day_of_week),
                      ws.start_time
            """,
            classroom_id,
        )
    return [dict(r) for r in rows]


# ─────────────────────────────────────────────
# CSV BULK UPLOADS
# ─────────────────────────────────────────────

_IMPORTERS = {
    "students": import_students,
    "teachers": import_teachers,
    "courses": import_courses,
    "schedule": import_schedule,
    "course-teachers": import_course_teachers,
}


@router.post("/upload/{kind}", summary="Bulk upload via CSV")
async def upload_csv(
    request: Request,
    kind: Literal["students", "teachers", "courses", "schedule", "course-teachers"],
    file: UploadFile = File(...),
    admin: Principal = AdminOnly,
):
    if not (file.filename or "").lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Upload a .csv file.")
    content = await file.read(upload_cfg.max_csv_bytes + 1)
    await file.close()
    if len(content) > upload_cfg.max_csv_bytes:
        raise HTTPException(status_code=413, detail="CSV exceeds the 2 MB limit.")
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="CSV must be UTF-8 encoded.")
    try:
        result = await _IMPORTERS[kind](text)
    except CsvImportError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    await audit("csv_import", admin.user_id, kind, result, request)
    return result


# ─────────────────────────────────────────────
# AUDIT LOG
# ─────────────────────────────────────────────

@router.get("/audit-log", summary="Recent audit log entries")
async def audit_log(limit: int = 100, event_type: str | None = None):
    limit = max(1, min(limit, 1000))
    async with get_conn() as conn:
        rows = await conn.fetch(
            """
            SELECT log_id, event_type, actor_id, target_id, detail, created_at
            FROM   audit_log
            WHERE  ($2::TEXT IS NULL OR event_type = $2)
            ORDER  BY created_at DESC
            LIMIT  $1
            """,
            limit, event_type,
        )
    return [dict(r) for r in rows]


@router.get("/security/overview", summary="Security posture summary")
async def security_overview():
    async with get_conn() as conn:
        row = await conn.fetchrow(
            """
            SELECT
              (SELECT COUNT(*) FROM auth_sessions WHERE revoked_at IS NULL AND expires_at > NOW()) AS active_sessions,
              (SELECT COUNT(*) FROM login_credentials WHERE locked_until > NOW())                  AS locked_accounts,
              (SELECT COUNT(*) FROM login_credentials WHERE password_hash IS NULL)                  AS accounts_without_password,
              (SELECT COUNT(*) FROM audit_log WHERE event_type IN ('login_failed','classroom_login_failed')
                                              AND created_at > NOW() - INTERVAL '24 hours')         AS failed_logins_24h,
              (SELECT COUNT(*) FROM audit_log WHERE event_type IN ('access_denied','csrf_rejected')
                                              AND created_at > NOW() - INTERVAL '24 hours')         AS denied_requests_24h,
              (SELECT COUNT(*) FROM classrooms WHERE access_pin_hash IS NULL)                       AS classrooms_without_pin
            """
        )
    return dict(row)
