"""Analytics endpoints — student, teacher, admin."""

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from services.analytics_service import (
    get_student_summary,
    get_student_history,
    get_teacher_course_stats,
    get_teacher_dashboard,
    get_teacher_course_detail,
    get_admin_dashboard,
    get_low_attendance_alerts,
)
from services.teacher_export_service import (
    build_attendance_excel,
    build_attendance_pdf,
    build_export_filename,
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

@router.get("/teacher/{teacher_id}/dashboard", summary="Teacher dashboard with course summaries")
async def teacher_dashboard_view(teacher_id: str):
    return await get_teacher_dashboard(teacher_id)


@router.get("/teacher/{teacher_id}/courses/{course_id}", summary="Student-level attendance for one teacher course")
async def teacher_course_view(teacher_id: str, course_id: str):
    data = await get_teacher_course_detail(teacher_id, course_id)
    if not data:
        raise HTTPException(status_code=404, detail="Course not found for this teacher.")
    return data


@router.get("/teacher/{teacher_id}/courses/{course_id}/export", summary="Download teacher attendance sheet")
async def teacher_course_export(
    teacher_id: str,
    course_id: str,
    format: str = Query(default="excel", pattern="^(excel|pdf)$"),
):
    report = await get_teacher_course_detail(teacher_id, course_id)
    if not report:
        raise HTTPException(status_code=404, detail="Course not found for this teacher.")

    if format == "excel":
        content = build_attendance_excel(report)
        media_type = "application/vnd.ms-excel"
    else:
        content = build_attendance_pdf(report)
        media_type = "application/pdf"

    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Content-Disposition": (
                f'attachment; filename="{build_export_filename(course_id, format)}"'
            )
        },
    )


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
