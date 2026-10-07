"""Analytics endpoints — student, teacher, admin."""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from core.auth import Principal, assert_self, audit, require
from core.security import ID_PATTERN
from services.analytics_service import (
    generate_weekly_defaulter_reminders,
    get_admin_dashboard,
    get_admin_risk_forecast,
    get_filtered_attendance_export,
    get_low_attendance_alerts,
    get_student_history,
    get_student_risk_forecast,
    get_student_summary,
    get_teacher_course_detail,
    get_teacher_course_stats,
    get_teacher_dashboard,
    list_defaulter_reminders,
    mark_defaulter_reminders_sent,
)
from services.teacher_export_service import (
    build_attendance_excel,
    build_attendance_pdf,
    build_export_filename,
    build_filtered_attendance_excel,
    build_filtered_attendance_pdf,
    build_filtered_export_filename,
)

router = APIRouter(prefix="/analytics", tags=["Analytics"])

EXCEL_MEDIA = "application/vnd.ms-excel"


class ReminderMarkRequest(BaseModel):
    reminder_ids: list[int] | None = Field(default=None, max_length=5000)


def _date_range(from_date: date | None, to_date: date | None) -> None:
    if from_date and to_date and from_date > to_date:
        raise HTTPException(status_code=400, detail="from_date must be on or before to_date.")


def _download(content: bytes, media_type: str, filename: str) -> Response:
    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "private, no-store",
        },
    )


# ─────────────────────────────────────────────
# STUDENT (self, or admin)
# ─────────────────────────────────────────────

@router.get("/student/{student_id}", summary="Attendance summary for a student")
async def student_summary(student_id: str = Path(pattern=ID_PATTERN), principal: Principal = Depends(require("student", "admin"))):
    assert_self(principal, student_id)
    data = await get_student_summary(student_id)
    if not data:
        raise HTTPException(status_code=404, detail="Student not found.")
    return data


@router.get("/student/{student_id}/history", summary="Attendance history for a student")
async def student_history(
    student_id: str = Path(pattern=ID_PATTERN),
    course_id: str | None = Query(default=None, pattern=ID_PATTERN),
    include_absent: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=500),
    principal: Principal = Depends(require("student", "admin")),
):
    assert_self(principal, student_id)
    return await get_student_history(student_id, course_id, limit, include_absent)


@router.get("/student/{student_id}/forecast", summary="Risk forecast for a student")
async def student_forecast(
    student_id: str = Path(pattern=ID_PATTERN),
    recent_window: int = Query(default=6, ge=1, le=20),
    projection_lectures: int = Query(default=6, ge=1, le=30),
    principal: Principal = Depends(require("student", "admin")),
):
    assert_self(principal, student_id)
    return await get_student_risk_forecast(student_id, recent_window, projection_lectures)


# ─────────────────────────────────────────────
# TEACHER (self, or admin)
# ─────────────────────────────────────────────

@router.get("/teacher/{teacher_id}/dashboard", summary="Teacher dashboard")
async def teacher_dashboard_view(teacher_id: str = Path(pattern=ID_PATTERN), principal: Principal = Depends(require("teacher", "admin"))):
    assert_self(principal, teacher_id)
    return await get_teacher_dashboard(teacher_id)


@router.get("/teacher/{teacher_id}/courses/{course_id}", summary="Student-level detail for one course")
async def teacher_course_view(
    teacher_id: str = Path(pattern=ID_PATTERN),
    course_id: str = Path(pattern=ID_PATTERN),
    principal: Principal = Depends(require("teacher", "admin")),
):
    assert_self(principal, teacher_id)
    data = await get_teacher_course_detail(teacher_id, course_id)
    if not data:
        raise HTTPException(status_code=404, detail="Course not found for this teacher.")
    return data


