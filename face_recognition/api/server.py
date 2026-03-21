from fastapi import FastAPI
from pydantic import BaseModel
from database.database import get_connection
from services.lecture_service import start_lecture, end_lecture, get_active_lecture
from fastapi.middleware.cors import CORSMiddleware

from fastapi import UploadFile, File
import shutil
from services.csv_service import import_students, import_courses, import_schedule

from services.schedule_service import get_current_course
from services.lecture_service import start_lecture

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class LectureStart(BaseModel):
    course_id: str
    classroom_id: str


class LectureEnd(BaseModel):
    lecture_id: int


@app.get("/")
def home():
    return {"message": "Attendance API Running"}


@app.post("/lecture/start")
def start(data: LectureStart):
    lecture_id = start_lecture(data.course_id, data.classroom_id)
    return {"lecture_id": lecture_id}


@app.post("/lecture/end")
def end(data: LectureEnd):
    end_lecture(data.lecture_id)
    return {"message": "Lecture ended"}


@app.get("/lecture/current/{classroom_id}")
def current(classroom_id: str):
    lecture_id = get_active_lecture(classroom_id)
    return {"lecture_id": lecture_id}

@app.get("/lecture/detect/{classroom_id}")
def detect_lecture(classroom_id: str):

    course_id = get_current_course(classroom_id)

    return {
        "course_id": course_id
    }


@app.post("/lecture/auto-start/{classroom_id}")
def auto_start(classroom_id: str):

    lecture_id = start_lecture(classroom_id)

    if not lecture_id:
        return {"message": "No lecture or already active"}

    return {"lecture_id": lecture_id}


@app.post("/lecture/auto-start/{classroom_id}")
def auto_start(classroom_id: str):

    lecture_id = start_lecture(classroom_id)

    if not lecture_id:
        return {"message": "No lecture or already active"}

    return {"lecture_id": lecture_id}


@app.get("/students")
def get_students():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("SELECT student_id, name FROM students")
    rows = cur.fetchall()

    conn.close()

    return [{"id": r[0], "name": r[1]} for r in rows]



@app.post("/admin/upload/students")
async def upload_students(file: UploadFile = File(...)):

    file_path = f"temp_{file.filename}"

    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    import_students(file_path)

    return {"message": "Students uploaded"}


@app.post("/admin/upload/courses")
async def upload_courses(file: UploadFile = File(...)):

    file_path = f"temp_{file.filename}"

    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    import_courses(file_path)

    return {"message": "Courses uploaded"}



@app.post("/admin/upload/schedule")
async def upload_schedule(file: UploadFile = File(...)):

    file_path = f"temp_{file.filename}"

    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    import_schedule(file_path)

    return {"message": "Schedule uploaded"}     