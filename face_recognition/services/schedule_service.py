from datetime import datetime
from database.database import get_connection


def get_current_course(classroom_id):

    conn = get_connection()
    cur = conn.cursor()

    # current day and time
    now = datetime.now()
    current_day = now.strftime("%A")  # Monday, Tuesday
    current_time = now.strftime("%H:%M")

    cur.execute("""
        SELECT course_id
        FROM weekly_schedule
        WHERE classroom_id=?
        AND day_of_week=?
        AND start_time <= ?
        AND end_time >= ?
    """, (
        classroom_id,
        current_day,
        current_time,
        current_time
    ))

    row = cur.fetchone()
    conn.close()

    return row[0] if row else None