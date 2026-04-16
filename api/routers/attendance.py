"""Attendance endpoints."""

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, HTTPException, UploadFile, File
from fastapi.responses import FileResponse
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

EVIDENCE_DIR = Path(__file__).resolve().parents[2] / "uploads" / "disputes"
EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
MAX_EVIDENCE_BYTES = 5 * 1024 * 1024


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


@router.post("/disputes/evidence", summary="Upload dispute evidence PDF")
async def upload_dispute_evidence(student_id: str, file: UploadFile = File(...)):
    student_id = student_id.strip()
    if not student_id:
        raise HTTPException(status_code=400, detail="Student ID is required.")

    async with get_conn() as conn:
        exists = await conn.fetchval(
            "SELECT 1 FROM students WHERE student_id = $1 LIMIT 1",
            student_id,
        )
    if not exists:
        raise HTTPException(status_code=404, detail="Student not found.")

    original_name = (file.filename or "").strip()
    if not original_name.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are allowed.")

    content = await file.read(MAX_EVIDENCE_BYTES + 1)
    await file.close()

    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    if len(content) > MAX_EVIDENCE_BYTES:
        raise HTTPException(status_code=400, detail="PDF exceeds 5 MB size limit.")
    if not content.startswith(b"%PDF"):
        raise HTTPException(status_code=400, detail="Uploaded file is not a valid PDF.")

    file_name = f"{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{uuid4().hex}.pdf"
    target = EVIDENCE_DIR / file_name
    target.write_bytes(content)

    return {
        "student_id": student_id,
        "original_name": original_name,
        "file_name": file_name,
        "size_bytes": len(content),
        "evidence_url": f"/attendance/disputes/evidence/{file_name}",
    }


@router.get("/disputes/evidence/{file_name}", summary="Download dispute evidence PDF")
async def get_dispute_evidence(file_name: str):
    safe_name = Path(file_name).name
    if safe_name != file_name or not safe_name.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Invalid evidence file name.")

    target = EVIDENCE_DIR / safe_name
    if not target.exists():
        raise HTTPException(status_code=404, detail="Evidence file not found.")

    return FileResponse(target, media_type="application/pdf", filename=safe_name)


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
