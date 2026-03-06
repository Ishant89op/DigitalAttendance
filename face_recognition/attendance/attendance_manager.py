from database.database import get_connection
from datetime import datetime


def mark_attendance(student_id, course_id, status="present", marked_by="AI"):
    """
    Marks attendance for a student for a specific course.

    Parameters
    ----------
    student_id : str
        Student identifier
    course_id : str
        Course identifier
    status : str
        present / absent / late / excused
    marked_by : str
        AI or Teacher
    """

    conn = get_connection()
    cursor = conn.cursor()

    # prevent duplicate attendance for same course on same day
    cursor.execute("""
        SELECT * FROM attendance
        WHERE student_id = ?
        AND course_id = ?
        AND DATE(timestamp) = DATE('now')
    """, (student_id, course_id))

    already_marked = cursor.fetchone()

    if already_marked:
        print(f"Attendance already marked today for {student_id} in {course_id}")

    else:

        cursor.execute("""
            INSERT INTO attendance (
                student_id,
                course_id,
                status,
                marked_by,
                timestamp
            )
            VALUES (?, ?, ?, ?, ?)
        """, (
            student_id,
            course_id,
            status,
            marked_by,
            datetime.now()
        ))

        conn.commit()

        print(f"Attendance marked: {student_id} | {course_id} | {status}")

    conn.close()


def get_today_attendance(course_id=None):
    """
    Returns today's attendance list
    """

    conn = get_connection()
    cursor = conn.cursor()

    if course_id:

        cursor.execute("""
            SELECT student_id, course_id, status, timestamp
            FROM attendance
            WHERE DATE(timestamp)=DATE('now')
            AND course_id=?
        """, (course_id,))

    else:

        cursor.execute("""
            SELECT student_id, course_id, status, timestamp
            FROM attendance
            WHERE DATE(timestamp)=DATE('now')
        """)

    rows = cursor.fetchall()

    conn.close()

    attendance_list = []

    for row in rows:

        attendance_list.append({
            "student_id": row[0],
            "course_id": row[1],
            "status": row[2],
            "timestamp": row[3]
        })

    return attendance_list


def get_student_attendance(student_id):
    """
    Returns attendance history for a student
    """

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT course_id, status, timestamp
        FROM attendance
        WHERE student_id=?
        ORDER BY timestamp DESC
    """, (student_id,))

    rows = cursor.fetchall()

    conn.close()

    result = []

    for row in rows:

        result.append({
            "course_id": row[0],
            "status": row[1],
            "timestamp": row[2]
        })

    return result


def calculate_student_attendance_percentage(student_id):
    """
    Calculates attendance percentage for a student
    """

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT COUNT(*) FROM attendance
        WHERE student_id=?
    """, (student_id,))

    total_classes = cursor.fetchone()[0]

    cursor.execute("""
        SELECT COUNT(*) FROM attendance
        WHERE student_id=? AND status='present'
    """, (student_id,))

    present_classes = cursor.fetchone()[0]

    conn.close()

    if total_classes == 0:
        return 0

    percentage = (present_classes / total_classes) * 100

    return round(percentage, 2)


def get_class_attendance_summary(course_id):
    """
    Returns today's class attendance statistics
    """

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT COUNT(DISTINCT student_id)
        FROM attendance
        WHERE course_id=?
    """, (course_id,))

    total_students = cursor.fetchone()[0]

    cursor.execute("""
        SELECT COUNT(*)
        FROM attendance
        WHERE course_id=?
        AND status='present'
        AND DATE(timestamp)=DATE('now')
    """, (course_id,))

    present = cursor.fetchone()[0]

    absent = total_students - present

    conn.close()

    return {
        "course_id": course_id,
        "total_students": total_students,
        "present_today": present,
        "absent_today": absent
    }