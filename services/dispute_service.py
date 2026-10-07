"""Attendance dispute workflow service."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import HTTPException

from core.database import get_conn, transaction

_MAX_OPEN_DISPUTES_PER_STUDENT = 20


async def create_dispute(
    student_id: str,
    course_id: str | None,
    lecture_id: int | None,
    reason: str,
    evidence: str | None = None,
    evidence_file: str | None = None,
) -> dict:
    reason = reason.strip()
    if not reason:
        raise HTTPException(status_code=400, detail="Reason is required.")
    if not course_id and lecture_id is None:
        raise HTTPException(status_code=400, detail="Choose a course or a lecture.")

    async with transaction() as conn:
        student = await conn.fetchrow(
            "SELECT department, semester FROM students WHERE student_id = $1", student_id,
        )
        if not student:
            raise HTTPException(status_code=404, detail="Student not found.")

        if lecture_id is not None:
            lecture = await conn.fetchrow(
                "SELECT course_id, status FROM lecture_sessions WHERE lecture_id = $1", lecture_id,
            )
            if not lecture:
                raise HTTPException(status_code=404, detail="Lecture not found.")
            if course_id and lecture["course_id"] != course_id:
                raise HTTPException(status_code=400, detail="Course and lecture do not match.")
            course_id = lecture["course_id"]

        # Students can only dispute courses they are enrolled in.
        enrolled = await conn.fetchval(
            "SELECT 1 FROM courses WHERE course_id = $1 AND department = $2 AND semester = $3",
            course_id, student["department"], student["semester"],
        )
        if not enrolled:
            raise HTTPException(status_code=400, detail="You are not enrolled in this course.")

        if lecture_id is not None:
            duplicate = await conn.fetchval(
                """
                SELECT 1 FROM attendance_disputes
                WHERE student_id = $1 AND lecture_id = $2 AND status = 'open'
                """,
                student_id, lecture_id,
            )
            if duplicate:
                raise HTTPException(status_code=409, detail="You already have an open dispute for this lecture.")

        open_count = await conn.fetchval(
            "SELECT COUNT(*) FROM attendance_disputes WHERE student_id = $1 AND status = 'open'",
            student_id,
        )
        if open_count >= _MAX_OPEN_DISPUTES_PER_STUDENT:
            raise HTTPException(status_code=429, detail="Too many open disputes. Wait for a review first.")

        dispute_id = await conn.fetchval(
            """
            INSERT INTO attendance_disputes
                (student_id, course_id, lecture_id, reason, evidence, evidence_file, status)
            VALUES ($1, $2, $3, $4, $5, $6, 'open')
            RETURNING dispute_id
            """,
            student_id,
            course_id,
            lecture_id,
            reason,
            evidence.strip() if evidence else None,
            evidence_file,
        )

        await conn.execute(
            """
            INSERT INTO audit_log (event_type, actor_id, target_id, detail)
            VALUES ('dispute_created', $1, $2, $3::JSONB)
            """,
            student_id,
            str(dispute_id),
            json.dumps({
                "course_id": course_id,
                "lecture_id": lecture_id,
                "has_evidence_file": bool(evidence_file),
                "ts": datetime.now(timezone.utc).isoformat(),
            }),
        )

    return {
        "dispute_id": dispute_id,
        "student_id": student_id,
        "course_id": course_id,
        "lecture_id": lecture_id,
        "status": "open",
    }


_DISPUTE_COLUMNS = """
    d.dispute_id,
    d.student_id,
    d.course_id,
    c.course_name,
    d.lecture_id,
    d.reason,
    d.evidence,
    d.evidence_file,
    d.status,
    d.reviewer_id,
    d.reviewer_role,
    d.resolution_note,
    d.created_at,
    d.reviewed_at
