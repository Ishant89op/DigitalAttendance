"""Attendance dispute workflow service."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import HTTPException

from attendance.attendance_manager import mark_attendance
from core.database import get_conn, transaction


async def create_dispute(
    student_id: str,
    course_id: str | None,
    lecture_id: int | None,
    reason: str,
    evidence: str | None = None,
) -> dict:
    if not reason.strip():
        raise HTTPException(status_code=400, detail="Reason is required.")

    async with transaction() as conn:
        exists = await conn.fetchval(
            "SELECT 1 FROM students WHERE student_id = $1 LIMIT 1",
            student_id,
        )
        if not exists:
            raise HTTPException(status_code=404, detail="Student not found.")

        if lecture_id is not None:
            lecture = await conn.fetchrow(
                "SELECT lecture_id, course_id FROM lecture_sessions WHERE lecture_id = $1",
                lecture_id,
            )
            if not lecture:
                raise HTTPException(status_code=404, detail="Lecture not found.")
            if course_id and lecture["course_id"] != course_id:
                raise HTTPException(status_code=400, detail="Course and lecture mismatch.")
            if not course_id:
                course_id = lecture["course_id"]

        dispute_id = await conn.fetchval(
            """
            INSERT INTO attendance_disputes
                (student_id, course_id, lecture_id, reason, evidence, status)
            VALUES ($1, $2, $3, $4, $5, 'open')
            RETURNING dispute_id
            """,
            student_id,
            course_id,
            lecture_id,
            reason.strip(),
            evidence.strip() if evidence else None,
        )

        await conn.execute(
            """
            INSERT INTO audit_log (event_type, actor_id, target_id, detail)
            VALUES ('dispute_created', $1, $2, $3::JSONB)
            """,
            student_id,
            str(dispute_id),
            json.dumps(
                {
                    "student_id": student_id,
                    "course_id": course_id,
                    "lecture_id": lecture_id,
                    "reason": reason.strip(),
                    "ts": datetime.now(timezone.utc).isoformat(),
                }
            ),
        )

    return {
        "dispute_id": dispute_id,
        "student_id": student_id,
        "course_id": course_id,
        "lecture_id": lecture_id,
        "status": "open",
    }


async def list_student_disputes(student_id: str, limit: int = 200) -> list[dict]:
    async with get_conn() as conn:
        rows = await conn.fetch(
            """
            SELECT
                d.dispute_id,
                d.student_id,
                d.course_id,
                c.course_name,
                d.lecture_id,
                d.reason,
                d.evidence,
                d.status,
                d.reviewer_id,
                d.reviewer_role,
                d.resolution_note,
                d.created_at,
                d.reviewed_at
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
            """
            SELECT
                d.dispute_id,
                d.student_id,
                s.name AS student_name,
                d.course_id,
                c.course_name,
                d.lecture_id,
                d.reason,
                d.evidence,
                d.status,
                d.reviewer_id,
                d.reviewer_role,
                d.resolution_note,
                d.created_at,
                d.reviewed_at
            FROM attendance_disputes d
            JOIN students s ON s.student_id = d.student_id
            LEFT JOIN courses c ON c.course_id = d.course_id
            WHERE ($1::TEXT IS NULL OR d.status = $1)
              AND ($2::TEXT IS NULL OR d.course_id = $2)
              AND (
                    $3::TEXT IS NULL
                    OR EXISTS (
                        SELECT 1
                        FROM course_teachers ct
                        WHERE ct.course_id = d.course_id
                          AND ct.teacher_id = $3
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
    action = action.strip().lower()
    reviewer_role = reviewer_role.strip().lower()

    if action not in {"approved", "rejected"}:
        raise HTTPException(status_code=400, detail="Action must be approved or rejected.")
    if reviewer_role not in {"teacher", "admin"}:
        raise HTTPException(status_code=400, detail="Reviewer role must be teacher or admin.")

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
        if dispute["status"] != "open":
            raise HTTPException(status_code=409, detail="Dispute is already resolved.")

        if reviewer_role == "teacher":
            can_review = await conn.fetchval(
                """
                SELECT 1
                FROM course_teachers
                WHERE teacher_id = $1
                  AND course_id = $2
                LIMIT 1
                """,
                reviewer_id,
                dispute["course_id"],
            )
            if not can_review:
                raise HTTPException(status_code=403, detail="Teacher is not assigned to this course.")

        if action == "approved" and dispute["lecture_id"] is not None:
            await mark_attendance(
                dispute["student_id"],
                int(dispute["lecture_id"]),
                source="manual_override",
                marked_by=reviewer_id,
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
            json.dumps(
                {
                    "action": action,
                    "reviewer_role": reviewer_role,
                    "lecture_id": dispute["lecture_id"],
                    "student_id": dispute["student_id"],
                    "ts": datetime.now(timezone.utc).isoformat(),
                }
            ),
        )

    return {
        "dispute_id": dispute_id,
        "status": action,
        "reviewer_id": reviewer_id,
        "reviewer_role": reviewer_role,
    }
