"""Attendance endpoints."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from attendance.attendance_manager import mark_attendance, manual_override
from core.database import get_conn

router = APIRouter(prefix="/attendance", tags=["Attendance"])


class MarkRequest(BaseModel):
    student_id: str
    lecture_id: int


class OverrideRequest(BaseModel):
    student_id: str
    lecture_id: int
    teacher_id: str
    present:    bool


@router.post("/mark", summary="Mark attendance (face recognition path)")
async def mark(req: MarkRequest):
    inserted = await mark_attendance(req.student_id, req.lecture_id)
    return {
        "student_id": req.student_id,
        "lecture_id": req.lecture_id,
        "new_record": inserted,
    }


@router.post("/override", summary="Teacher manual attendance override")
async def override(req: OverrideRequest):
    result = await manual_override(
        req.student_id, req.lecture_id, req.teacher_id, req.present
    )
    return result


@router.get("/count/{lecture_id}", summary="Count present students for a lecture")
async def count(lecture_id: int):
    async with get_conn() as conn:
        n = await conn.fetchval(
            "SELECT COUNT(*) FROM attendance WHERE lecture_id = $1", lecture_id
        )
    return {"lecture_id": lecture_id, "count": n}


@router.get("/list/{lecture_id}", summary="List all present students for a lecture")
async def list_attendance(lecture_id: int):
    async with get_conn() as conn:
        rows = await conn.fetch(
            """
            SELECT a.student_id, s.name, a.timestamp, a.source
            FROM   attendance a
            JOIN   students s ON s.student_id = a.student_id
            WHERE  a.lecture_id = $1
            ORDER  BY s.name
            """,
            lecture_id,
        )
    return [dict(r) for r in rows]
