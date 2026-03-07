import numpy as np
from database.database import get_connection


def load_known_faces():

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT students.student_id, users.name, students.face_encoding
        FROM students
        JOIN users
        ON students.user_id = users.id
    """)

    rows = cur.fetchall()
    conn.close()

    encodings = []
    names = []
    ids = []

    for row in rows:

        student_id = row[0]
        name = row[1]
        encoding_bytes = row[2]

        encoding = np.frombuffer(encoding_bytes, dtype=np.float32)

        encodings.append(encoding)
        names.append(name)
        ids.append(student_id)

    return encodings, names, ids