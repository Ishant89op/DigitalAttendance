"""
Lecture session service.

Key fix: start_lecture now accepts force=True so teacher/recognizer
can start a lecture even when nothing is in the weekly_schedule right now.
This is essential during testing and for ad-hoc lectures.
"""

import logging
from datetime import datetime, timedelta, timezone

from core.database import get_conn, transaction
from services.schedule_service import get_current_course, get_upcoming_lectures

logger = logging.getLogger(__name__)
SESSION_RESUME_WINDOW = timedelta(minutes=90)


async def start_lecture(
    classroom_id: str,
    course_id: str | None = None,
    teacher_id: str | None = None,
    force: bool = False,
) -> dict | None:
    """
    Start a lecture session for `classroom_id`.

    - If course_id is given → use it directly (no schedule lookup).
    - If course_id is None and force=False → auto-detect from weekly_schedule.
    - If course_id is None and force=True → use the nearest scheduled course
      for this classroom instead of picking an arbitrary row.

    Returns a session dict on success, None if:
      - No course found and force=False
      - A lecture is already active in this classroom
    """

    # ── resolve course_id ──
    if not course_id:
        course_id = await get_current_course(classroom_id)

    if not course_id and force:
        upcoming = await get_upcoming_lectures(classroom_id, limit=1)
        if upcoming:
            course_id = upcoming[0]["course_id"]

    if not course_id:
        logger.info(
            "No scheduled course for classroom %s right now. "
            "Pass course_id explicitly or use force=True.",
            classroom_id,
        )
        return None

    async with transaction() as conn:
        # Guard: one active lecture per classroom at a time
        existing = await conn.fetchval(
            """
            SELECT lecture_id FROM lecture_sessions
            WHERE classroom_id = $1 AND status = 'active'
            LIMIT 1
            """,
            classroom_id,
        )
        if existing:
            logger.info(
                "Lecture already active in %s (id=%d).", classroom_id, existing
            )
            return {
                "lecture_id": existing,
                "course_id": course_id,
                "status": "existing_active",
            }

        resumable = await _find_resumable_lecture(conn, classroom_id, course_id)
        if resumable:
            lecture_id = await conn.fetchval(
                """
                UPDATE lecture_sessions
                SET status = 'active',
                    end_time = NULL,
                    teacher_id = COALESCE($2, teacher_id)
                WHERE lecture_id = $1
                RETURNING lecture_id
                """,
                resumable["lecture_id"],
                teacher_id,
            )
            logger.info(
                "Lecture resumed: id=%d  course=%s  room=%s",
                lecture_id,
                course_id,
                classroom_id,
            )
            return {
                "lecture_id": lecture_id,
                "course_id": course_id,
                "status": "resumed_today",
            }

        lecture_id = await conn.fetchval(
            """
            INSERT INTO lecture_sessions
                (course_id, classroom_id, teacher_id, status, start_time)
            VALUES ($1, $2, $3, 'active', NOW())
            RETURNING lecture_id
            """,
            course_id, classroom_id, teacher_id,
        )

    logger.info(
        "Lecture started: id=%d  course=%s  room=%s", lecture_id, course_id, classroom_id
    )
    return {
        "lecture_id": lecture_id,
        "course_id": course_id,
        "status": "started_new",
    }


async def _find_resumable_lecture(conn, classroom_id: str, course_id: str) -> dict | None:
    """
    Reopen only the most recent matching lecture from today.

    Safety guard:
      - only if it ended recently
      - never if a later scheduled slot for the same course has already begun
    """
    now = datetime.now(timezone.utc).astimezone()
    current_day = now.strftime("%A")
    current_time = now.time().replace(microsecond=0)

    row = await conn.fetchrow(
        """
        SELECT lecture_id, start_time, end_time
        FROM lecture_sessions
        WHERE classroom_id = $1
          AND course_id = $2
          AND status = 'closed'
          AND start_time::DATE = CURRENT_DATE
          AND end_time IS NOT NULL
          AND end_time >= NOW() - $3::INTERVAL
        ORDER BY end_time DESC, lecture_id DESC
        LIMIT 1
        """,
        classroom_id,
        course_id,
        SESSION_RESUME_WINDOW,
    )
    if not row:
        return None

    later_slot_started = await conn.fetchval(
        """
        SELECT EXISTS (
            SELECT 1
            FROM weekly_schedule
            WHERE classroom_id = $1
              AND course_id = $2
              AND day_of_week = $3
              AND start_time > $4::TIME
              AND start_time <= $5::TIME
        )
        """,
        classroom_id,
        course_id,
        current_day,
        row["start_time"].astimezone().time().replace(microsecond=0),
        current_time,
    )
    if later_slot_started:
        return None

    return dict(row)


async def end_lecture(lecture_id: int) -> bool:
    """Close a lecture. Returns True if successfully closed."""
    async with transaction() as conn:
        result = await conn.execute(
            """
            UPDATE lecture_sessions
            SET    status = 'closed', end_time = NOW()
            WHERE  lecture_id = $1 AND status = 'active'
            """,
            lecture_id,
        )
    updated = result.split()[-1] != "0"
    if updated:
        logger.info("Lecture %d closed.", lecture_id)
    return updated


async def get_active_lecture(classroom_id: str) -> int | None:
    """Return lecture_id of the active session in this classroom, or None."""
    async with get_conn() as conn:
        row = await conn.fetchrow(
            """
            SELECT lecture_id FROM lecture_sessions
            WHERE  classroom_id = $1 AND status = 'active'
            ORDER  BY lecture_id DESC
            LIMIT  1
            """,
            classroom_id,
        )
    return row["lecture_id"] if row else None


async def get_lecture_detail(lecture_id: int) -> dict | None:
    """Full detail for a lecture including attendance count."""
    async with get_conn() as conn:
        row = await conn.fetchrow(
            """
            SELECT ls.lecture_id,
                   ls.course_id,
                   c.course_name,
                   ls.classroom_id,
                   ls.teacher_id,
                   ls.status,
                   ls.start_time,
                   ls.end_time,
                   COUNT(a.id) AS attendance_count
            FROM   lecture_sessions ls
            JOIN   courses c ON c.course_id = ls.course_id
            LEFT   JOIN attendance a ON a.lecture_id = ls.lecture_id
            WHERE  ls.lecture_id = $1
            GROUP  BY ls.lecture_id, c.course_name
            """,
            lecture_id,
        )
    return dict(row) if row else None