@router.get("/teacher/{teacher_id}/courses/{course_id}/export", summary="Download attendance sheet")
async def teacher_course_export(
    request: Request,
    teacher_id: str = Path(pattern=ID_PATTERN),
    course_id: str = Path(pattern=ID_PATTERN),
    format: str = Query(default="excel", pattern="^(excel|pdf)$"),
    from_date: date | None = Query(default=None),
    to_date: date | None = Query(default=None),
    principal: Principal = Depends(require("teacher", "admin")),
):
    assert_self(principal, teacher_id)
    _date_range(from_date, to_date)
    report = await get_teacher_course_detail(teacher_id, course_id)
    if not report:
        raise HTTPException(status_code=404, detail="Course not found for this teacher.")

    if from_date or to_date:
        filtered = await get_filtered_attendance_export(course_id=course_id, from_date=from_date, to_date=to_date)
        content = build_filtered_attendance_excel(filtered) if format == "excel" else build_filtered_attendance_pdf(filtered)
        filename = build_filtered_export_filename(format, course_id, None, from_date, to_date)
    else:
        content = build_attendance_excel(report) if format == "excel" else build_attendance_pdf(report)
        filename = build_export_filename(course_id, format)

    await audit("export_downloaded", principal.user_id, course_id,
                {"format": format, "from": from_date, "to": to_date}, request)
    return _download(content, EXCEL_MEDIA if format == "excel" else "application/pdf", filename)


@router.get("/teacher/{teacher_id}", summary="Attendance stats across a teacher's courses")
async def teacher_stats(teacher_id: str = Path(pattern=ID_PATTERN), principal: Principal = Depends(require("teacher", "admin"))):
    assert_self(principal, teacher_id)
    return await get_teacher_course_stats(teacher_id)


# ─────────────────────────────────────────────
# ADMIN
# ─────────────────────────────────────────────

admin_only = Depends(require("admin"))


@router.get("/admin/dashboard", summary="System-wide dashboard", dependencies=[admin_only])
async def admin_dashboard():
    return await get_admin_dashboard()


@router.get("/admin/alerts", summary="Low attendance alerts", dependencies=[admin_only])
async def low_attendance_alerts():
    return await get_low_attendance_alerts()


@router.post("/admin/reminders/generate", summary="Generate weekly defaulter reminders", dependencies=[admin_only])
async def generate_reminders(force: bool = Query(default=False)):
    return await generate_weekly_defaulter_reminders(force=force)


@router.get("/admin/reminders", summary="Reminder queue", dependencies=[admin_only])
async def list_reminders(
    status: str | None = Query(default=None, pattern="^(pending|sent)$"),
    limit: int = Query(default=200, ge=1, le=2000),
):
    return await list_defaulter_reminders(status=status, limit=limit)


@router.post("/admin/reminders/mark-sent", summary="Mark reminders as sent", dependencies=[admin_only])
async def mark_reminders_sent(req: ReminderMarkRequest):
    return await mark_defaulter_reminders_sent(reminder_ids=req.reminder_ids)


@router.get("/admin/risk-forecast", summary="Students likely to remain below threshold", dependencies=[admin_only])
async def admin_risk_forecast(
    limit: int = Query(default=50, ge=1, le=500),
    recent_window: int = Query(default=6, ge=1, le=20),
    projection_lectures: int = Query(default=6, ge=1, le=30),
):
    return await get_admin_risk_forecast(limit=limit, recent_window=recent_window,
                                         projection_lectures=projection_lectures)


@router.get("/admin/export", summary="Export by course/date/semester")
async def admin_export(
    request: Request,
    format: str = Query(default="excel", pattern="^(excel|pdf)$"),
    course_id: str | None = Query(default=None, pattern=ID_PATTERN),
    department: str | None = Query(default=None, max_length=32),
    semester: int | None = Query(default=None, ge=1, le=12),
    from_date: date | None = Query(default=None),
    to_date: date | None = Query(default=None),
    principal: Principal = Depends(require("admin")),
):
    _date_range(from_date, to_date)
    report = await get_filtered_attendance_export(
        course_id=course_id, department=department, semester=semester,
        from_date=from_date, to_date=to_date,
    )
    content = build_filtered_attendance_excel(report) if format == "excel" else build_filtered_attendance_pdf(report)
    await audit("export_downloaded", principal.user_id, course_id or "all",
                {"format": format, "department": department, "semester": semester}, request)
    return _download(
        content,
        EXCEL_MEDIA if format == "excel" else "application/pdf",
        build_filtered_export_filename(format, course_id, semester, from_date, to_date),
    )
