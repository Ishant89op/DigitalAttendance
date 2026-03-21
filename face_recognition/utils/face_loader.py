import numpy as np
from database.database import get_connection


def load_known_faces():

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("SELECT student_id, name, face_encoding FROM students")
    rows = cur.fetchall()

    conn.close()

    encodings = []
    names = []
    ids = []

    for row in rows:
        encoding = np.frombuffer(row[2], dtype=np.float32)
        encodings.append(encoding)
        names.append(row[1])
        ids.append(row[0])

    return encodings, names, ids