"""
Attendance manager — all attendance write operations live here.

Responsibilities:
  - Mark attendance (face recognition path)
  - Manual override (teacher path)
  - Both paths write to the audit_log
  - Duplicate marks are silently ignored (UNIQUE constraint is the guard)
"""

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
            await conn.execute(
                """
                INSERT INTO audit_log (event_type, actor_id, target_id, detail)
                VALUES ('attendance_marked', $1, $2,
                        jsonb_build_object(
                            'lecture_id', $3::TEXT,
                            'source', $4,
                            'ts', $5::TEXT
                        ))
                """,
                marked_by or "system",
                student_id,
                lecture_id,
                source,
                datetime.now(timezone.utc).isoformat(),
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
            action = "marked_present"
        else:
            await conn.execute(
                """
                DELETE FROM attendance
                WHERE student_id = $1 AND lecture_id = $2
                """,
                student_id, lecture_id,
            )
            action = "marked_absent"

        await conn.execute(
            """
            INSERT INTO audit_log (event_type, actor_id, target_id, detail)
            VALUES ('manual_override', $1, $2,
                    jsonb_build_object(
                        'lecture_id', $3::TEXT,
                        'action', $4
                    ))
            """,
            teacher_id, student_id, lecture_id, action,
        )

    logger.info("Manual override  teacher=%s  student=%s  lecture=%d  action=%s",
                teacher_id, student_id, lecture_id, action)
    return {"student_id": student_id, "lecture_id": lecture_id, "action": action}
