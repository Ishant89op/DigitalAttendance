"""
Generate realistic past attendance for demos and presentations.

    python scripts/demo_history.py --weeks 5

For every weekly_schedule slot over the past N weeks it creates a closed
lecture and marks each enrolled student present with a per-student
probability (some students are deliberately "at risk"). Safe to re-run:
weeks that already have a lecture for a slot are skipped.

Demo data only — do not run against a production database.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import random
import sys
from datetime import date, datetime, time, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.database import close_pool, get_conn, init_pool  # noqa: E402

DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


async def main(weeks: int, seed: int) -> None:
    rng = random.Random(seed)
    await init_pool()
    try:
        async with get_conn() as conn:
            slots = await conn.fetch(
                """
                SELECT ws.course_id, ws.classroom_id, ws.day_of_week, ws.start_time, ws.end_time,
                       c.department, c.semester,
                       (SELECT teacher_id FROM course_teachers ct WHERE ct.course_id = ws.course_id
                        ORDER BY teacher_id LIMIT 1) AS teacher_id
                FROM weekly_schedule ws JOIN courses c ON c.course_id = ws.course_id
                """
            )
            students = await conn.fetch("SELECT student_id, department, semester FROM students")
            # Stable per-student attendance habit between 55% and 97%.
            habit = {s["student_id"]: rng.uniform(0.55, 0.97) for s in students}

            today = date.today()
            tz = datetime.now().astimezone().tzinfo
            made = marks = 0
            for week in range(weeks, 0, -1):
                monday = today - timedelta(days=today.weekday()) - timedelta(weeks=week)
                for slot in slots:
                    day = monday + timedelta(days=DAYS.index(slot["day_of_week"]))
                    start = datetime.combine(day, slot["start_time"], tz)
                    end = datetime.combine(day, slot["end_time"], tz)
                    exists = await conn.fetchval(
                        "SELECT 1 FROM lecture_sessions WHERE course_id=$1 AND classroom_id=$2 AND start_time=$3",
                        slot["course_id"], slot["classroom_id"], start,
                    )
                    if exists:
                        continue
                    lecture_id = await conn.fetchval(
                        """
                        INSERT INTO lecture_sessions (course_id, classroom_id, teacher_id, status, start_time, end_time)
                        VALUES ($1, $2, $3, 'closed', $4, $5) RETURNING lecture_id
                        """,
                        slot["course_id"], slot["classroom_id"], slot["teacher_id"], start, end,
                    )
                    made += 1
                    for s in students:
                        if (s["department"], s["semester"]) != (slot["department"], slot["semester"]):
                            continue
                        if rng.random() < habit[s["student_id"]]:
                            marked_at = start + timedelta(minutes=rng.randint(0, 12), seconds=rng.randint(0, 59))
                            await conn.execute(
                                """
                                INSERT INTO attendance (lecture_id, student_id, timestamp, source)
                                VALUES ($1, $2, $3, $4) ON CONFLICT DO NOTHING
                                """,
                                lecture_id, s["student_id"], marked_at,
                                "face_recognition" if rng.random() < 0.93 else "manual_override",
                            )
                            marks += 1
        print(f"Created {made} past lectures and {marks} attendance marks.")
    finally:
        await close_pool()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--weeks", type=int, default=5)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()
    asyncio.run(main(max(1, min(args.weeks, 20)), args.seed))
