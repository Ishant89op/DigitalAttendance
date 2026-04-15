# AttendX — Smart Digital Attendance System

> Biometric face-recognition attendance platform for universities.  
> Designed for multi-classroom deployment with a FastAPI backend, PostgreSQL database,  
> InsightFace recognition engine, and a browser-based UI for admins, teachers, and students.

---

## Table of Contents

1. [What the System Does](#1-what-the-system-does)
2. [Architecture Overview](#2-architecture-overview)
3. [Project Structure](#3-project-structure)
4. [Database Schema](#4-database-schema)
5. [How Attendance Works — End to End](#5-how-attendance-works--end-to-end)
6. [API Reference](#6-api-reference)
7. [Frontend Pages](#7-frontend-pages)
8. [Configuration & Environment](#8-configuration--environment)
9. [Setup & Installation](#9-setup--installation)
10. [CSV Data Formats](#10-csv-data-formats)
11. [Face Registration Workflow](#11-face-registration-workflow)
12. [Recognition Engine Deep Dive](#12-recognition-engine-deep-dive)
13. [Analytics System](#13-analytics-system)
14. [Known Bugs & Current Issues](#14-known-bugs--current-issues)
15. [Planned Enhancements](#15-planned-enhancements)
16. [Seed / Demo Data](#16-seed--demo-data)
17. [Key Design Decisions](#17-key-design-decisions)

---

## 1. What the System Does

AttendX automates classroom attendance for institutions using real-time face recognition. Here is the full user journey:

**Admin (one-time setup)**
- Uploads student, teacher, course, classroom, and schedule data via CSV files or directly in the Admin Panel.
- Opens a face registration window at the start of a semester. Students walk up, enter their ID, and the camera captures 20 face samples to build a biometric profile.

**Classroom device (per-lecture, ~2 minutes)**
- Any device (laptop, tablet) placed in the classroom logs in.
- The system suggests the next scheduled lecture for that room automatically.
- The teacher (or device itself) presses "Start Attendance."
- A background camera process launches, reads faces, and marks attendance in real time.
- Up to 4 devices can be active in the same classroom simultaneously; they all write to the same lecture session.
- After class, "End Session" closes the lecture and stops the camera.

**Teacher**
- Views a live dashboard showing who is present and who is absent during the lecture.
- Can manually override any attendance record (mark present or absent).
- Sees per-course analytics: average attendance percentages across all lectures they have taught.

**Student**
- Sees their personal attendance summary: overall percentage and per-subject breakdown.
- Receives visual warnings when their percentage falls below the institution's threshold (default 75%).
- Can view their full attendance history filtered by subject or date range.

**Admin (ongoing)**
- Views the system-wide dashboard: total students, attendance rates by department/semester.
- Receives alerts for students below the threshold across any subject.
- Browses the full audit log of every attendance mark and override.

---

## 2. Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                          Browser (UI)                            │
│  login.html  ·  admin.html  ·  teacher.html  ·  student.html    │
└────────────────────────────┬────────────────────────────────────┘
                             │  HTTP / REST (localhost:8000)
┌────────────────────────────▼────────────────────────────────────┐
│                     FastAPI Backend (api/server.py)              │
│                                                                  │
│  /lecture    /attendance    /analytics    /admin                 │
│                                                                  │
│  Lifespan hooks:                                                 │
│    startup  → init DB pool → run schema migrations               │
│    shutdown → stop all recognition processes → close pool        │
└───────┬──────────────────────────┬──────────────────────────────┘
        │                          │
┌───────▼──────────┐   ┌───────────▼──────────────────────────────┐
│  Services layer  │   │  Recognition Manager                      │
│                  │   │  (core/recognition_manager.py)            │
│  lecture_service │   │                                           │
│  schedule_service│   │  Spawns one subprocess per classroom      │
│  analytics_svc   │   │  when a lecture starts.                   │
│  csv_service     │   │  Kills it when the lecture ends.          │
└───────┬──────────┘   └───────────┬──────────────────────────────┘
        │                          │ asyncio.create_subprocess_exec
┌───────▼──────────────────────────▼──────────────────────────────┐
│                         PostgreSQL 14+                           │
│  asyncpg connection pool (min=2, max=10)                        │
│  All queries use $1 $2 ... positional placeholders              │
└─────────────────────────────────────────────────────────────────┘
        ▲
        │  (separate OS process per classroom)
┌───────┴──────────────────────────────────────────────────────────┐
│              Recognition Engine  (recognition/recognizer.py)      │
│                                                                   │
│  cv2.VideoCapture(0)  →  InsightFace buffalo_l                   │
│  →  cosine similarity match  →  3-frame buffer  →  mark_attendance│
│  Reloads face DB from PostgreSQL every 60 seconds                │
│  Processes up to 6 faces per frame                               │
└──────────────────────────────────────────────────────────────────┘
```

**Why subprocesses for the camera?**  
The camera loop is a blocking, CPU-bound operation. Running it inside the FastAPI async event loop would freeze the entire API. A separate OS process keeps the API fully responsive and allows multiple classrooms to run cameras concurrently without interfering with each other.

---

## 3. Project Structure

```
DigitalAttendance/
│
├── main.py                         CLI entry point (db / register / recognize / server)
├── requirements.txt
├── .env                            Environment variables (DB credentials, CLASSROOM_ID)
├── seed.sql                        Demo data for CSE Sem-4 timetable (IIIT Vadodara)
│
├── config/
│   └── settings.py                 All tuneable constants in frozen dataclasses
│                                   DatabaseSettings · RecognitionSettings · APISettings
│                                   AnalyticsSettings
│
├── core/
│   ├── database.py                 asyncpg pool init/close, get_conn(), transaction()
│   └── recognition_manager.py      spawn / kill recognition subprocesses per classroom
│
├── migrations/
│   └── schema.py                   Idempotent DDL — CREATE TABLE IF NOT EXISTS for all tables
│                                   Run automatically at API startup
│
├── api/
│   ├── server.py                   FastAPI app · CORS · lifespan · router registration
│   └── routers/
│       ├── lecture.py              POST /lecture/start|end  GET /lecture/active/{id}
│       ├── attendance.py           POST /attendance/mark|override  GET /attendance/list
│       ├── analytics.py            GET /analytics/student|teacher|admin
│       └── admin.py                CRUD endpoints + CSV bulk upload + audit log
│
├── services/
│   ├── lecture_service.py          start_lecture() / end_lecture() / get_active_lecture()
│   ├── schedule_service.py         get_current_course() — time-based schedule lookup
│   ├── analytics_service.py        All reporting SQL (student summary, teacher stats,
│   │                               admin dashboard, low-attendance alerts, live snapshot)
│   └── csv_service.py              Transactional CSV import for all 5 entity types
│
├── attendance/
│   └── attendance_manager.py       mark_attendance() · manual_override()
│                                   Both paths write to audit_log
│
├── recognition/
│   └── recognizer.py               Camera loop · InsightFace · cosine match
│                                   Frame buffer · cooldown · auto-start lecture
│
├── registration/
│   └── register_student.py         Admin-first face capture (terminal, headless)
│                                   Captures 20 samples → averages → saves BYTEA
│
├── utils/
│   └── face_utils.py               InsightFace model singleton · load_known_faces()
│                                   normalize() · cosine_match()
│
└── ui/
    ├── login.html                  Role-selector login page (admin / teacher / student)
    ├── admin.html                  CSV upload + data management panel
    ├── teacher.html                Live lecture control + attendance dashboard
    ├── student.html                Personal attendance summary
    ├── css/
    │   └── dashboard.css           Shared dark-theme design system
    └── js/
        └── api.js                  Shared API helper functions
```

---

## 4. Database Schema

All tables are created idempotently in `migrations/schema.py` at every server startup.

### `users`
Authentication table for login. Linked optionally to students/teachers via `user_id`.

| Column | Type | Notes |
|---|---|---|
| id | TEXT PK | gen_random_uuid() |
| name | TEXT | |
| email | TEXT UNIQUE | |
| role | TEXT | `admin` · `teacher` · `student` |
| password_hash | TEXT | |
| created_at | TIMESTAMPTZ | |

### `students`
| Column | Type | Notes |
|---|---|---|
| student_id | TEXT PK | e.g. `202411090` |
| user_id | TEXT FK → users | Optional login link |
| name | TEXT | |
| email | TEXT | |
| department | TEXT | e.g. `CSE` |
| semester | INTEGER | 1–12 |
| face_encoding | BYTEA | 512-dim float32 vector, NULL until registered |
| registered_at | TIMESTAMPTZ | NULL until face captured |

Index: `(semester, department)` — used by analytics JOIN.

### `teachers`
| Column | Type | Notes |
|---|---|---|
| teacher_id | TEXT PK | e.g. `T001` |
| user_id | TEXT FK → users | |
| name | TEXT | |
| email | TEXT | |
| department | TEXT | |

### `classrooms`
| Column | Type | Notes |
|---|---|---|
| classroom_id | TEXT PK | e.g. `CR-2113`, `CR-LAB` |
| room_number | TEXT | |
| building | TEXT | |
| capacity | INTEGER | |

### `courses`
| Column | Type | Notes |
|---|---|---|
| course_id | TEXT PK | e.g. `CS401` |
| course_name | TEXT | |
| department | TEXT | |
| semester | INTEGER | |
| credits | INTEGER | default 3 |

Index: `(semester, department)`.

### `course_teachers`
Junction table: which teacher teaches which course.

| Column | Type |
|---|---|
| id | SERIAL PK |
| course_id | TEXT FK → courses |
| teacher_id | TEXT FK → teachers |

UNIQUE `(course_id, teacher_id)`.

### `weekly_schedule`
The timetable. One row per course-classroom-day-time slot.

| Column | Type | Notes |
|---|---|---|
| schedule_id | SERIAL PK | |
| course_id | TEXT FK → courses | |
| classroom_id | TEXT FK → classrooms | |
| day_of_week | TEXT | `Monday` … `Sunday` |
| start_time | TIME | e.g. `09:00` |
| end_time | TIME | e.g. `10:30` |

Constraint: `end_time > start_time`.  
Index: `(classroom_id, day_of_week)` — used by schedule lookup every frame.

### `lecture_sessions`
One row per actual class held. Created when lecture starts, updated when it ends.

| Column | Type | Notes |
|---|---|---|
| lecture_id | SERIAL PK | |
| course_id | TEXT FK → courses | |
| classroom_id | TEXT FK → classrooms | |
| teacher_id | TEXT FK → teachers | nullable |
| status | TEXT | `active` · `closed` |
| start_time | TIMESTAMPTZ | |
| end_time | TIMESTAMPTZ | nullable until closed |

⚠️ **Known bug:** `UNIQUE (classroom_id, status) DEFERRABLE` — this constraint inadvertently limits a classroom to a single `closed` lecture ever. See [Known Bugs](#14-known-bugs--current-issues).

### `attendance`
One row per student per lecture (presence record).

| Column | Type | Notes |
|---|---|---|
| id | BIGSERIAL PK | |
| lecture_id | INTEGER FK → lecture_sessions | |
| student_id | TEXT FK → students | |
| timestamp | TIMESTAMPTZ | when marked |
| source | TEXT | `face_recognition` · `manual_override` |
| marked_by | TEXT | teacher_id if manual |

UNIQUE `(student_id, lecture_id)` — prevents duplicate marks.  
Indexes: `(lecture_id)`, `(student_id)`, `(timestamp)`.

### `audit_log`
Immutable event trail. Every attendance mark and override writes here.

| Column | Type | Notes |
|---|---|---|
| log_id | BIGSERIAL PK | |
| event_type | TEXT | `attendance_marked` · `manual_override` · `face_registered` |
| actor_id | TEXT | who did it |
| target_id | TEXT | affected student/entity |
| detail | JSONB | extra context (lecture_id, source, ts…) |
| created_at | TIMESTAMPTZ | |

---

## 5. How Attendance Works — End to End

### Step 1 — Schedule resolution
When a lecture is started, `schedule_service.get_current_course(classroom_id)` queries `weekly_schedule` for a row matching the current `day_of_week` and `current_time BETWEEN start_time AND end_time`. Returns the `course_id` or `None`.

### Step 2 — Lecture session creation
`lecture_service.start_lecture()` resolves course_id (from schedule, or passed explicitly), checks no lecture is already active for that room, and inserts a row into `lecture_sessions` with `status = 'active'`.

### Step 3 — Recognition process spawn
`core/recognition_manager.start_recognition_process(classroom_id)` spawns a subprocess running `python main.py recognize --classroom <id>`. The subprocess inherits environment variables including `CLASSROOM_ID`.

### Step 4 — Camera loop (inside the subprocess)
The recognizer (`recognition/recognizer.py`) runs the following loop at ~25 fps:

```
1. Reload face embeddings from DB (every 60 seconds)
2. Check get_active_lecture(classroom_id) → lecture_id
3. Read a frame from cv2.VideoCapture(0)
4. Run InsightFace model.get(frame) → list of detected faces
5. Sort faces by area (largest first), take top 6
6. For each face:
   a. cosine_match(embedding, known_matrix) → (idx, score)
   b. If score ≥ 0.50 threshold: increment frame_buffer[student_id]
   c. If frame_buffer[student_id] ≥ 3 consecutive frames AND not on 30s cooldown:
      → mark_attendance(student_id, lecture_id)
      → reset frame_buffer[student_id]
      → set last_seen[student_id] = now
```

The 3-frame buffer prevents false positives from a passing face. The 30-second cooldown prevents the same student being marked multiple times in one session.

### Step 5 — Attendance record
`attendance_manager.mark_attendance()` inserts into `attendance` with `source = 'face_recognition'` and writes to `audit_log`. Duplicate marks are silently ignored via the UNIQUE constraint.

### Step 6 — End session
Teacher clicks "End Session" → `POST /lecture/end` → `lecture_service.end_lecture()` sets `status = 'closed'` → `recognition_manager.stop_recognition_process()` terminates the subprocess.

---

## 6. API Reference

All endpoints are available with interactive documentation at `http://localhost:8000/docs`.

### Lecture

| Method | Endpoint | Description |
|---|---|---|
| POST | `/lecture/start` | Start lecture + spawn camera process |
| POST | `/lecture/end` | End lecture + stop camera |
| GET | `/lecture/active/{classroom_id}` | Active lecture ID for a room |
| GET | `/lecture/{lecture_id}` | Full lecture detail + attendance count |
| GET | `/lecture/{lecture_id}/live` | Real-time present/absent snapshot |

**POST /lecture/start — request body:**
```json
{
  "classroom_id": "CR-2113",
  "course_id": null,
  "teacher_id": "T001",
  "force": true
}
```
If `course_id` is `null`, the system auto-detects from schedule. If `force: true` and no scheduled course exists right now, it falls back to any course linked to this classroom.

### Attendance

| Method | Endpoint | Description |
|---|---|---|
| POST | `/attendance/mark` | Mark attendance (called by face rec engine) |
| POST | `/attendance/override` | Teacher manual override |
| GET | `/attendance/count/{lecture_id}` | Count of present students |
| GET | `/attendance/list/{lecture_id}` | Full list of present students |

**POST /attendance/override — request body:**
```json
{
  "student_id": "202411090",
  "lecture_id": 42,
  "teacher_id": "T001",
  "present": true
}
```
`present: false` deletes the attendance record (marks absent).

### Analytics

| Method | Endpoint | Description |
|---|---|---|
| GET | `/analytics/student/{student_id}` | Overall % + per-subject breakdown |
| GET | `/analytics/student/{student_id}/history` | Full history (filter by course/date) |
| GET | `/analytics/teacher/{teacher_id}` | Teacher's course stats |
| GET | `/analytics/admin/dashboard` | System-wide summary |
| GET | `/analytics/admin/alerts` | Students below threshold |

### Admin

| Method | Endpoint | Description |
|---|---|---|
| POST | `/admin/students` | Add single student |
| GET | `/admin/students` | List students (filter: department, semester) |
| POST | `/admin/teachers` | Add single teacher |
| GET | `/admin/teachers` | List teachers |
| POST | `/admin/courses` | Add single course |
| GET | `/admin/courses` | List courses |
| POST | `/admin/classrooms` | Add classroom |
| GET | `/admin/schedule/{classroom_id}` | Get classroom timetable |
| POST | `/admin/schedule` | Add schedule entry |
| POST | `/admin/upload/students` | Bulk CSV import |
| POST | `/admin/upload/teachers` | Bulk CSV import |
| POST | `/admin/upload/courses` | Bulk CSV import |
| POST | `/admin/upload/schedule` | Bulk CSV import |
| POST | `/admin/upload/course-teachers` | Bulk CSV import |
| GET | `/admin/audit-log` | Recent audit entries (default: last 100) |

---

## 7. Frontend Pages

All pages are served as static HTML from `ui/`. They call the FastAPI backend directly via `fetch()`.

### `login.html`
Dark-theme role selector. Three login paths: Admin, Teacher, Student. Animates on load. Redirects to the appropriate dashboard on success.

### `admin.html`
Admin panel with:
- CSV file upload widgets for all 5 entity types (students, teachers, courses, schedule, course-teachers). Each shows inserted/skipped counts after import.
- Lists of all students, teachers, courses filtered by department/semester.
- Audit log viewer.

### `teacher.html`
Live lecture control panel with:
- Classroom selector dropdown (currently hardcoded: CR-2113, CR-LAB).
- Course selector (auto-detect or manual).
- "Start Attendance" / "End Session" buttons.
- Live statistics cards: Present · Absent · Attendance % · Enrolled.
- Two live tables: present students (with timestamp + source) and absent students (with manual override button).
- Course statistics tab with historical per-course averages.

### `student.html`
Personal attendance dashboard:
- Overall attendance percentage with status ring.
- Per-subject cards showing attended / total / percentage with status colour coding (good / warning / critical).
- Attendance history table.

### `css/dashboard.css`
Shared design system used by teacher and student pages. Dark background (`#080c14`), cyan accent (`#00d4ff`), green for success, amber for warning, red for danger. Space Mono for mono elements, DM Sans for body text.

### `js/api.js`
Shared helper module. Provides `apiFetch(path, options)` wrapper that prepends the backend base URL and handles JSON parsing. All pages import this.

---

## 8. Configuration & Environment

All settings live in `config/settings.py` as frozen dataclasses loaded at import time.

### `.env` file (copy from `.env.example`)

```env
# PostgreSQL connection
DB_HOST=localhost
DB_PORT=5432
DB_NAME=attendance_system
DB_USER=postgres
DB_PASSWORD=your_password_here

# Per-device: set before running recognizer
CLASSROOM_ID=CR-2113
```

### `config/settings.py` — tuneable constants

| Setting | Default | Description |
|---|---|---|
| `recog.model_name` | `buffalo_l` | InsightFace model pack |
| `recog.det_size` | `(640, 640)` | Face detection resolution |
| `recog.ctx_id` | `-1` | `-1` = CPU, `0` = first GPU |
| `recog.similarity_threshold` | `0.50` | Minimum cosine similarity to accept a match |
| `recog.cooldown_seconds` | `30` | Seconds before same student can be marked again |
| `recog.max_faces_per_frame` | `6` | Maximum faces processed per frame |
| `recog.samples_required` | `20` | Samples captured during registration |
| `recog.embedding_dim` | `512` | InsightFace embedding dimensions |
| `analytics.low_attendance_threshold` | `75.0` | % below which warning fires |
| `analytics.critical_threshold` | `60.0` | % below which critical alert fires |
| `db.pool_min` | `2` | Minimum DB connections |
| `db.pool_max` | `10` | Maximum DB connections |

---

## 9. Setup & Installation

### Prerequisites
- Python 3.11+
- PostgreSQL 14+
- A webcam (for recognition and registration terminals)
- Git

### Installation

```bash
# Clone the repository
git clone <repo-url>
cd DigitalAttendance

# Create virtual environment
python -m venv venv
source venv/bin/activate       # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

> **Note on InsightFace:** The first run downloads the `buffalo_l` model pack (~300MB) to `~/.insightface/models/`. This is a one-time download. Ensure internet access on first launch.

### Database setup

```bash
# 1. Create the PostgreSQL database
psql -U postgres -c "CREATE DATABASE attendance_system;"

# 2. Configure .env
cp .env .env.backup
# Edit .env — fill in DB_HOST, DB_NAME, DB_USER, DB_PASSWORD

# 3. Run schema migrations
python main.py db
# Output: ✔  Schema migration complete.
```

Migrations run automatically on every server start, so `python main.py db` is only needed before the first `server` launch.

### Start the API server

```bash
python main.py server
# or directly:
uvicorn api.server:app --host 0.0.0.0 --port 8000 --reload
```

Swagger UI: `http://localhost:8000/docs`  
Health check: `http://localhost:8000/`

### Load demo data (optional)

```bash
psql -U postgres -d attendance_system -f seed.sql
```

This loads 2 classrooms, 6 CSE Sem-4 courses, 6 teachers, 5 students, and a full weekly timetable based on IIIT Vadodara's CSE Sem-4 schedule.

### Open the frontend

Open any of the UI pages directly in a browser:
```
ui/login.html
```
No web server required — all pages call `http://localhost:8000` directly.

### Selenium Testing (Complete Project UI)

This repository now includes a full Selenium smoke suite for all frontend roles/pages:

- Login (`ui/login.html`)
- Student dashboard (`ui/student.html`)
- Teacher dashboard + session control (`ui/teacher.html`)
- Admin console + data tabs + audit (`ui/admin.html`)
- Classroom view + upcoming lecture start (`ui/classroom.html`)

The tests use mocked API responses in-browser so they can run reliably even when PostgreSQL/camera processes are not running.

Prerequisites:
- Chrome or Edge installed
- Python dependencies installed from `requirements.txt`

Run tests and generate HTML report:

```bash
python -m pytest tests/selenium -m selenium --junitxml=reports/selenium/junit.xml
python tests/selenium/build_html_report.py --input reports/selenium/junit.xml --output reports/selenium/report.html
```

PowerShell convenience command (Windows):

```powershell
./run_selenium_tests.ps1
```

Useful options:
- `./run_selenium_tests.ps1 -Browser edge`
- `./run_selenium_tests.ps1 -Headed`
- `./run_selenium_tests.ps1 -OpenReport`

Generated report path:
- `reports/selenium/report.html`

---

## 10. CSV Data Formats

All CSV files use UTF-8 encoding. The first row must be a header. Extra columns are ignored. Rows that fail validation are skipped (not rolled back) and counted in the `skipped` response.

### `students.csv`
```csv
student_id,name,email,department,semester
202411090,Shreyash Chaurasia,202411090@university.edu,CSE,4
202411044,Ishant Yadav,202411044@university.edu,CSE,4
```

### `teachers.csv`
```csv
teacher_id,name,email,department
T001,Prof. Mehta,mehta@university.edu,CSE
T002,Prof. Shah,shah@university.edu,CSE
```

### `courses.csv`
```csv
course_id,course_name,department,semester,credits
CS401,Computer Organisation and Architecture,CSE,4,4
CS402,Database Management Systems,CSE,4,4
```
`credits` is optional; defaults to 3.

### `schedule.csv`
```csv
course_id,classroom_id,day_of_week,start_time,end_time
CS401,CR-2113,Monday,14:00,15:30
CS402,CR-2113,Tuesday,14:00,15:30
```
`day_of_week` must match exactly: `Monday`, `Tuesday`, `Wednesday`, `Thursday`, `Friday`, `Saturday`, `Sunday`.  
Times in `HH:MM` 24-hour format.

### `course_teachers.csv`
```csv
course_id,teacher_id
CS401,T001
CS402,T002
```

---

## 11. Face Registration Workflow

Registration is a one-time per-student operation, ideally done in the first week of every semester.

```bash
python main.py register
```

**What happens:**
1. The terminal prompts: `Enter Student ID:`
2. The system verifies the ID exists in the `students` table. If not, it aborts — the admin must add the student record first.
3. If the student already has a face registered, you are asked to confirm overwrite.
4. The camera opens. The student looks directly at the camera.
5. 20 face samples are captured over ~5–10 seconds (visible progress bar in terminal).
6. All 20 embeddings are averaged and L2-normalized into a single 512-dimensional float32 vector.
7. The vector is stored as `BYTEA` in `students.face_encoding`.
8. `registered_at` timestamp and an `audit_log` entry are written.

**Important notes:**
- Raw images are never stored. The system only stores the averaged embedding. This cannot be reversed back to a face image (privacy by design).
- The registration terminal does not need to be the same machine as the classroom recognition terminal.
- New registrations are picked up by running recognition engines within 60 seconds (the face DB reload interval).
- Run on a machine with a webcam. Headless servers without cameras cannot run registration.

---

## 12. Recognition Engine Deep Dive

File: `recognition/recognizer.py`

### Key constants (at top of file)

| Constant | Value | Effect |
|---|---|---|
| `RECOGNITION_BUFFER` | `3` | Consecutive matching frames before marking |
| `RELOAD_INTERVAL_SECS` | `60` | How often face DB is refreshed from PostgreSQL |
| `WAIT_POLL_SECS` | `3` | Poll interval when no active lecture |
| `AUTO_START` | `True` | Auto-create lecture from schedule if none active |

### InsightFace `buffalo_l` model
- Detects and embeds faces in a single `model.get(frame)` call.
- Returns a list of `Face` objects, each with `.bbox`, `.embedding` (512-dim float32), `.det_score`.
- Detection resolution is set to `640×640` in settings for a balance of speed and accuracy.
- The camera is explicitly set to `640×480` capture to keep frame processing fast.

### Cosine similarity matching
`utils/face_utils.cosine_match()` performs:
```python
similarities = known_matrix @ query   # matrix multiply: (N,512) @ (512,) = (N,)
best_idx = np.argmax(similarities)
best_score = similarities[best_idx]
```
Both `known_matrix` rows and `query` are L2-normalized, so this is equivalent to cosine similarity. Threshold: `0.50` (configurable). A score of `1.0` means identical faces; `0.0` means no similarity.

### Multi-device support
Multiple devices can run the recognizer for the same classroom simultaneously. They all call `mark_attendance()` for the same `lecture_id`. Duplicate marks are absorbed by the `UNIQUE (student_id, lecture_id)` constraint in the `attendance` table — no data corruption.

### Why the process is separate
The recognition loop is CPU-bound (model inference) and must not block FastAPI's async event loop. Using `asyncio.create_subprocess_exec()` keeps them completely isolated. The API server streams the subprocess's stdout to its own logger for debugging.

---

## 13. Analytics System

File: `services/analytics_service.py`

All analytics are computed entirely in PostgreSQL using aggregation queries — no Python-side computation. This means analytics scale with your database, not your server's RAM.

### Student summary (`GET /analytics/student/{id}`)
Joins `courses` → `students` (matching department + semester) → `lecture_sessions` (closed only) → `attendance`. Returns:
- Overall attendance percentage across all subjects.
- Per-subject: total lectures held, attended, percentage, status (`good` / `warning` / `critical`).

### Teacher stats (`GET /analytics/teacher/{id}`)
Returns each course the teacher teaches with: total lectures held, total student-attendances, average attendance percentage.

### Admin dashboard (`GET /analytics/admin/dashboard`)
System-wide aggregate: total students, total lectures, overall attendance rate, breakdown by department.

### Low-attendance alerts (`GET /analytics/admin/alerts`)
Returns all students whose attendance in any subject falls below `analytics.low_attendance_threshold` (default 75%). Useful for the admin to flag students at risk.

### Live lecture snapshot (`GET /lecture/{id}/live`)
For the teacher's live dashboard. Returns the list of enrolled students split into present and absent based on real-time `attendance` table contents.

### Thresholds (configurable in `config/settings.py`)

| Status | Condition |
|---|---|
| `good` | percentage ≥ 75% |
| `warning` | 60% ≤ percentage < 75% |
| `critical` | percentage < 60% |

---

## 14. Known Bugs & Current Issues

### Bug 1 — `UNIQUE (classroom_id, status)` constraint is broken
**File:** `migrations/schema.py`, `lecture_sessions` table.  
**Problem:** The constraint `UNIQUE (classroom_id, status) DEFERRABLE` means a classroom can have at most one row with `status = 'closed'`. After the first lecture ends, every subsequent lecture end will hit a unique violation.  
**Fix:** Remove the UNIQUE constraint. The one-active-per-room guard should be done in application logic inside `start_lecture()` (already done via the `SELECT ... WHERE status = 'active'` check), not via a DB constraint on status.

### Bug 2 — `start_lecture` force-fallback picks a random course
**File:** `services/lecture_service.py`, line: `SELECT course_id FROM weekly_schedule WHERE classroom_id = $1 LIMIT 1`  
**Problem:** No `ORDER BY`. When outside scheduled hours and `force=True`, this selects an arbitrary course — often the wrong one.  
**Fix:** Order by time proximity: `ORDER BY ABS(EXTRACT(EPOCH FROM (start_time - CURRENT_TIME)))` to pick the nearest upcoming course.

### Bug 3 — No classroom device authentication
**Problem:** There is no `classroom_id` login endpoint. Classroom devices have no scoped identity token. The teacher dashboard has classrooms hardcoded as `CR-2113` and `CR-LAB` in an HTML dropdown.  
**Fix needed:** `POST /classroom/login` with classroom_id + PIN → returns a classroom-scoped JWT. Classroom login page (`ui/classroom.html`) with smart upcoming lecture suggestions.

### Bug 4 — Schedule service only matches the exact current moment
**File:** `services/schedule_service.py`  
**Problem:** `get_current_course()` returns a course only if the current time is strictly within a scheduled slot. A lecture started 2 minutes early or a device that boots after the scheduled start time finds nothing.  
**Fix:** Add a `GET /lecture/upcoming/{classroom_id}?limit=3` endpoint returning the next N scheduled lectures (ordered by time), so the device can show contextual suggestions and let the user pick.

### Bug 5 — In-memory recognition process registry lost on restart
**File:** `core/recognition_manager.py`  
**Problem:** `_processes: dict[str, asyncio.subprocess.Process]` is a module-level dict. If the FastAPI server crashes and restarts, this dict is empty — but the database still shows lectures as `active`. The recognizer auto-starts a new lecture via `AUTO_START`, potentially violating the active-lecture uniqueness guard.  
**Fix:** On server startup, query for any orphaned `active` lectures (started before server boot) and either close them automatically or reconcile against running processes.

### Bug 6 — Frontend classroom options are hardcoded
**File:** `ui/teacher.html`  
**Problem:** `<select id="classroom-select">` has hardcoded `<option>` values `CR-2113` and `CR-LAB`. Adding a new classroom to the database does not update the dropdown.  
**Fix:** Populate the dropdown dynamically via `GET /admin/classrooms` on page load.

---

## 15. Planned Enhancements

The following features are identified for the next development phase:

| Feature | Description |
|---|---|
| Classroom login ID | Per-device classroom authentication with PIN, returning a scoped JWT. Up to 4 devices per room sharing the same lecture session. |
| Smart lecture suggestions | Classroom login page shows the next 2–3 upcoming lectures for that room based on schedule + current time, with countdown timers. |
| Admin inline spreadsheet editor | Load any database table (students, teachers, courses, schedule) into an editable grid within the admin page. Support row add, edit, delete, save — no CSV required. |
| JWT authentication | Protect all API endpoints with role-scoped JWT tokens. Currently the API is completely open. |
| WebSocket live dashboard | Replace the teacher dashboard's polling with WebSocket push so attendance updates appear instantly without page-side `setInterval` calls. |
| Liveness detection | Add blink or head-movement check during face recognition to prevent photo spoofing (holding up a photo to the camera). |
| PDF / Excel report export | Allow teachers and admins to download per-lecture or per-semester attendance reports as PDF or Excel files. |
| Geofencing | Validate that student's device (if they have a companion app) is on campus at mark time. |
| Student companion app | Mobile app for students to view their attendance, receive low-attendance warnings, and view lecture schedules. |
| Multi-department scalability | Currently the analytics JOIN uses `department + semester` matching. Multiple departments with the same semester number work correctly, but load testing is needed at scale. |

---

## 16. Seed / Demo Data

`seed.sql` contains a complete test dataset based on the CSE Semester 4 timetable at IIIT Vadodara:

**Classrooms:** `CR-2113` (Main Block, 60 seats), `CR-LAB` (Lab Block, 30 seats)

**Courses (CSE Sem 4):**

| ID | Name | Credits |
|---|---|---|
| CS401 | Computer Organisation and Architecture | 4 |
| CS402 | Database Management Systems | 4 |
| CS403 | System Software | 3 |
| CS404 | Software Engineering | 3 |
| CS405 | Mathematics | 4 |
| CS406 | Economics | 3 |

**Sample students:**

| ID | Name | Email |
|---|---|---|
| 202411090 | Shreyash Chaurasia | 202411090@diu.iiitvadodara.ac.in |
| 202411044 | Ishant Yadav | 202411044@diu.iiitvadodara.ac.in |
| 202411052 | Kavya Sharma | 202411052@diu.iiitvadodara.ac.in |
| 202411064 | Naman Panwar | 202411064@diu.iiitvadodara.ac.in |
| 202411028 | Chinmay Patil | 202411028@diu.iiitvadodara.ac.in |

**Sample weekly timetable (Mon–Fri):**

| Day | Time | Room | Course |
|---|---|---|---|
| Monday | 09:00–13:15 | CR-LAB | CS401 COA Lab |
| Monday | 14:00–15:30 | CR-2113 | CS401 COA Theory |
| Monday | 15:30–17:00 | CR-2113 | CS403 System Software |
| Tuesday | 09:00–13:00 | CR-LAB | CS405 Maths Lab + Tutorial |
| Tuesday | 14:00–15:30 | CR-2113 | CS402 DBMS |
| Tuesday | 15:30–17:00 | CR-2113 | CS404 Software Engineering |
| Wednesday | 10:45–12:30 | CR-LAB | CS402 DBMS Lab |
| Wednesday | 14:00–15:30 | CR-2113 | CS406 Economics |
| Wednesday | 15:30–17:00 | CR-2113 | CS401 COA |
| Thursday | 09:00–12:00 | CR-LAB | CS404 SE Tutorial + Lab |
| Thursday | 14:00–15:30 | CR-2113 | CS403 System Software |
| Thursday | 15:30–17:00 | CR-2113 | CS402 DBMS |
| Friday | 14:00–15:30 | CR-2113 | CS406 Economics |

---

## 17. Key Design Decisions

**Why asyncpg instead of SQLAlchemy or psycopg2?**  
FastAPI is fully async. asyncpg is the fastest async PostgreSQL driver for Python, using the binary wire protocol directly. SQLAlchemy's async layer adds overhead; psycopg2 is synchronous and would block the event loop.

**Why PostgreSQL `$1, $2` placeholders?**  
PostgreSQL uses positional placeholders, not `?` (that's SQLite). Early versions of this project used `?` with asyncpg, which caused every query to throw `invalid syntax` errors. All queries now use `$1, $2, ...`.

**Why store only the averaged embedding, not raw face images?**  
Privacy. Raw images are biometric data subject to GDPR/PDPA regulations. Storing only the 512-dim float32 vector satisfies the functional requirement (matching) without retaining reversible biometric data.

**Why a 3-frame recognition buffer?**  
A single-frame match can be a false positive from a passing face, a reflection, or a photo. Requiring 3 consecutive matching frames with the same identity reduces false positive marks to near zero in practice.

**Why run the recognition engine as a subprocess, not an async task?**  
InsightFace's model inference is CPU-bound and blocks Python's GIL. Running it as an `asyncio.Task` inside the FastAPI event loop would stall the entire API. A separate subprocess (via `asyncio.create_subprocess_exec`) gives it its own Python interpreter and CPU core.

**Why reload face DB every 60 seconds instead of on-demand?**  
New students can be registered at any terminal during the registration window (first 1–2 weeks of semester). A 60-second reload ensures all classroom recognition engines pick up new registrations automatically without requiring a restart. The reload is a single lightweight `SELECT student_id, name, face_encoding FROM students WHERE face_encoding IS NOT NULL`.

**Why `BYTEA` for face embeddings?**  
PostgreSQL's native binary type. The original schema used `BLOB` (SQLite-only). `BYTEA` stores the raw float32 bytes efficiently and roundtrips cleanly through asyncpg without any encoding overhead.

**Why `ON CONFLICT DO NOTHING` in CSV imports?**  
Bulk imports are expected to be run multiple times (e.g., admin re-exports and re-imports the same student list). Silently skipping duplicates means imports are idempotent. The returned `inserted` / `skipped` counts tell the admin what happened.
