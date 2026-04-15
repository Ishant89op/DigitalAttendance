# AttendX - Smart Digital Attendance System

AttendX is a face-recognition attendance platform for colleges and classrooms.
It includes role-based dashboards for Admin, Teacher, Student, and Classroom Device users.

## Overview

AttendX handles the full attendance lifecycle:

- lecture/session start and end
- face-based automatic attendance marking
- teacher manual attendance override
- student attendance history and disputes
- admin analytics, reminders, and exports

## Core Features

### Admin

- Manage students, teachers, courses, and classroom metadata
- View system-wide analytics and low-attendance alerts
- Generate and manage defaulter reminders
- Export filtered attendance data (Excel/PDF)
- Reset user passwords

### Teacher

- View course records and student-wise percentages
- Run live session control (start/end attendance)
- Use Manual Attendance section for past lectures
- Resolve student disputes for assigned courses
- Export attendance reports

### Student

- View subject-wise and overall attendance
- View lecture-wise history (present/absent)
- Raise attendance disputes with course/lecture details
- View risk forecast and dispute outcomes

### Classroom Device

- Login with classroom credentials
- Start lecture attendance from scheduled or selected course
- Run recognition pipeline for live marking

## Tech Stack

- Backend: FastAPI, asyncpg, PostgreSQL
- Recognition: InsightFace + OpenCV + NumPy
- Frontend: Static HTML/CSS/JS dashboards
- Testing: pytest, Selenium, pytest-html

## Project Layout

```text
DigitalAttendance/
|-- main.py
|-- requirements.txt
|-- seed.sql
|-- api/
|-- attendance/
|-- config/
|-- core/
|-- migrations/
|-- recognition/
|-- registration/
|-- services/
|-- ui/
|-- tests/
`-- run_selenium_tests.ps1
```

## Quick Start

### 1. Prerequisites

- Python 3.11+
- PostgreSQL 14+
- Webcam (for registration/recognition)

### 2. Install Dependencies

Windows PowerShell:

```powershell
python -m venv .venv311
.\.venv311\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 3. Configure Environment

Create `.env` in project root:

```env
DB_HOST=localhost
DB_PORT=5432
DB_NAME=attendance_system
DB_USER=postgres
DB_PASSWORD=your_password

# Optional admin override
ADMIN_LOGIN_ID=admin
ADMIN_LOGIN_PASSWORD=admin123
```

### 4. Initialize Database

```powershell
python main.py db
```

Optional demo data:

```powershell
psql -U postgres -d attendance_system -f seed.sql
```

### 5. Run API Server

```powershell
python main.py server
```

API base URL: `http://localhost:8000`

### 6. Open UI

Open `ui/login.html` in browser.

## Login Defaults

- Student: `student_id` / same as `student_id`
- Teacher: `teacher_id` / same as `teacher_id`
- Admin: `admin` / `admin123`
- Classroom: `classroom_id` / room PIN (default `1234`)

## Common Commands

```powershell
# Run migrations
python main.py db

# Start registration terminal
python main.py register

# Start recognition for default classroom
python main.py recognize

# Start recognition for specific classroom
python main.py recognize --classroom CR-2113

# Start API server
python main.py server
```

## Main API Route Groups

- `/auth` - login, change password, reset password
- `/lecture` - classroom login, start/end, live lecture status
- `/attendance` - mark/override/list, disputes
- `/analytics` - student/teacher/admin analytics, forecasts, exports
- `/admin` - classroom and master data operations

## Teacher Manual Attendance Workflow

1. Open Teacher dashboard
2. Go to Manual Attendance (left sidebar)
3. Pick course and previous lecture
4. Select absentees or all students
5. Mark selected as present/absent and apply

## Testing

### API and Unit Tests

```powershell
.\.venv311\Scripts\python.exe -m pytest -q
```

### Selenium + HTML Report

```powershell
powershell -ExecutionPolicy Bypass -File .\run_selenium_tests.ps1
```

Generated report: `reports/selenium/report.html`

## Troubleshooting

### Port 8000 already in use

If server start fails with address already in use:

```powershell
$pid = (Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1).OwningProcess
if ($pid) { Stop-Process -Id $pid -Force }
python main.py server
```

### Recognition does not start on Windows

- Ensure camera permission is enabled
- Ensure dependencies are installed in `.venv311`
- Check `recognition_last_error.log`

## Notes

- Migrations run at API startup as well, but `python main.py db` is the recommended explicit setup step.
- Attendance write operations are idempotent for the same student+lecture.
- Dispute approval can update attendance records and audit logs.
