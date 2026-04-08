"""Admin management endpoints."""

import os
import shutil
import tempfile

from fastapi import APIRouter, HTTPException, UploadFile, File
from pydantic import BaseModel

from core.database import get_conn, transaction
from services.csv_service import (
    import_students,
    import_teachers,
    import_courses,
    import_schedule,
    import_course_teachers,
)

router = APIRouter(prefix="/admin", tags=["Admin"])


# ─────────────────────────────────────────────
# STUDENTS
# ─────────────────────────────────────────────

class StudentCreate(BaseModel):
    student_id: str
    name:       str
    email:      str | None = None
    department: str
    semester:   int


@router.post("/students", summary="Add a single student")
async def add_student(data: StudentCreate):
    async with transaction() as conn:
        try:
            await conn.execute(
                """
                INSERT INTO students (student_id, name, email, department, semester)
                VALUES ($1, $2, $3, $4, $5)
                """,
                data.student_id, data.name, data.email,
                data.department, data.semester,
            )
        except Exception as e:
            raise HTTPException(status_code=409, detail=f"Student already exists: {e}")
    return {"message": "Student created", "student_id": data.student_id}


@router.get("/students", summary="List all students")
async def list_students(department: str | None = None, semester: int | None = None):
    async with get_conn() as conn:
        rows = await conn.fetch(
            """
            SELECT student_id, name, email, department, semester,
                   (face_encoding IS NOT NULL) AS face_registered,
                   registered_at
            FROM   students
            WHERE  ($1::TEXT IS NULL OR department = $1)
              AND  ($2::INT  IS NULL OR semester   = $2)
            ORDER  BY name
            """,
            department, semester,
        )
    return [dict(r) for r in rows]


@router.put("/students/{student_id}", summary="Update a student")
async def update_student(student_id: str, data: StudentCreate):
    async with transaction() as conn:
        result = await conn.execute(
            """
            UPDATE students SET name=$1, email=$2, department=$3, semester=$4
            WHERE student_id=$5
            """,
            data.name, data.email, data.department, data.semester, student_id,
        )
    if result == "UPDATE 0":
        raise HTTPException(status_code=404, detail="Student not found")
    return {"message": "Updated", "student_id": student_id}


@router.delete("/students/{student_id}", summary="Delete a student")
async def delete_student(student_id: str):
    async with transaction() as conn:
        result = await conn.execute(
            "DELETE FROM students WHERE student_id=$1", student_id
        )
    if result == "DELETE 0":
        raise HTTPException(status_code=404, detail="Student not found")
    return {"message": "Deleted", "student_id": student_id}


# ─────────────────────────────────────────────
# TEACHERS
# ─────────────────────────────────────────────

class TeacherCreate(BaseModel):
    teacher_id: str
    name:       str
    email:      str | None = None
    department: str


@router.post("/teachers", summary="Add a single teacher")
async def add_teacher(data: TeacherCreate):
    async with transaction() as conn:
        try:
            await conn.execute(
                """
                INSERT INTO teachers (teacher_id, name, email, department)
                VALUES ($1, $2, $3, $4)
                """,
                data.teacher_id, data.name, data.email, data.department,
            )
        except Exception as e:
            raise HTTPException(status_code=409, detail=str(e))
    return {"message": "Teacher created", "teacher_id": data.teacher_id}


@router.get("/teachers", summary="List all teachers")
async def list_teachers():
    async with get_conn() as conn:
        rows = await conn.fetch(
            "SELECT teacher_id, name, email, department FROM teachers ORDER BY name"
        )
    return [dict(r) for r in rows]


# ─────────────────────────────────────────────
# COURSES
# ─────────────────────────────────────────────

class CourseCreate(BaseModel):
    course_id:   str
    course_name: str
    department:  str
    semester:    int
    credits:     int = 3


@router.post("/courses", summary="Add a single course")
async def add_course(data: CourseCreate):
    async with transaction() as conn:
        try:
            await conn.execute(
                """
                INSERT INTO courses (course_id, course_name, department, semester, credits)
                VALUES ($1, $2, $3, $4, $5)
                """,
                data.course_id, data.course_name,
                data.department, data.semester, data.credits,
            )
        except Exception as e:
            raise HTTPException(status_code=409, detail=str(e))
    return {"message": "Course created", "course_id": data.course_id}


@router.get("/courses", summary="List all courses")
async def list_courses():
    async with get_conn() as conn:
        rows = await conn.fetch(
            "SELECT course_id, course_name, department, semester, credits "
            "FROM courses ORDER BY department, semester, course_name"
        )
    return [dict(r) for r in rows]


# ─────────────────────────────────────────────
# CLASSROOMS
# ─────────────────────────────────────────────

class ClassroomCreate(BaseModel):
    classroom_id: str
    room_number:  str
    building:     str | None = None
    capacity:     int | None = None
    access_pin:   str = "1234"


