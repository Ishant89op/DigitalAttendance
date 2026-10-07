"""
Attendance manager — all attendance write operations live here.

Responsibilities:
  - Mark attendance (face recognition path)
  - Manual override (teacher path)
  - Both paths write to the audit_log
  - Integrity rules enforced in SQL, not just in callers:
      * a student can only be marked for a lecture of a course they are
        enrolled in (same department + semester)
      * the camera path can only mark ACTIVE lectures
  - Duplicate marks are silently ignored (UNIQUE constraint is the guard)
"""

import json
import logging
from datetime import datetime, timezone

from fastapi import HTTPException

from core.database import transaction

logger = logging.getLogger(__name__)

_ENROLLED_SQL = """
    SELECT 1
    FROM lecture_sessions ls
    JOIN courses  c ON c.course_id = ls.course_id
    JOIN students s ON s.department = c.department AND s.semester = c.semester
    WHERE ls.lecture_id = $2 AND s.student_id = $1
"""


async def mark_attendance(
    student_id: str,
    lecture_id: int,
    source: str = "face_recognition",
    marked_by: str | None = None,
) -> bool:
    """
    Record one attendance entry.

    Returns True if a new record was inserted, False if already present or the
    student/lecture combination is not eligible.
    """
    active_only = "AND ls.status = 'active'" if source == "face_recognition" else ""
    async with transaction() as conn:
        inserted = await conn.fetchval(
            f"""
            INSERT INTO attendance (student_id, lecture_id, source, marked_by)
            SELECT $1, $2, $3, $4
            WHERE EXISTS ({_ENROLLED_SQL} {active_only})
            ON CONFLICT (student_id, lecture_id) DO NOTHING
            RETURNING id
            """,
            student_id, lecture_id, source, marked_by,
        )
        if inserted is None:
            return False

        await conn.execute(
            """
            INSERT INTO audit_log (event_type, actor_id, target_id, detail)
            VALUES ('attendance_marked', $1, $2, $3::JSONB)
            """,
            marked_by or "system",
            student_id,
            json.dumps({
                "lecture_id": int(lecture_id),
                "source": source,
                "ts": datetime.now(timezone.utc).isoformat(),
            }),
        )

    logger.info("Attendance marked  student=%s  lecture=%d  via=%s", student_id, lecture_id, source)
    return True


async def manual_override(
    student_id: str,
    lecture_id: int,
    teacher_id: str,
    present: bool,
) -> dict:
    """
    Teacher manually sets attendance status.

    - present=True  -> INSERT or do nothing (already marked present)
    - present=False -> DELETE the attendance record if it exists
    """
    action = "marked_present" if present else "marked_absent"
    async with transaction() as conn:
        enrolled = await conn.fetchval(_ENROLLED_SQL, student_id, lecture_id)
        if not enrolled:
            raise HTTPException(status_code=400, detail="Student is not enrolled in this lecture's course.")

        if present:
            result = await conn.execute(
                """
                INSERT INTO attendance (student_id, lecture_id, source, marked_by)
                VALUES ($1, $2, 'manual_override', $3)
                ON CONFLICT (student_id, lecture_id) DO NOTHING
                """,
                student_id, lecture_id, teacher_id,
            )
        else:
            result = await conn.execute(
                "DELETE FROM attendance WHERE student_id = $1 AND lecture_id = $2",
                student_id, lecture_id,
            )
        changed = not result.endswith(" 0")

        await conn.execute(
            """
            INSERT INTO audit_log (event_type, actor_id, target_id, detail)
            VALUES ('manual_override', $1, $2, $3::JSONB)
            """,
            teacher_id,
            student_id,
            json.dumps({
                "lecture_id": int(lecture_id),
                "action": action,
                "changed": changed,
                "ts": datetime.now(timezone.utc).isoformat(),
            }),
        )

    logger.info("Manual override  by=%s  student=%s  lecture=%d  action=%s",
                teacher_id, student_id, lecture_id, action)
    return {"student_id": student_id, "lecture_id": lecture_id, "action": action, "changed": changed}
