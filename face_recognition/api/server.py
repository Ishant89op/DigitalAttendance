from fastapi import FastAPI
from pydantic import BaseModel
from database.database import get_connection
from fastapi.middleware.cors import CORSMiddleware
import json

async def broadcast_attendance(data):

    for connection in connections:
        await connection.send_text(json.dumps(data))

app = FastAPI()

# Enable CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# -------------------------------
# Models
# -------------------------------

class LoginRequest(BaseModel):
    id: str
    password: str


class AttendanceRequest(BaseModel):
    student_id: str
    course_id: str
    status: str


# -------------------------------
# Basic Route
# -------------------------------

@app.get("/")
def home():
    return {"message": "Attendance API running"}


# -------------------------------
# Login
# -------------------------------

@app.post("/login")
def login(data: LoginRequest):

    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        "SELECT id,name,role,password FROM users WHERE id=?",
        (data.id,)
    )

    user = cur.fetchone()
    conn.close()

    if not user:
        return {"error": "User not found"}

    if user[3] != data.password:
        return {"error": "Incorrect password"}

    return {
        "id": user[0],
        "name": user[1],
        "role": user[2]
    }


# -------------------------------
# Manual Attendance (Teacher)
# -------------------------------

@app.post("/attendance/mark")
def mark_attendance_api(data: AttendanceRequest):

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO attendance (student_id,course_id,status,marked_by)
        VALUES (?, ?, ?, ?)
    """, (data.student_id, data.course_id, data.status, "Teacher"))

    conn.commit()
    conn.close()

    return {"message": "Attendance marked"}


# -------------------------------
# Student Analytics
# -------------------------------

@app.get("/analytics/student/{student_id}")
def student_analytics(student_id: str):

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT COUNT(*) FROM attendance
        WHERE student_id=?
    """, (student_id,))
    total = cur.fetchone()[0]

    cur.execute("""
        SELECT COUNT(*) FROM attendance
        WHERE student_id=? AND status='present'
    """, (student_id,))
    present = cur.fetchone()[0]

    conn.close()

    percentage = 0

    if total > 0:
        percentage = (present / total) * 100

    return {
        "student_id": student_id,
        "total_classes": total,
        "present": present,
        "attendance_percentage": round(percentage, 2)
    }


# -------------------------------
# Class Analytics
# -------------------------------

@app.get("/analytics/class/{course_id}")
def class_analytics(course_id: str):

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT COUNT(DISTINCT student_id)
        FROM attendance
        WHERE course_id=?
    """, (course_id,))
    total_students = cur.fetchone()[0]

    cur.execute("""
        SELECT COUNT(*)
        FROM attendance
        WHERE course_id=?
        AND status='present'
        AND DATE(timestamp)=DATE('now')
    """, (course_id,))
    present = cur.fetchone()[0]

    conn.close()

    absent = total_students - present

    return {
        "course_id": course_id,
        "present_today": present,
        "absent_today": absent
    }


# -------------------------------
# Students List
# -------------------------------

@app.get("/students")
def get_students():

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT student_id, user_id
        FROM students
    """)

    rows = cur.fetchall()
    conn.close()

    students = []

    for row in rows:
        students.append({
            "student_id": row[0],
            "user_id": row[1]
        })

    return students

from fastapi import WebSocket
from typing import List

connections: List[WebSocket] = []

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    connections.append(websocket)

    try:
        while True:
            await websocket.receive_text()
    except:
        connections.remove(websocket)