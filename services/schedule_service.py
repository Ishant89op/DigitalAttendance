"""
Schedule service — resolves which course is running / upcoming in a classroom.

Key fixes:
  - get_current_course: unchanged, still matches exact current window.
  - get_upcoming_lectures: NEW — returns next N scheduled lectures for a
    classroom ordered by time proximity. Used by classroom login page to
    show smart suggestions even when no lecture is active right now.
"""

import logging
from datetime import datetime, timezone

from core.database import get_conn

logger = logging.getLogger(__name__)


async def get_current_course(classroom_id: str) -> str | None:
    """
    Return the course_id scheduled in `classroom_id` right now.
    Returns None if no class is scheduled at this moment.
    """
    now = datetime.now(timezone.utc).astimezone()
    current_day  = now.strftime("%A")
    current_time = now.strftime("%H:%M")

    async with get_conn() as conn:
        rows = await conn.fetch(
            """
            SELECT ws.course_id, ws.start_time, ws.end_time
            FROM   weekly_schedule ws
            WHERE  ws.classroom_id = $1
              AND  ws.day_of_week  = $2
            ORDER  BY ws.start_time
            """,
            classroom_id,
            current_day,
        )

    for row in rows:
        start_str = _time_to_str(row["start_time"])
        end_str = _time_to_str(row["end_time"])
        if start_str <= current_time <= end_str:
            logger.debug("Active course in %s: %s", classroom_id, row["course_id"])
            return row["course_id"]

    logger.debug("No scheduled course in %s at %s %s",
                 classroom_id, current_day, current_time)
    return None


async def get_upcoming_lectures(classroom_id: str, limit: int = 3) -> list[dict]:
    """
    Return the next `limit` scheduled lectures for a classroom.

    Logic:
      1. First includes any CURRENTLY ONGOING lecture (start_time <= now <= end_time).
      2. Then upcoming lectures today (start_time > now), ordered by start_time ASC.
      3. If still fewer than `limit`, adds next-occurrence lectures from other days
         (ordered by proximity in the weekly cycle).

    Returns list of dicts with:
      course_id, course_name, day_of_week, start_time, end_time,
      status: 'ongoing' | 'upcoming_today' | 'upcoming',
      minutes_until_start (negative means already started)
    """
    now = datetime.now(timezone.utc).astimezone()
    current_day  = now.strftime("%A")
    current_time = now.strftime("%H:%M")

    days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
    today_idx = days.index(current_day) if current_day in days else 0

    async with get_conn() as conn:
        rows = await conn.fetch(
            """
            SELECT
                ws.schedule_id,
                ws.course_id,
                c.course_name,
                ws.day_of_week,
                ws.start_time,
                ws.end_time
            FROM   weekly_schedule ws
            JOIN   courses c ON c.course_id = ws.course_id
            WHERE  ws.classroom_id = $1
            ORDER BY ws.day_of_week, ws.start_time
            """,
            classroom_id,
        )

    annotated_rows = []
    for row in rows:
        d = dict(row)
        start_str = _time_to_str(d["start_time"])
        end_str = _time_to_str(d["end_time"])

        now_mins   = now.hour * 60 + now.minute
        start_h, start_m = map(int, start_str.split(":"))
        end_h,   end_m   = map(int, end_str.split(":"))
        start_mins = start_h * 60 + start_m
        end_mins   = end_h   * 60 + end_m

        row_day_idx = days.index(d["day_of_week"]) if d["day_of_week"] in days else today_idx
        days_away = (row_day_idx - today_idx) % 7
        minutes_until_start = (days_away * 1440) + start_mins - now_mins

        if days_away == 0 and start_mins <= now_mins <= end_mins:
            status = "ongoing"
        elif days_away == 0 and start_mins > now_mins:
            status = "upcoming_today"
        else:
            status = "upcoming"

        if days_away == 0 and now_mins > end_mins:
            continue

        annotated_rows.append({
            "schedule_id":         d["schedule_id"],
            "course_id":           d["course_id"],
            "course_name":         d["course_name"],
            "day_of_week":         d["day_of_week"],
            "start_time":          start_str,
            "end_time":            end_str,
            "status":              status,
            "minutes_until_start": minutes_until_start,
        })

    annotated_rows.sort(
        key=lambda item: (
            0 if item["status"] == "ongoing" else 1,
            item["minutes_until_start"],
            item["course_name"],
        )
    )
    return annotated_rows[:limit]


def _time_to_str(value) -> str:
    if hasattr(value, "strftime"):
        return value.strftime("%H:%M")
    return str(value)[:5]