@router.post("/classrooms", summary="Add a classroom")
async def add_classroom(data: ClassroomCreate):
    async with transaction() as conn:
        await conn.execute(
            """
            INSERT INTO classrooms (classroom_id, room_number, building, capacity, access_pin)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (classroom_id) DO UPDATE
              SET room_number=$2, building=$3, capacity=$4, access_pin=$5
            """,
            data.classroom_id, data.room_number, data.building,
            data.capacity, data.access_pin,
        )
    return {"message": "Classroom saved", "classroom_id": data.classroom_id}


@router.get("/classrooms", summary="List all classrooms")
async def list_classrooms():
    async with get_conn() as conn:
        rows = await conn.fetch(
            "SELECT classroom_id, room_number, building, capacity FROM classrooms ORDER BY classroom_id"
        )
    return [dict(r) for r in rows]


@router.put("/classrooms/{classroom_id}/pin", summary="Update classroom PIN")
async def update_classroom_pin(classroom_id: str, pin: str):
    async with transaction() as conn:
        result = await conn.execute(
            "UPDATE classrooms SET access_pin=$1 WHERE classroom_id=$2",
            pin, classroom_id,
        )
    if result == "UPDATE 0":
        raise HTTPException(status_code=404, detail="Classroom not found")
    return {"message": "PIN updated", "classroom_id": classroom_id}


# ─────────────────────────────────────────────
# SCHEDULE
# ─────────────────────────────────────────────

class ScheduleEntry(BaseModel):
    course_id:    str
    classroom_id: str
    day_of_week:  str
    start_time:   str
    end_time:     str


@router.post("/schedule", summary="Add a schedule entry")
async def add_schedule(data: ScheduleEntry):
    async with transaction() as conn:
        await conn.execute(
            """
            INSERT INTO weekly_schedule
                (course_id, classroom_id, day_of_week, start_time, end_time)
            VALUES ($1, $2, $3, $4::TIME, $5::TIME)
            """,
            data.course_id, data.classroom_id,
            data.day_of_week, data.start_time, data.end_time,
        )
    return {"message": "Schedule entry added"}


@router.get("/schedule/{classroom_id}", summary="Get schedule for a classroom")
async def get_schedule(classroom_id: str):
    async with get_conn() as conn:
        rows = await conn.fetch(
            """
            SELECT ws.schedule_id, ws.course_id, c.course_name,
                   ws.day_of_week, ws.start_time::TEXT, ws.end_time::TEXT
            FROM   weekly_schedule ws
            JOIN   courses c ON c.course_id = ws.course_id
            WHERE  ws.classroom_id = $1
            ORDER  BY ws.day_of_week, ws.start_time
            """,
            classroom_id,
        )
    return [dict(r) for r in rows]


# ─────────────────────────────────────────────
# CSV BULK UPLOADS
# ─────────────────────────────────────────────

async def _save_temp(file: UploadFile) -> str:
    fd, path = tempfile.mkstemp(suffix=".csv")
    with os.fdopen(fd, "wb") as f:
        shutil.copyfileobj(file.file, f)
    return path


@router.post("/upload/students",  summary="Bulk upload students via CSV")
async def upload_students(file: UploadFile = File(...)):
    path = await _save_temp(file)
    result = await import_students(path)
    os.unlink(path)
    return result


@router.post("/upload/teachers",  summary="Bulk upload teachers via CSV")
async def upload_teachers(file: UploadFile = File(...)):
    path = await _save_temp(file)
    result = await import_teachers(path)
    os.unlink(path)
    return result


@router.post("/upload/courses",   summary="Bulk upload courses via CSV")
async def upload_courses(file: UploadFile = File(...)):
    path = await _save_temp(file)
    result = await import_courses(path)
    os.unlink(path)
    return result


@router.post("/upload/schedule",  summary="Bulk upload schedule via CSV")
async def upload_schedule(file: UploadFile = File(...)):
    path = await _save_temp(file)
    result = await import_schedule(path)
    os.unlink(path)
    return result


@router.post("/upload/course-teachers", summary="Bulk upload course-teacher assignments")
async def upload_course_teachers(file: UploadFile = File(...)):
    path = await _save_temp(file)
    result = await import_course_teachers(path)
    os.unlink(path)
    return result


# ─────────────────────────────────────────────
# AUDIT LOG
# ─────────────────────────────────────────────

@router.get("/audit-log", summary="View recent audit log entries")
async def audit_log(limit: int = 100):
    async with get_conn() as conn:
        rows = await conn.fetch(
            """
            SELECT log_id, event_type, actor_id, target_id, detail, created_at
            FROM   audit_log
            ORDER  BY created_at DESC
            LIMIT  $1
            """,
            limit,
        )
    return [dict(r) for r in rows]
