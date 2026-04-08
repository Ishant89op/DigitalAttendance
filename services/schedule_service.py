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
        row = await conn.fetchrow(
            """
            SELECT ws.course_id
            FROM   weekly_schedule ws
            WHERE  ws.classroom_id = $1
              AND  ws.day_of_week  = $2
              AND  ws.start_time  <= $3::TIME
              AND  ws.end_time    >= $3::TIME
            LIMIT 1
            """,
            classroom_id,
            current_day,
            current_time,
        )

    if row:
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

    # Day order for proximity calculation (today = 0, tomorrow = 1, ...)
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
                ws.start_time::TEXT   AS start_time,
                ws.end_time::TEXT     AS end_time,
                -- Days from today (0=today, 1=tomorrow, ...)
                CASE
                    WHEN ws.day_of_week = $2 THEN 0
                    ELSE MOD(
                        (ARRAY_POSITION(
                            ARRAY['Monday','Tuesday','Wednesday','Thursday',
                                  'Friday','Saturday','Sunday'],
                            ws.day_of_week
                        ) - $3 + 7),
                        7
                    )
                END AS days_away
            FROM   weekly_schedule ws
            JOIN   courses c ON c.course_id = ws.course_id
            WHERE  ws.classroom_id = $1
            ORDER BY days_away ASC, ws.start_time ASC
            LIMIT  20
            """,
            classroom_id,
            current_day,
            today_idx + 1,   # ARRAY_POSITION is 1-indexed
        )

    results = []
    for row in rows:
        d = dict(row)
        start_str = d["start_time"][:5]   # "HH:MM"
        end_str   = d["end_time"][:5]

        # Compute minutes until start (negative = already started)
        now_mins   = now.hour * 60 + now.minute
        start_h, start_m = map(int, start_str.split(":"))
        end_h,   end_m   = map(int, end_str.split(":"))
        start_mins = start_h * 60 + start_m
        end_mins   = end_h   * 60 + end_m

        days_away = d["days_away"]
        minutes_until_start = (days_away * 1440) + start_mins - now_mins

        # Determine status
        if days_away == 0 and start_mins <= now_mins <= end_mins:
            status = "ongoing"
        elif days_away == 0 and start_mins > now_mins:
            status = "upcoming_today"
        else:
            status = "upcoming"

        # Skip past lectures from today that have already ended
        if days_away == 0 and now_mins > end_mins:
            continue

        results.append({
            "schedule_id":         d["schedule_id"],
            "course_id":           d["course_id"],
            "course_name":         d["course_name"],
            "day_of_week":         d["day_of_week"],
            "start_time":          start_str,
            "end_time":            end_str,
            "status":              status,
            "minutes_until_start": minutes_until_start,
        })

        if len(results) >= limit:
            break

    return results
