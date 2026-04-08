"""Analytics endpoints — student, teacher, admin."""

from fastapi import APIRouter, HTTPException, Query

from services.analytics_service import (
    get_student_summary,
    get_student_history,
    get_teacher_course_stats,
    get_admin_dashboard,
    get_low_attendance_alerts,
)

router = APIRouter(prefix="/analytics", tags=["Analytics"])


# ─────────────────────────────────────────────
# STUDENT
# ─────────────────────────────────────────────

@router.get("/student/{student_id}", summary="Full attendance summary for a student")
async def student_summary(student_id: str):
    data = await get_student_summary(student_id)
    if not data:
        raise HTTPException(status_code=404, detail="Student not found.")
    return data


@router.get("/student/{student_id}/history", summary="Attendance history for a student")
async def student_history(
    student_id: str,
    course_id: str | None = Query(default=None, description="Filter by course"),
    limit: int = Query(default=50, ge=1, le=500),
):
    return await get_student_history(student_id, course_id, limit)


# ─────────────────────────────────────────────
# TEACHER
# ─────────────────────────────────────────────

@router.get("/teacher/{teacher_id}", summary="Attendance stats across a teacher's courses")
async def teacher_stats(teacher_id: str):
    return await get_teacher_course_stats(teacher_id)


# ─────────────────────────────────────────────
# ADMIN
# ─────────────────────────────────────────────

@router.get("/admin/dashboard", summary="System-wide admin dashboard data")
async def admin_dashboard():
    return await get_admin_dashboard()


@router.get("/admin/alerts", summary="Low attendance alerts across all subjects")
async def low_attendance_alerts():
    return await get_low_attendance_alerts()
