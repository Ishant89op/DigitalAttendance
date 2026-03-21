from database.database import get_connection
from services.schedule_service import get_current_course


def start_lecture(classroom_id):

    course_id = get_current_course(classroom_id)

    if not course_id:
        return None

    conn = get_connection()
    cur = conn.cursor()

    # check if already active
    cur.execute("""
        SELECT lecture_id FROM lecture_sessions
        WHERE classroom_id=? AND status='active'
    """, (classroom_id,))

    if cur.fetchone():
        conn.close()
        return None

    # create lecture
    cur.execute("""
        INSERT INTO lecture_sessions
        (course_id, classroom_id, status, start_time)
        VALUES (?, ?, 'active', CURRENT_TIMESTAMP)
    """, (course_id, classroom_id))

    conn.commit()
    lecture_id = cur.lastrowid
    conn.close()

    print(f"Auto lecture started: {course_id}")

    return lecture_id
    

def end_lecture(lecture_id):
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        UPDATE lecture_sessions
        SET status='closed', end_time=CURRENT_TIMESTAMP
        WHERE lecture_id=?
    """, (lecture_id,))

    conn.commit()
    conn.close()

    print(f"Lecture ended: {lecture_id}")


def get_active_lecture(classroom_id):
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT lecture_id
        FROM lecture_sessions
        WHERE classroom_id=? AND status='active'
        ORDER BY lecture_id DESC
        LIMIT 1
    """, (classroom_id,))

    row = cur.fetchone()
    conn.close()

    return row[0] if row else None