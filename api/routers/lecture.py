"""Lecture session endpoints."""

import sys

from fastapi import APIRouter, Depends, HTTPException, Path, Request
from pydantic import BaseModel, Field

from core.auth import (
    Principal,
    assert_classroom_access,
    assert_lecture_access,
    audit,
    require,
    teaches,
)
from core.database import get_conn
from core.recognition_manager import (
    build_manual_command,
    is_running_async,
    start_recognition_process,
    stop_recognition_process,
)
from core.security import ID_PATTERN
from services.analytics_service import get_live_lecture_attendance
from services.lecture_service import (
    end_lecture,
    get_active_lecture,
    get_lecture_detail,
    start_lecture,
)
from services.schedule_service import get_current_course, get_upcoming_lectures

router = APIRouter(prefix="/lecture", tags=["Lectures"])

IS_WINDOWS = sys.platform == "win32"


def _manual_command_for(principal: Principal, classroom_id: str) -> str | None:
    # The command reveals local interpreter paths; only the device itself and
    # admins need it.
    if principal.role in {"classroom", "admin"}:
        return build_manual_command(classroom_id)
    return None


async def _classroom_exists(classroom_id: str) -> bool:
    async with get_conn() as conn:
        return bool(await conn.fetchval("SELECT 1 FROM classrooms WHERE classroom_id = $1", classroom_id))


@router.get("/classrooms", summary="Classrooms available for starting a session")
async def classrooms(principal: Principal = Depends(require("teacher", "admin"))):
    async with get_conn() as conn:
        rows = await conn.fetch(
            "SELECT classroom_id, room_number, building, capacity FROM classrooms ORDER BY classroom_id"
        )
    return [dict(r) for r in rows]


@router.get("/upcoming/{classroom_id}")
async def upcoming(
    classroom_id: str = Path(pattern=ID_PATTERN),
    limit: int = 3,
    principal: Principal = Depends(require("classroom", "teacher", "admin")),
):
    await assert_classroom_access(principal, classroom_id)
    limit = max(1, min(limit, 10))
    async with get_conn() as conn:
        room = await conn.fetchrow(
            "SELECT classroom_id, room_number, building, capacity FROM classrooms WHERE classroom_id = $1",
            classroom_id,
        )
    if not room:
        raise HTTPException(status_code=404, detail="Classroom not found.")
    lectures = await get_upcoming_lectures(classroom_id, limit=limit)
    active_id = await get_active_lecture(classroom_id)
    camera_active = await is_running_async(classroom_id)
    return {
        "classroom_id":      classroom_id,
        "room_number":       room["room_number"],
        "building":          room["building"],
        "capacity":          room["capacity"],
        "active_lecture_id": active_id,
        "camera_active":     camera_active,
        "windows_mode":      IS_WINDOWS,
        "manual_command":    _manual_command_for(principal, classroom_id),
        "upcoming":          lectures,
    }


class LectureStartRequest(BaseModel):
    classroom_id: str | None = Field(default=None, pattern=ID_PATTERN)
    course_id:    str | None = Field(default=None, pattern=ID_PATTERN)
    force:        bool = True


class LectureEndRequest(BaseModel):
    lecture_id: int = Field(ge=1)


async def _resolve_course(classroom_id: str, course_id: str | None, force: bool) -> str | None:
    if course_id:
        return course_id
    course_id = await get_current_course(classroom_id)
    if not course_id and force:
        nxt = await get_upcoming_lectures(classroom_id, limit=1)
        if nxt:
            course_id = nxt[0]["course_id"]
    return course_id


