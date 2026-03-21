import psycopg2

DB_NAME = "attendance_system.db"

def get_connection():
    return psycopg2.connect(
        host="localhost",
        database="attendance_system",
        user="postgres",
        password="your_password"
    )

def init_db():
    conn = get_connection()
    cur = conn.cursor()

    # USERS
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            name TEXT,
            role TEXT,
            password TEXT
        )
    """)

    # STUDENTS
    cur.execute("""
        CREATE TABLE IF NOT EXISTS students (
            student_id TEXT PRIMARY KEY,
            name TEXT,
            department TEXT,
            semester INTEGER,
            face_encoding BLOB
        )
    """)

    # CLASSROOMS
    cur.execute("""
        CREATE TABLE IF NOT EXISTS classrooms (
            classroom_id TEXT PRIMARY KEY,
            room_number TEXT
        )
    """)

    # COURSES
    cur.execute("""
        CREATE TABLE IF NOT EXISTS courses (
            course_id TEXT PRIMARY KEY,
            course_name TEXT,
            department TEXT,
            semester INTEGER
        )
    """)

    # LECTURE SESSIONS
    cur.execute("""
        CREATE TABLE IF NOT EXISTS lecture_sessions (
            lecture_id INTEGER PRIMARY KEY AUTOINCREMENT,
            course_id TEXT,
            classroom_id TEXT,
            status TEXT,
            start_time DATETIME,
            end_time DATETIME
        )
    """)

    # ATTENDANCE (CRITICAL UNIQUE CONSTRAINT)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lecture_id INTEGER,
            student_id TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(student_id, lecture_id)
        )
    """)

    # WEEKLY SCHEDULE
    cur.execute("""
        CREATE TABLE IF NOT EXISTS weekly_schedule (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            course_id TEXT,
            classroom_id TEXT,
            day_of_week TEXT,
            start_time TEXT,
            end_time TEXT
        )
    """)

    conn.commit()
    conn.close()

    print("Database initialized successfully.")