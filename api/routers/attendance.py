"""Attendance endpoints."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from attendance.attendance_manager import mark_attendance, manual_override
from core.database import get_conn
from services.dispute_service import (
    create_dispute,
    list_student_disputes,
    list_disputes,
    resolve_dispute,
)

router = APIRouter(prefix="/attendance", tags=["Attendance"])


class MarkRequest(BaseModel):
    student_id: str
    lecture_id: int


class OverrideRequest(BaseModel):
    student_id: str
    lecture_id: int
    teacher_id: str
    present:    bool


class DisputeCreateRequest(BaseModel):
    student_id: str
    course_id: str | None = None
    lecture_id: int | None = None
    reason: str
    evidence: str | None = None


class DisputeResolveRequest(BaseModel):
    reviewer_id: str
    reviewer_role: str
    action: str
    resolution_note: str | None = None


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


@router.post("/disputes", summary="Create attendance dispute")
async def create_dispute_endpoint(req: DisputeCreateRequest):
    return await create_dispute(
        student_id=req.student_id,
        course_id=req.course_id,
        lecture_id=req.lecture_id,
        reason=req.reason,
        evidence=req.evidence,
    )


@router.get("/disputes/student/{student_id}", summary="List disputes raised by a student")
async def student_disputes(student_id: str, limit: int = 200):
    return await list_student_disputes(student_id, limit)


@router.get("/disputes", summary="List disputes (admin/teacher queue)")
async def disputes_queue(
    status: str | None = None,
    course_id: str | None = None,
    teacher_id: str | None = None,
    limit: int = 200,
):
    if status and status not in {"open", "approved", "rejected"}:
        raise HTTPException(status_code=400, detail="Invalid status filter.")
    return await list_disputes(
        status=status,
        course_id=course_id,
        teacher_id=teacher_id,
        limit=limit,
    )


@router.post("/disputes/{dispute_id}/resolve", summary="Resolve dispute")
async def resolve_dispute_endpoint(dispute_id: int, req: DisputeResolveRequest):
    return await resolve_dispute(
        dispute_id=dispute_id,
        reviewer_id=req.reviewer_id,
        reviewer_role=req.reviewer_role,
        action=req.action,
        resolution_note=req.resolution_note,
    )