"""


async def list_student_disputes(student_id: str, limit: int = 200) -> list[dict]:
    async with get_conn() as conn:
        rows = await conn.fetch(
            f"""
            SELECT {_DISPUTE_COLUMNS}
            FROM attendance_disputes d
            LEFT JOIN courses c ON c.course_id = d.course_id
            WHERE d.student_id = $1
            ORDER BY d.created_at DESC, d.dispute_id DESC
            LIMIT $2
            """,
            student_id,
            limit,
        )
    return [dict(r) for r in rows]


async def list_disputes(
    *,
    status: str | None = None,
    course_id: str | None = None,
    teacher_id: str | None = None,
    limit: int = 200,
) -> list[dict]:
    async with get_conn() as conn:
        rows = await conn.fetch(
            f"""
            SELECT {_DISPUTE_COLUMNS}, s.name AS student_name
            FROM attendance_disputes d
            JOIN students s ON s.student_id = d.student_id
            LEFT JOIN courses c ON c.course_id = d.course_id
            WHERE ($1::TEXT IS NULL OR d.status = $1)
              AND ($2::TEXT IS NULL OR d.course_id = $2)
              AND (
                    $3::TEXT IS NULL
                    OR EXISTS (
                        SELECT 1 FROM course_teachers ct
                        WHERE ct.course_id = d.course_id AND ct.teacher_id = $3
                    )
              )
            ORDER BY d.created_at DESC, d.dispute_id DESC
            LIMIT $4
            """,
            status,
            course_id,
            teacher_id,
            limit,
        )
    return [dict(r) for r in rows]


async def resolve_dispute(
    dispute_id: int,
    reviewer_id: str,
    reviewer_role: str,
    action: str,
    resolution_note: str | None = None,
) -> dict:
    if action not in {"approved", "rejected"}:
        raise HTTPException(status_code=400, detail="Action must be approved or rejected.")
    if reviewer_role not in {"teacher", "admin"}:
        raise HTTPException(status_code=403, detail="Only teachers or admins can review disputes.")

    async with transaction() as conn:
        dispute = await conn.fetchrow(
            """
            SELECT dispute_id, student_id, course_id, lecture_id, status
            FROM attendance_disputes
            WHERE dispute_id = $1
            FOR UPDATE
            """,
            dispute_id,
        )
        if not dispute:
            raise HTTPException(status_code=404, detail="Dispute not found.")

        if reviewer_role == "teacher":
            can_review = await conn.fetchval(
                "SELECT 1 FROM course_teachers WHERE teacher_id = $1 AND course_id = $2",
                reviewer_id, dispute["course_id"],
            )
            if not can_review:
                # Do not reveal whether the dispute exists to non-owners.
                raise HTTPException(status_code=404, detail="Dispute not found.")

        if dispute["status"] != "open":
            raise HTTPException(status_code=409, detail="Dispute is already resolved.")

        if action == "approved" and dispute["lecture_id"] is not None:
            # Same transaction as the status change: either both happen or neither.
            await conn.execute(
                """
                INSERT INTO attendance (student_id, lecture_id, source, marked_by)
                VALUES ($1, $2, 'manual_override', $3)
                ON CONFLICT (student_id, lecture_id) DO NOTHING
                """,
                dispute["student_id"], int(dispute["lecture_id"]), reviewer_id,
            )

        await conn.execute(
            """
            UPDATE attendance_disputes
            SET status = $2,
                reviewer_id = $3,
                reviewer_role = $4,
                resolution_note = $5,
                reviewed_at = NOW()
            WHERE dispute_id = $1
            """,
            dispute_id,
            action,
            reviewer_id,
            reviewer_role,
            resolution_note.strip() if resolution_note else None,
        )

        await conn.execute(
            """
            INSERT INTO audit_log (event_type, actor_id, target_id, detail)
            VALUES ('dispute_resolved', $1, $2, $3::JSONB)
            """,
            reviewer_id,
            str(dispute_id),
            json.dumps({
                "action": action,
                "reviewer_role": reviewer_role,
                "lecture_id": dispute["lecture_id"],
                "student_id": dispute["student_id"],
                "ts": datetime.now(timezone.utc).isoformat(),
            }),
        )

    return {
        "dispute_id": dispute_id,
        "status": action,
        "reviewer_id": reviewer_id,
        "reviewer_role": reviewer_role,
    }
