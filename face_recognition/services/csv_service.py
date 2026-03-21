import csv
from database.database import get_connection


# ==========================
# IMPORT STUDENTS
# ==========================
def import_students(file_path):

    conn = get_connection()
    cur = conn.cursor()

    with open(file_path, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)

        for row in reader:
            try:
                cur.execute("""
                    INSERT INTO students (student_id, name, department, semester)
                    VALUES (?, ?, ?, ?)
                """, (
                    row['student_id'],
                    row['name'],
                    row['department'],
                    int(row['semester'])
                ))
            except:
                pass  # ignore duplicates

    conn.commit()
    conn.close()

    print("✔ Students imported")


# ==========================
# IMPORT COURSES
# ==========================
def import_courses(file_path):

    conn = get_connection()
    cur = conn.cursor()

    with open(file_path, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)

        for row in reader:
            try:
                cur.execute("""
                    INSERT INTO courses (course_id, course_name, department, semester)
                    VALUES (?, ?, ?, ?)
                """, (
                    row['course_id'],
                    row['course_name'],
                    row['department'],
                    int(row['semester'])
                ))
            except:
                pass

    conn.commit()
    conn.close()

    print("✔ Courses imported")


# ==========================
# IMPORT SCHEDULE
# ==========================
def import_schedule(file_path):

    conn = get_connection()
    cur = conn.cursor()

    with open(file_path, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)

        for row in reader:
            try:
                cur.execute("""
                    INSERT INTO weekly_schedule
                    (course_id, classroom_id, day_of_week, start_time, end_time)
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    row['course_id'],
                    row['classroom'],
                    row['day'],
                    row['start_time'],
                    row['end_time']
                ))
            except:
                pass

    conn.commit()
    conn.close()

    print("✔ Schedule imported")