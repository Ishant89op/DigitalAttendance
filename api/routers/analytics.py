"""Analytics endpoints — student, teacher, admin."""

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel

from services.analytics_service import (
    get_student_summary,
    get_student_history,
    get_student_risk_forecast,
    get_teacher_course_stats,
    get_teacher_dashboard,
    get_teacher_course_detail,
    get_admin_dashboard,
    get_low_attendance_alerts,
    generate_weekly_defaulter_reminders,
    list_defaulter_reminders,
    mark_defaulter_reminders_sent,
    get_admin_risk_forecast,
    get_filtered_attendance_export,
)
from services.teacher_export_service import (
    build_attendance_excel,
    build_attendance_pdf,
    build_filtered_attendance_excel,
    build_filtered_attendance_pdf,
    build_export_filename,
    build_filtered_export_filename,
)

router = APIRouter(prefix="/analytics", tags=["Analytics"])


class ReminderMarkRequest(BaseModel):
    reminder_ids: list[int] | None = None


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
    include_absent: bool = Query(default=False, description="Include absent sessions"),
    limit: int = Query(default=50, ge=1, le=500),
):
    return await get_student_history(student_id, course_id, limit, include_absent)


@router.get("/student/{student_id}/forecast", summary="Risk forecast for a student")
async def student_forecast(
    student_id: str,
    recent_window: int = Query(default=6, ge=1, le=20),
    projection_lectures: int = Query(default=6, ge=1, le=30),
):
    return await get_student_risk_forecast(student_id, recent_window, projection_lectures)


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
    from_date: str | None = Query(default=None, description="YYYY-MM-DD"),
    to_date: str | None = Query(default=None, description="YYYY-MM-DD"),
):
    report = await get_teacher_course_detail(teacher_id, course_id)
    if not report:
        raise HTTPException(status_code=404, detail="Course not found for this teacher.")

    if from_date or to_date:
        filtered_report = await get_filtered_attendance_export(
            course_id=course_id,
            from_date=from_date,
            to_date=to_date,
        )
        if format == "excel":
            content = build_filtered_attendance_excel(filtered_report)
            media_type = "application/vnd.ms-excel"
        else:
            content = build_filtered_attendance_pdf(filtered_report)
            media_type = "application/pdf"
    else:
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
                f'attachment; filename="{build_filtered_export_filename(format, course_id, None, from_date, to_date) if (from_date or to_date) else build_export_filename(course_id, format)}"'
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


@router.post("/admin/reminders/generate", summary="Generate weekly defaulter reminders")
async def generate_reminders(force: bool = Query(default=False)):
    return await generate_weekly_defaulter_reminders(force=force)


@router.get("/admin/reminders", summary="List reminder queue")
async def list_reminders(
    status: str | None = Query(default=None, pattern="^(pending|sent)$"),
    limit: int = Query(default=200, ge=1, le=2000),
):
    return await list_defaulter_reminders(status=status, limit=limit)


@router.post("/admin/reminders/mark-sent", summary="Mark reminders as sent")
async def mark_reminders_sent(req: ReminderMarkRequest):
    return await mark_defaulter_reminders_sent(reminder_ids=req.reminder_ids)


@router.get("/admin/risk-forecast", summary="Students likely to remain below threshold")
async def admin_risk_forecast(
    limit: int = Query(default=50, ge=1, le=500),
    recent_window: int = Query(default=6, ge=1, le=20),
    projection_lectures: int = Query(default=6, ge=1, le=30),
):
    return await get_admin_risk_forecast(limit=limit, recent_window=recent_window, projection_lectures=projection_lectures)


@router.get("/admin/export", summary="Smart export by course/date/semester")
async def admin_export(
    format: str = Query(default="excel", pattern="^(excel|pdf)$"),
    course_id: str | None = Query(default=None),
    department: str | None = Query(default=None),
    semester: int | None = Query(default=None, ge=1, le=12),
    from_date: str | None = Query(default=None, description="YYYY-MM-DD"),
    to_date: str | None = Query(default=None, description="YYYY-MM-DD"),
):
    report = await get_filtered_attendance_export(
        course_id=course_id,
        department=department,
        semester=semester,
        from_date=from_date,
        to_date=to_date,
    )

    if format == "excel":
        content = build_filtered_attendance_excel(report)
        media_type = "application/vnd.ms-excel"
    else:
        content = build_filtered_attendance_pdf(report)
        media_type = "application/pdf"

    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Content-Disposition": (
                f'attachment; filename="{build_filtered_export_filename(format, course_id, semester, from_date, to_date)}"'
            )
        },
    )
