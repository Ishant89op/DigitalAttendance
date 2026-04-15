"""Lecture session endpoints."""

import sys
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from services.lecture_service import (
    start_lecture, end_lecture, get_active_lecture, get_lecture_detail,
)
from services.schedule_service import get_upcoming_lectures
from services.analytics_service import get_live_lecture_attendance
from core.recognition_manager import (
    build_manual_command,
    is_running_async,
    start_recognition_process,
    stop_recognition_process,
)
from core.database import get_conn

router = APIRouter(prefix="/lecture", tags=["Lectures"])

IS_WINDOWS = sys.platform == "win32"


class ClassroomLoginRequest(BaseModel):
    classroom_id: str
    pin: str


@router.post("/classroom-login")
async def classroom_login(req: ClassroomLoginRequest):
    async with get_conn() as conn:
        row = await conn.fetchrow(
            "SELECT classroom_id, room_number, building, capacity, access_pin "
            "FROM classrooms WHERE classroom_id = $1",
            req.classroom_id,
        )
    if not row:
        raise HTTPException(status_code=404, detail="Classroom not found.")
    stored_pin = row["access_pin"] or "1234"
    if req.pin != stored_pin:
        raise HTTPException(status_code=401, detail="Incorrect PIN.")

    upcoming = await get_upcoming_lectures(req.classroom_id, limit=3)
    active_id = await get_active_lecture(req.classroom_id)
    camera_active = await is_running_async(req.classroom_id)
    return {
        "classroom_id":      row["classroom_id"],
        "room_number":       row["room_number"],
        "building":          row["building"],
        "capacity":          row["capacity"],
        "active_lecture_id": active_id,
        "camera_active":     camera_active,
        "windows_mode":      IS_WINDOWS,
        "manual_command":    build_manual_command(req.classroom_id),
        "upcoming_lectures": upcoming,
    }


@router.get("/upcoming/{classroom_id}")
async def upcoming(classroom_id: str, limit: int = 3):
    lectures = await get_upcoming_lectures(classroom_id, limit=limit)
    active_id = await get_active_lecture(classroom_id)
    camera_active = await is_running_async(classroom_id)
    return {
        "classroom_id":      classroom_id,
        "active_lecture_id": active_id,
        "camera_active":     camera_active,
        "windows_mode":      IS_WINDOWS,
        "manual_command":    build_manual_command(classroom_id),
        "upcoming":          lectures,
    }


class LectureStartRequest(BaseModel):
    classroom_id: str
    course_id:    str | None = None
    teacher_id:   str | None = None
    force:        bool = True


class LectureEndRequest(BaseModel):
    lecture_id: int


@router.post("/start")
async def start(req: LectureStartRequest):
    lecture_id = await start_lecture(
        classroom_id=req.classroom_id,
        course_id=req.course_id,
        teacher_id=req.teacher_id,
        force=req.force,
    )
    if not lecture_id:
        raise HTTPException(
            status_code=409,
            detail="No course assigned or lecture already active.",
        )

    manual_command = build_manual_command(req.classroom_id)
    cam_started = await start_recognition_process(req.classroom_id)
    camera_active = await is_running_async(req.classroom_id)

    if camera_active:
        cam_note = "Camera recognition active."
    elif IS_WINDOWS:
        cam_note = (
            "Lecture started, but camera could not be confirmed yet. "
            "If no new camera window appears, run the manual command."
        )
    else:
        cam_note = "Lecture started, but recognition process could not be confirmed."

    return {
        "lecture_id":     lecture_id,
        "classroom_id":   req.classroom_id,
        "camera_started": cam_started,
        "camera_active":  camera_active,
        "windows_mode":   IS_WINDOWS,
        "message":        cam_note,
        "manual_command": manual_command,
    }


@router.post("/end")
async def end(req: LectureEndRequest):
    detail = await get_lecture_detail(req.lecture_id)
    if not detail:
        raise HTTPException(status_code=404, detail="Lecture not found.")
    ok = await end_lecture(req.lecture_id)
    if not ok:
        raise HTTPException(status_code=409, detail="Lecture already closed.")
    cam_stopped = await stop_recognition_process(detail["classroom_id"])
    return {"message": f"Lecture {req.lecture_id} closed.", "camera_stopped": cam_stopped}


@router.post("/force-close/{classroom_id}", summary="Force-close any stale active lecture")
async def force_close(classroom_id: str):
    """
    Close any stuck active lecture for this classroom.
    Use this when the DB shows a lecture as active but no session is running.
    """
    async with get_conn() as conn:
        result = await conn.execute(
            """
            UPDATE lecture_sessions
            SET status = 'closed', end_time = NOW()
            WHERE classroom_id = $1 AND status = 'active'
            """,
            classroom_id,
        )
    closed = int(result.split()[-1])
    await stop_recognition_process(classroom_id)
    return {"classroom_id": classroom_id, "lectures_closed": closed}


@router.get("/active/{classroom_id}")
async def active(classroom_id: str):
    lecture_id = await get_active_lecture(classroom_id)
    camera_active = await is_running_async(classroom_id)
    return {
        "classroom_id":  classroom_id,
        "lecture_id":    lecture_id,
        "camera_active": camera_active,
        "windows_mode":  IS_WINDOWS,
        "manual_command": build_manual_command(classroom_id),
    }


@router.get("/{lecture_id}/live")
async def live(lecture_id: int):
    data = await get_live_lecture_attendance(lecture_id)
    if not data:
        raise HTTPException(status_code=404, detail="Lecture not found.")
    return data


@router.get("/{lecture_id}")
async def detail(lecture_id: int):
    data = await get_lecture_detail(lecture_id)
    if not data:
        raise HTTPException(status_code=404, detail="Lecture not found.")
    return data