@router.post("/start")
async def start(
    req: LectureStartRequest,
    request: Request,
    principal: Principal = Depends(require("classroom", "teacher", "admin")),
):
    # A classroom device can only ever operate its own room.
    classroom_id = principal.user_id if principal.role == "classroom" else req.classroom_id
    if not classroom_id:
        raise HTTPException(status_code=400, detail="classroom_id is required.")
    if not await _classroom_exists(classroom_id):
        raise HTTPException(status_code=404, detail="Classroom not found.")

    course_id = await _resolve_course(classroom_id, req.course_id, req.force)
    if not course_id:
        raise HTTPException(status_code=409, detail="No course is scheduled for this classroom.")

    async with get_conn() as conn:
        course_ok = await conn.fetchval("SELECT 1 FROM courses WHERE course_id = $1", course_id)
        scheduled_here = await conn.fetchval(
            "SELECT 1 FROM weekly_schedule WHERE classroom_id = $1 AND course_id = $2 LIMIT 1",
            classroom_id, course_id,
        )
    if not course_ok:
        raise HTTPException(status_code=404, detail="Course not found.")
    if principal.role == "teacher" and not await teaches(principal.user_id, course_id):
        raise HTTPException(status_code=403, detail="You are not assigned to this course.")
    if principal.role == "classroom" and not scheduled_here:
        raise HTTPException(status_code=403, detail="This course is not scheduled in this classroom.")

    # Refuse to hand out someone else's running lecture.
    active_id = await get_active_lecture(classroom_id)
    if active_id:
        active = await get_lecture_detail(active_id)
        if active and active["course_id"] != course_id and principal.role != "admin":
            raise HTTPException(
                status_code=409,
                detail=f"Another lecture ({active['course_id']}) is active in this classroom.",
            )

    session = await start_lecture(
        classroom_id=classroom_id,
        course_id=course_id,
        teacher_id=principal.user_id if principal.role == "teacher" else None,
        force=req.force,
    )
    if not session:
        raise HTTPException(status_code=409, detail="Lecture could not be started.")
    lecture_id = session["lecture_id"]

    cam_started = await start_recognition_process(classroom_id)
    camera_active = await is_running_async(classroom_id)

    if session["status"] == "resumed_today":
        cam_note = "Resumed today's attendance session."
    elif session["status"] == "existing_active":
        cam_note = "This lecture is already running."
    elif camera_active:
        cam_note = "Camera recognition active."
    elif IS_WINDOWS:
        cam_note = (
            "Lecture started, but the camera could not be confirmed yet. "
            "If no camera window appears, run the manual command on the classroom PC."
        )
    else:
        cam_note = "Lecture started, but the recognition process could not be confirmed."

    await audit("lecture_started", principal.user_id, str(lecture_id),
                {"role": principal.role, "classroom_id": classroom_id, "course_id": course_id,
                 "status": session["status"]}, request)
    return {
        "lecture_id":     lecture_id,
        "classroom_id":   classroom_id,
        "course_id":      course_id,
        "camera_started": cam_started,
        "camera_active":  camera_active,
        "windows_mode":   IS_WINDOWS,
        "session_status": session["status"],
        "resumed_today":  session["status"] == "resumed_today",
        "message":        cam_note,
        "manual_command": _manual_command_for(principal, classroom_id),
    }


@router.post("/end")
async def end(
    req: LectureEndRequest,
    request: Request,
    principal: Principal = Depends(require("classroom", "teacher", "admin")),
):
    ctx = await assert_lecture_access(principal, req.lecture_id)
    ok = await end_lecture(req.lecture_id)
    if not ok:
        raise HTTPException(status_code=409, detail="Lecture already closed.")
    cam_stopped = await stop_recognition_process(ctx["classroom_id"])
    await audit("lecture_ended", principal.user_id, str(req.lecture_id),
                {"role": principal.role, "classroom_id": ctx["classroom_id"]}, request)
    return {"message": f"Lecture {req.lecture_id} closed.", "camera_stopped": cam_stopped}


@router.post("/force-close/{classroom_id}", summary="Close any stale active lecture in a classroom")
async def force_close(
    request: Request,
    classroom_id: str = Path(pattern=ID_PATTERN),
    principal: Principal = Depends(require("classroom", "admin")),
):
    if principal.role == "classroom" and principal.user_id != classroom_id:
        raise HTTPException(status_code=403, detail="You do not have access to this resource.")
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
    await audit("lecture_force_closed", principal.user_id, classroom_id, {"closed": closed}, request)
    return {"classroom_id": classroom_id, "lectures_closed": closed}


@router.get("/active/{classroom_id}")
async def active(
    classroom_id: str = Path(pattern=ID_PATTERN),
    principal: Principal = Depends(require("classroom", "teacher", "admin")),
):
    await assert_classroom_access(principal, classroom_id)
    lecture_id = await get_active_lecture(classroom_id)
    camera_active = await is_running_async(classroom_id)
    detail = await get_lecture_detail(lecture_id) if lecture_id else None
    can_manage = bool(detail) and (
        principal.role in {"admin", "classroom"}
        or await teaches(principal.user_id, detail["course_id"])
    )
    return {
        "classroom_id":   classroom_id,
        "lecture_id":     lecture_id,
        "course_id":      detail["course_id"] if detail else None,
        "course_name":    detail["course_name"] if detail else None,
        "can_manage":     can_manage,
        "camera_active":  camera_active,
        "windows_mode":   IS_WINDOWS,
        "manual_command": _manual_command_for(principal, classroom_id),
    }


@router.get("/{lecture_id}/live")
async def live(lecture_id: int, principal: Principal = Depends(require("classroom", "teacher", "admin"))):
    await assert_lecture_access(principal, lecture_id)
    data = await get_live_lecture_attendance(lecture_id)
    if not data:
        raise HTTPException(status_code=404, detail="Lecture not found.")
    return data


@router.get("/{lecture_id}")
async def detail(lecture_id: int, principal: Principal = Depends(require("classroom", "teacher", "admin"))):
    await assert_lecture_access(principal, lecture_id)
    data = await get_lecture_detail(lecture_id)
    if not data:
        raise HTTPException(status_code=404, detail="Lecture not found.")
    return data
