"""
Attendance manager — all attendance write operations live here.

Responsibilities:
  - Mark attendance (face recognition path)
  - Manual override (teacher path)
  - Both paths write to the audit_log
  - Duplicate marks are silently ignored (UNIQUE constraint is the guard)
"""

import json
import logging
from datetime import datetime, timezone

from asyncpg import UniqueViolationError

from core.database import transaction

logger = logging.getLogger(__name__)


async def mark_attendance(
    student_id: str,
    lecture_id: int,
    source: str = "face_recognition",
    marked_by: str | None = None,
) -> bool:
    """
    Record one attendance entry.

    Returns True if a new record was inserted, False if already present.
    Never raises on duplicate — the UNIQUE constraint handles idempotency.
    """
    try:
        async with transaction() as conn:
            await conn.execute(
                """
                INSERT INTO attendance (student_id, lecture_id, source, marked_by)
                VALUES ($1, $2, $3, $4)
                """,
                student_id, lecture_id, source, marked_by,
            )

            # Audit trail
            detail = json.dumps({
                "lecture_id": int(lecture_id),
                "source": source,
                "ts": datetime.now(timezone.utc).isoformat(),
            })
            await conn.execute(
                """
                INSERT INTO audit_log (event_type, actor_id, target_id, detail)
                VALUES ('attendance_marked', $1, $2, $3::JSONB)
                """,
                marked_by or "system",
                student_id,
                detail,
            )

        logger.info("✔ Attendance marked  student=%s  lecture=%d  via=%s",
                    student_id, lecture_id, source)
        return True

    except UniqueViolationError:
        # Already marked — not an error
        return False

    except Exception as exc:
        logger.error("Failed to mark attendance for %s: %s", student_id, exc)
        raise


async def manual_override(
    student_id: str,
    lecture_id: int,
    teacher_id: str,
    present: bool,
) -> dict:
    """
    Teacher manually sets attendance status.

    - present=True  → INSERT or do nothing (already marked present)
    - present=False → DELETE the attendance record if it exists
    """
    action = "marked_present" if present else "marked_absent"
    detail = json.dumps({
        "lecture_id": int(lecture_id),
        "action": action,
    })
    async with transaction() as conn:
        if present:
            await conn.execute(
                """
                INSERT INTO attendance (student_id, lecture_id, source, marked_by)
                VALUES ($1, $2, 'manual_override', $3)
                ON CONFLICT (student_id, lecture_id) DO NOTHING
                """,
                student_id, lecture_id, teacher_id,
            )
        else:
            await conn.execute(
                """
                DELETE FROM attendance
                WHERE student_id = $1 AND lecture_id = $2
                """,
                student_id, lecture_id,
            )

        await conn.execute(
            """
            INSERT INTO audit_log (event_type, actor_id, target_id, detail)
            VALUES ('manual_override', $1, $2, $3::JSONB)
            """,
            teacher_id, student_id, detail,
        )

    logger.info("Manual override  teacher=%s  student=%s  lecture=%d  action=%s",
                teacher_id, student_id, lecture_id, action)
    return {"student_id": student_id, "lecture_id": lecture_id, "action": action}
