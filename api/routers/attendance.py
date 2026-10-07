"""Attendance, manual override and dispute endpoints."""

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path as FsPath
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, Path, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from attendance.attendance_manager import manual_override, mark_attendance
from config.settings import security as security_cfg, uploads as upload_cfg
from core.auth import (
    Principal,
    assert_lecture_access,
    assert_self,
    audit,
    forbid,
    require,
    teaches,
)
from core.database import get_conn
from core.security import ID_PATTERN
from utils.pdf_guard import is_safe_pdf
from services.dispute_service import (
    create_dispute,
    list_disputes,
    list_student_disputes,
    resolve_dispute,
)

router = APIRouter(prefix="/attendance", tags=["Attendance"])

# Uploads live under instance/ (git-ignored, outside the web root). The old
# uploads/disputes folder is still read so earlier evidence keeps working.
EVIDENCE_DIR = FsPath(security_cfg.instance_dir) / "uploads" / "disputes"
EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
LEGACY_EVIDENCE_DIR = FsPath(__file__).resolve().parents[2] / "uploads" / "disputes"
EVIDENCE_NAME_RE = re.compile(r"^\d{14}_[0-9a-f]{32}\.pdf$")

class MarkRequest(BaseModel):
    student_id: str = Field(pattern=ID_PATTERN)
    lecture_id: int = Field(ge=1)


class OverrideRequest(BaseModel):
    student_id: str = Field(pattern=ID_PATTERN)
    lecture_id: int = Field(ge=1)
    present:    bool


class DisputeCreateRequest(BaseModel):
    course_id: str | None = Field(default=None, pattern=ID_PATTERN)
    lecture_id: int | None = Field(default=None, ge=1)
    reason: str = Field(min_length=3, max_length=1000)
    evidence: str | None = Field(default=None, max_length=2000)
    evidence_file: str | None = Field(default=None, max_length=64)


class DisputeResolveRequest(BaseModel):
    action: Literal["approved", "rejected"]
    resolution_note: str | None = Field(default=None, max_length=1000)


@router.post("/mark", summary="Mark attendance (admin tooling; the camera writes directly)")
async def mark(req: MarkRequest, request: Request, principal: Principal = Depends(require("admin"))):
    inserted = await mark_attendance(req.student_id, req.lecture_id, source="manual_override",
                                     marked_by=principal.user_id)
    return {"student_id": req.student_id, "lecture_id": req.lecture_id, "new_record": inserted}


@router.post("/override", summary="Teacher manual attendance override")
async def override(
    req: OverrideRequest,
    request: Request,
    principal: Principal = Depends(require("teacher", "admin")),
):
    await assert_lecture_access(principal, req.lecture_id)
    return await manual_override(req.student_id, req.lecture_id, principal.user_id, req.present)


@router.get("/count/{lecture_id}", summary="Count present students for a lecture")
async def count(lecture_id: int, principal: Principal = Depends(require("classroom", "teacher", "admin"))):
    await assert_lecture_access(principal, lecture_id)
    async with get_conn() as conn:
        n = await conn.fetchval("SELECT COUNT(*) FROM attendance WHERE lecture_id = $1", lecture_id)
    return {"lecture_id": lecture_id, "count": n}


@router.get("/list/{lecture_id}", summary="List present students for a lecture")
async def list_attendance(lecture_id: int, principal: Principal = Depends(require("classroom", "teacher", "admin"))):
    await assert_lecture_access(principal, lecture_id)
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


# ─────────────────────────────────────────────
# DISPUTE EVIDENCE
# ─────────────────────────────────────────────

@router.post("/disputes/evidence", summary="Upload dispute evidence PDF (student)")
async def upload_dispute_evidence(
    request: Request,
    file: UploadFile = File(...),
    principal: Principal = Depends(require("student")),
):
    original_name = (file.filename or "").strip()[:120]
    if not original_name.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are allowed.")

    content = await file.read(upload_cfg.max_evidence_bytes + 1)
    await file.close()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    if len(content) > upload_cfg.max_evidence_bytes:
        raise HTTPException(status_code=413, detail="PDF exceeds the 5 MB limit.")
    if not is_safe_pdf(content):
        await audit("evidence_rejected", principal.user_id, None, {"reason": "unsafe_pdf"}, request)
        raise HTTPException(
            status_code=400,
            detail="This PDF is invalid or contains scripts/attachments. Export it again as a plain PDF.",
        )

    file_name = f"{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{uuid4().hex}.pdf"
    (EVIDENCE_DIR / file_name).write_bytes(content)
    async with get_conn() as conn:
        await conn.execute(
            """
            INSERT INTO evidence_files (file_name, student_id, sha256, size_bytes, original_name)
            VALUES ($1, $2, $3, $4, $5)
            """,
            file_name, principal.user_id, hashlib.sha256(content).hexdigest(), len(content), original_name,
        )
    await audit("evidence_uploaded", principal.user_id, file_name, {"size": len(content)}, request)
    return {
        "file_name": file_name,
        "original_name": original_name,
        "size_bytes": len(content),
        "evidence_url": f"/attendance/disputes/evidence/{file_name}",
    }


