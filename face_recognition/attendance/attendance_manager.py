from database.database import get_connection

def mark_attendance(student_id, lecture_id):
    conn = get_connection()
    cur = conn.cursor()

    try:
        cur.execute("""
            INSERT INTO attendance (student_id, lecture_id)
            VALUES (?, ?)
        """, (student_id, lecture_id))

        conn.commit()
        print(f"✔ Attendance marked: {student_id}")

    except:
        # Duplicate entry (already marked)
        pass

    finally:
        conn.close()