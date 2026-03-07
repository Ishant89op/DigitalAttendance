import sqlite3

DB_NAME = "attendance_system.db"


def get_connection():
    return sqlite3.connect(DB_NAME)


def init_db():

    conn = get_connection()
    cursor = conn.cursor()

    # USERS TABLE
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        role TEXT NOT NULL,
        password TEXT
    )
    """)

    # STUDENTS TABLE
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS students (
        student_id TEXT PRIMARY KEY,
        user_id TEXT,
        face_encoding BLOB,
        department TEXT,
        semester INTEGER,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )
    """)

    # COURSES TABLE
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS courses (
        id TEXT PRIMARY KEY,
        course_name TEXT,
        teacher_id TEXT
    )
    """)

    # ATTENDANCE TABLE
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS attendance (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id TEXT,
        course_id TEXT,
        status TEXT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        marked_by TEXT
    )
    """)

    conn.commit()
    conn.close()

    print("Database initialized successfully")


if __name__ == "__main__":
    init_db()