async def _may_read_evidence(principal: Principal, file_name: str) -> bool:
    async with get_conn() as conn:
        owner = await conn.fetchval("SELECT student_id FROM evidence_files WHERE file_name = $1", file_name)
        if owner is None:
            return False
        if principal.is_admin:
            return True
        if principal.role == "student":
            return owner == principal.user_id
        if principal.role == "teacher":
            return bool(await conn.fetchval(
                """
                SELECT 1
                FROM attendance_disputes d
                JOIN course_teachers ct ON ct.course_id = d.course_id
                WHERE ct.teacher_id = $1
                  AND (d.evidence_file = $2 OR d.evidence LIKE '%' || $2 || '%')
                LIMIT 1
                """,
                principal.user_id, file_name,
            ))
    return False


@router.get("/disputes/evidence/{file_name}", summary="Download dispute evidence PDF")
async def get_dispute_evidence(
    file_name: str = Path(max_length=64),
    principal: Principal = Depends(require("student", "teacher", "admin")),
):
    if not EVIDENCE_NAME_RE.match(file_name):
        raise HTTPException(status_code=404, detail="Evidence file not found.")
    if not await _may_read_evidence(principal, file_name):
        raise HTTPException(status_code=404, detail="Evidence file not found.")
    target = EVIDENCE_DIR / file_name
    if not target.is_file():
        target = LEGACY_EVIDENCE_DIR / file_name
    if not target.is_file():
        raise HTTPException(status_code=404, detail="Evidence file not found.")
    return FileResponse(
        target,
        media_type="application/pdf",
        filename=file_name,
        content_disposition_type="inline",
        headers={
            # Even if a viewer would run PDF scripts, nothing may run here.
            "Content-Security-Policy": "sandbox; default-src 'none'",
            "Cache-Control": "private, no-store",
        },
    )


# ─────────────────────────────────────────────
# DISPUTES
# ─────────────────────────────────────────────

@router.post("/disputes", summary="Raise an attendance dispute (student)")
async def create_dispute_endpoint(
    req: DisputeCreateRequest,
    request: Request,
    principal: Principal = Depends(require("student")),
):
    if req.evidence_file:
        if not EVIDENCE_NAME_RE.match(req.evidence_file):
            raise HTTPException(status_code=400, detail="Invalid evidence reference.")
        async with get_conn() as conn:
            owner = await conn.fetchval(
                "SELECT student_id FROM evidence_files WHERE file_name = $1", req.evidence_file,
            )
        if owner != principal.user_id:
            raise HTTPException(status_code=400, detail="Invalid evidence reference.")

    result = await create_dispute(
        student_id=principal.user_id,
        course_id=req.course_id,
        lecture_id=req.lecture_id,
        reason=req.reason,
        evidence=req.evidence,
        evidence_file=req.evidence_file,
    )
    return result


@router.get("/disputes/student/{student_id}", summary="Disputes raised by a student")
async def student_disputes(
    student_id: str = Path(pattern=ID_PATTERN),
    limit: int = 200,
    principal: Principal = Depends(require("student", "admin")),
):
    assert_self(principal, student_id)
    return await list_student_disputes(student_id, max(1, min(limit, 500)))


@router.get("/disputes", summary="Dispute queue (teacher: own courses only)")
async def disputes_queue(
    status: Literal["open", "approved", "rejected"] | None = None,
    course_id: str | None = None,
    limit: int = 200,
    principal: Principal = Depends(require("teacher", "admin")),
):
    if course_id is not None and not re.match(ID_PATTERN, course_id):
        raise HTTPException(status_code=400, detail="Invalid course_id.")
    teacher_id = None
    if principal.role == "teacher":
        teacher_id = principal.user_id
        if course_id and not await teaches(principal.user_id, course_id):
            raise forbid()
    return await list_disputes(
        status=status,
        course_id=course_id,
        teacher_id=teacher_id,
        limit=max(1, min(limit, 500)),
    )


@router.post("/disputes/{dispute_id}/resolve", summary="Approve or reject a dispute")
async def resolve_dispute_endpoint(
    dispute_id: int,
    req: DisputeResolveRequest,
    request: Request,
    principal: Principal = Depends(require("teacher", "admin")),
):
    return await resolve_dispute(
        dispute_id=dispute_id,
        reviewer_id=principal.user_id,
        reviewer_role=principal.role,
        action=req.action,
        resolution_note=req.resolution_note,
    )
