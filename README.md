# Digital Attendance System

A modern, intelligent biometric attendance management platform leveraging facial recognition technology for academic institutions. This system automates attendance recording while providing real-time analytics, class management, and administrative oversight.

---

## Table of Contents

- [Overview](#overview)
- [Key Features](#key-features)
- [Technology Stack](#technology-stack)
- [System Architecture](#system-architecture)
- [Project Structure](#project-structure)
- [Installation & Setup](#installation--setup)
- [Configuration](#configuration)
- [Running the Application](#running-the-application)
- [API Endpoints](#api-endpoints)
- [Database Schema](#database-schema)
- [User Roles & Capabilities](#user-roles--capabilities)
- [Workflows](#workflows)
- [Troubleshooting](#troubleshooting)
- [License](#license)

---

## Overview

The **Digital Attendance System** is a comprehensive biometric-based solution designed to streamline attendance management in academic institutions. It replaces traditional paper-based or manual digital attendance with an automated, secure system that leverages computer vision and facial recognition technology.

The platform provides:
- **Automated attendance marking** via facial recognition from webcam captures
- **Real-time monitoring** and analytics for instructors and administrators
- **Subject-wise attendance tracking** with percentage calculations
- **Multi-layer access control** with role-based dashboards
- **Data persistence** using SQLite with structured relational schemas
- **REST API** for seamless frontend-backend communication

---

## Key Features

### 🔐 **Face Recognition & Registration**
- Biometric enrollment using facial encodings (dlib-based)
- Multi-sample capture for robust face matching
- Real-time face detection using MediaPipe
- Confidence scoring with distance-based matching
- Recognition buffer to reduce false positives (3-frame confirmation)

### 📊 **Attendance Management**
- Automated attendance marking during live sessions
- Manual attendance override capability for instructors
- Course-wise and student-wise attendance tracking
- Timestamped records for audit trails
- Attendance history and analytics per student

### 📈 **Analytics & Reporting**
- Individual student attendance percentage and statistics
- Class-level attendance summaries
- Subject-wise attendance distributions
- Real-time progress monitoring

### 🎓 **Role-Based Access Control**
- **Admin**: Institutional data management, user management, system configuration
- **Teacher/Faculty**: Course management, attendance sessions, student monitoring
- **Student**: Self-service registration, attendance marking, personal analytics

### 💻 **User Interface**
- Responsive web dashboard with HTML/CSS/JavaScript
- Role-specific views (Student, Teacher, Admin)
- Interactive charts for attendance visualization (Chart.js)
- Login authentication system

### 🔄 **API-Driven Architecture**
- FastAPI-based REST API
- CORS-enabled for cross-origin requests
- Modular, extensible design
- JSON request/response format

---

## Technology Stack

| Layer | Technology |
|-------|-----------|
| **Backend** | Python 3.10–3.12 |
| **API Framework** | FastAPI, Uvicorn |
| **Computer Vision** | OpenCV, face_recognition (dlib), MediaPipe |
| **Database** | SQLite |
| **Data Validation** | Pydantic |
| **Frontend** | HTML5, CSS3, JavaScript (ES6+) |
| **Visualization** | Chart.js |
| **Scientific Computing** | NumPy |

### Key Dependencies
- **face_recognition**: dlib-based facial encoding and matching
- **opencv-python**: Image processing and webcam capture
- **mediapipe**: Face detection and localization
- **fastapi**: Modern async web framework
- **pydantic**: Data validation and serialization
- **uvicorn**: ASGI application server

---

## System Architecture

The system follows a **layered, modular architecture**:

```
┌─────────────────────────────────────────────────────┐
│          Web Dashboard (HTML/JS/CSS)                │
│  (Student View | Teacher View | Admin Panel)        │
└──────────────────────┬──────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────┐
│      REST API (FastAPI Server on Port 8000)         │
│  (/login, /attendance/mark, /analytics/*, /students)
└──────────────────────┬──────────────────────────────┘
                       │
        ┌──────────────┼──────────────┐
        │              │              │
┌───────▼────────┐ ┌──▼─────────┐ ┌─▼────────────────┐
│ Attendance     │ │ Recognition│ │ Registration     │
│ Manager        │ │ Engine     │ │ Engine (Student) │
│ (mark/update)  │ │ (face eval)│ │ (enrollment)     │
└───────┬────────┘ └──┬─────────┘ └─┬────────────────┘
        │             │             │
        └─────────────┼─────────────┘
                      │
        ┌─────────────▼──────────────┐
        │   SQLite Database          │
        │  (users, students,         │
        │   courses, attendance)     │
        └────────────────────────────┘

        ┌─────────────────────────────┐
        │  Webcam / Camera Input      │
        │  (Face Capture)             │
        └─────────────────────────────┘
```

### Data Flow

1. **Registration**: Student captures 20 facial samples → Encodings stored in database
2. **Attendance**: Webcam feed → Face recognition → Database record → API response
3. **Analytics**: Query database → Calculate statistics → Return to dashboard
4. **Authorization**: Login credentials → User role determination → Dashboard access

---

## Project Structure

```
DigitalAttendance/
│
├── src/                                    # Core application code
│   ├── main.py                            # CLI entry point (database init, user creation)
│   ├── create_admin.py                    # Admin user creation script
│   │
│   ├── api/
│   │   ├── __init__.py
│   │   └── server.py                      # FastAPI application & endpoints
│   │
│   ├── database/
│   │   ├── __init__.py
│   │   └── database.py                    # SQLite initialization & connection management
│   │
│   ├── attendance/
│   │   ├── __init__.py
│   │   └── attendance_manager.py          # Attendance marking & record management
│   │
│   ├── recognition/
│   │   ├── __init__.py
│   │   └── recognizer_v2.py               # Face recognition engine with CV2 & dlib
│   │
│   ├── registration/
│   │   ├── __init__.py
│   │   └── register_student_v2.py         # Student enrollment with facial encoding
│   │
│   ├── services/
│   │   ├── __init__.py
│   │   ├── csv_service.py                 # CSV import/export utilities
│   │   ├── lecture_service.py             # Lecture scheduling
│   │   └── schedule_service.py            # Schedule management
│   │
│   └── utils/
│       ├── __init__.py
│       └── face_loader.py                 # Load & cache facial encodings
│
├── dashboard/                             # Web frontend
│   ├── index.html                         # Login portal
│   ├── student.html                       # Student dashboard view
│   ├── teacher.html                       # Teacher dashboard view
│   ├── admin.html                         # Administrator panel
│   │
│   ├── css/
│   │   └── style.css                      # Global styling (responsive design)
│   │
│   └── js/
│       ├── app.js                         # Main application controller
│       ├── charts.js                      # Chart.js utilities for visualization
│       ├── login.js                       # Authentication logic
│       ├── student.js                     # Student-specific interactions
│       └── teacher.js                     # Teacher-specific interactions
│
├── docs/
│   └── face_rec.md                        # Technical system specification
│
├── face_recognition/                      # Original/legacy source code
│   ├── main.py
│   ├── __pycache__/
│   ├── api/
│   ├── attendance/
│   ├── database/
│   ├── recognition/
│   ├── registration/
│   ├── services/
│   └── utils/
│
├── requirements.txt                       # Python dependencies
├── LICENSE                                # License file
└── README.md                              # This file
```

---

## Installation & Setup

### Prerequisites

- **Python 3.10, 3.11, or 3.12** (3.13+ not supported due to dlib/face_recognition)
- **Windows, macOS, or Linux** with Python environment manager support
- **Webcam** for facial registration and recognition
- **pip** or **conda** for package management

> ⚠️ **Important**: The `face-recognition` and `dlib` libraries do not yet support Python 3.13+. Ensure you use Python 3.10–3.12.

### Step 1: Clone / Extract Repository

```bash
cd DigitalAttendance
```

### Step 2: Create Virtual Environment

```bash
# Using Python 3.12 (recommended)
python -m venv venv

# Or with explicit path
"C:\...\Python312\python.exe" -m venv venv
```

### Step 3: Activate Virtual Environment

**Windows (PowerShell):**
```powershell
.\venv\Scripts\Activate.ps1
```

**Windows (CMD):**
```cmd
venv\Scripts\activate.bat
```

**macOS/Linux:**
```bash
source venv/bin/activate
```

### Step 4: Install dlib Pre-built Wheel

> ⚠️ **Critical**: Install dlib before other dependencies to avoid C++ compiler requirement.

```bash
pip install https://github.com/z-mahmud22/Dlib_Windows_Python3.x/raw/main/dlib-19.24.99-cp312-cp312-win_amd64.whl
```

### Step 5: Install Face Recognition Models

```bash
pip install git+https://github.com/ageitgey/face_recognition_models
```

### Step 6: Install Remaining Dependencies

```bash
pip install -r requirements.txt
```

### Step 7: Initialize Database

```bash
cd src
python main.py
```

Select the menu options:
- Option 1: Initialize Database
- Option 2: Create Default Teacher

### Step 8: Create Admin User

```bash
python create_admin.py
```

This will create an admin account for system administration.

### Step 9: Verify Installation

```bash
pip list
```

Ensure all packages from `requirements.txt` are installed.

---

## Configuration

### Database Configuration

The database is configured in [src/database/database.py](src/database/database.py):

```python
DB_NAME = "attendance_system.db"  # SQLite database file
```

To reset the database:
```bash
cd src
rm attendance_system.db  # or delete on Windows
python main.py  # Select "Initialize Database"
```

### Camera Configuration

In [src/recognition/recognizer_v2.py](src/recognition/recognizer_v2.py):
- Camera index: `cv2.VideoCapture(0)` (default webcam)
- Frame downscaling: 25% for faster processing
- Face detection confidence threshold: 0.45 (distance-based)
- Recognition buffer: 3-frame confirmation to reduce false positives

### API Configuration

Server runs on **http://localhost:8000** by default with uvicorn.

Enable CORS for frontend requests (already configured in [src/api/server.py](src/api/server.py)).

### Role Configuration

Default credentials (change after first login):

| Role | User ID | Password | Created By |
|------|---------|----------|-----------|
| Teacher | `teacher1` | `1234` | main.py |
| Admin | `admin1` | `1234` | create_admin.py |

---

## Running the Application

### Terminal 1: Start FastAPI Server

```bash
cd src
uvicorn api.server:app --reload
```

Output:
```
INFO:     Uvicorn running on http://127.0.0.1:8000
INFO:     Application startup complete
```

### Terminal 2: Start Web Dashboard

```bash
cd dashboard
python -m http.server 5500
```

Output:
```
Serving HTTP on 0.0.0.0 port 5500 (http://0.0.0.0:5500/) ...
```

### Terminal 3: Optional - Start Recognition Engine

```bash
cd src
python -m recognition.recognizer_v2
```

### Access the Application

Open your browser to:
```
http://localhost:5500
```

Login with default credentials based on your role.

---

## API Endpoints

All endpoints return JSON responses. Base URL: `http://localhost:8000`

### Authentication

#### `POST /login`
**Description**: Authenticate user and retrieve role information

**Request:**
```json
{
  "id": "teacher1",
  "password": "1234"
}
```

**Response (Success):**
```json
{
  "id": "teacher1",
  "name": "Teacher One",
  "role": "teacher"
}
```

**Response (Error):**
```json
{
  "error": "User not found" | "Incorrect password"
}
```

---

### Attendance Management

#### `POST /attendance/mark`
**Description**: Manually mark attendance for a student in a course

**Request:**
```json
{
  "student_id": "STU001",
  "course_id": "CS101",
  "status": "present"
}
```

**Response:**
```json
{
  "message": "Attendance marked"
}
```

**Status Values**: `present`, `absent`, `late`

---

### Analytics

#### `GET /analytics/student/{student_id}`
**Description**: Get attendance statistics for a specific student

**Response:**
```json
{
  "student_id": "STU001",
  "total_classes": 25,
  "present": 23,
  "attendance_percentage": 92.0
}
```

---

#### `GET /analytics/class/{course_id}`
**Description**: Get real-time attendance summary for a course

**Response:**
```json
{
  "course_id": "CS101",
  "present_today": 18,
  "absent_today": 7
}
```

---

### Data Retrieval

#### `GET /students`
**Description**: Retrieve list of all registered students

**Response:**
```json
[
  {
    "student_id": "STU001",
    "user_id": "user1"
  },
  {
    "student_id": "STU002",
    "user_id": "user2"
  }
]
```

---

#### `GET /`
**Description**: Health check endpoint

**Response:**
```json
{
  "message": "Attendance API running"
}
```

---

## Database Schema

### users Table
Stores system user accounts (students, teachers, admins).

| Column | Type | Constraint | Description |
|--------|------|-----------|------------|
| `id` | TEXT | PRIMARY KEY | Unique user identifier |
| `name` | TEXT | NOT NULL | User's full name |
| `role` | TEXT | NOT NULL | Role: student, teacher, admin |
| `password` | TEXT | — | User's password (plaintext in demo) |

---

### students Table
Biometric enrollment data for students.

| Column | Type | Constraint | Description |
|--------|------|-----------|------------|
| `student_id` | TEXT | PRIMARY KEY | Unique student identifier |
| `user_id` | TEXT | FK → users.id | Link to user account |
| `face_encoding` | BLOB | — | Serialized facial encoding vector |
| `department` | TEXT | — | Department/program name |
| `semester` | INTEGER | — | Current semester enrollment |

---

### courses Table
Course/subject definitions and instructor assignments.

| Column | Type | Constraint | Description |
|--------|------|-----------|------------|
| `id` | TEXT | PRIMARY KEY | Course code (e.g., CS101) |
| `course_name` | TEXT | — | Full course name |
| `teacher_id` | TEXT | — | Assigned instructor ID |

---

### attendance Table
Individual attendance records.

| Column | Type | Constraint | Description |
|--------|------|-----------|------------|
| `id` | INTEGER | PRIMARY KEY AUTOINCREMENT | Record ID |
| `student_id` | TEXT | — | Student marked (FK → students) |
| `course_id` | TEXT | — | Course attendance marked for |
| `status` | TEXT | — | `present`, `absent`, or `late` |
| `timestamp` | DATETIME | DEFAULT NOW | Record timestamp |
| `marked_by` | TEXT | — | `system` or `teacher` |

---

## User Roles & Capabilities

### 👨‍💼 Administrator
**Responsibility**: System and institutional management.

**Capabilities:**
- Create, delete, and manage user accounts
- Configure course and subject structures
- Assign teachers to courses
- Upload student data (batch import)
- Configure institutional semester structures
- View system-wide analytics and logs
- Manage system settings

**Dashboard**: [dashboard/admin.html](dashboard/admin.html)

---

### 👨‍🏫 Teacher / Faculty
**Responsibility**: Course attendance and student management.

**Capabilities:**
- Start attendance session for assigned courses
- View real-time attendance during class
- Monitor student attendance trends
- Manual attendance override (for late arrivals)
- Generate subject-wise attendance reports
- Perform student management tasks
- Export attendance data

**Dashboard**: [dashboard/teacher.html](dashboard/teacher.html)

---

### 👨‍🎓 Student
**Responsibility**: Self-service enrollment and attendance marking.

**Capabilities:**
- Register facial biometric during enrollment
- Mark attendance using facial recognition
- View personal attendance history
- Track subject-wise attendance percentage
- Receive low attendance alerts
- Download attendance transcripts

**Dashboard**: [dashboard/student.html](dashboard/student.html)

---

## Workflows

### 1. Student Enrollment Workflow

```
Student Registration
  ↓
1. Capture facial samples (20 images)
   - MediaPipe detects face location
   - Face_recognition creates encodings
  ↓
2. Encodings stored in database
   - student.face_encoding (BLOB)
  ↓
3. Enrollment complete
   - Student ready to mark attendance
```

### 2. Attendance Marking Workflow

```
Attendance Session Started
  ↓
1. Webcam captures live frame
  ↓
2. Face detection & recognition
   - Compare against known encodings
   - Confidence > 55% (distance < 0.45)
  ↓
3. Recognition buffer (3-frame confirmation)
   - Reduce false positives
  ↓
4. Attendance record created
   - student_id, course_id, status, timestamp
  ↓
5. Dashboard updated in real-time
```

### 3. Analytics Workflow

```
Dashboard loads
  ↓
1. Fetch student record from database
  ↓
2. Calculate statistics:
   - Total classes attended
   - Classes present
   - Attendance percentage
  ↓
3. Render charts (Chart.js)
  ↓
4. Display on dashboard
```

---

## Troubleshooting

### Issue: "No module named 'face_recognition'"

**Solution:**
```bash
pip install git+https://github.com/ageitgey/face_recognition_models
pip install face-recognition
```

---

### Issue: "dlib cannot be imported" or Build Errors

**Solution:**
Ensure dlib pre-built wheel is installed before other dependencies:
```bash
pip install https://github.com/z-mahmud22/Dlib_Windows_Python3.x/raw/main/dlib-19.24.99-cp312-cp312-win_amd64.whl
pip install -r requirements.txt
```

---

### Issue: "Python 3.13+ not supported"

**Solution:**
Use Python 3.10, 3.11, or 3.12. Check version:
```bash
python --version
```

---

### Issue: Webcam Not Detected

**Solution:**
1. Verify camera hardware is connected
2. Check if other application is using camera
3. Verify OpenCV can access camera:
   ```bash
   python -c "import cv2; cap = cv2.VideoCapture(0); print(cap.isOpened())"
   ```
4. Try different camera index (0, 1, 2) in recognizer_v2.py

---

### Issue: Face Recognition Not Working (Low Accuracy)

**Solution:**
- Ensure good lighting conditions
- Face should be clearly visible
- Camera resolution should be adequate (640x480 minimum)
- Increase face samples during registration (currently 20)
- Adjust confidence threshold in recognizer_v2.py (default: 0.45)

---

### Issue: Database Locked or Corrupted

**Solution:**
```bash
cd src
rm attendance_system.db
python main.py  # Reinitialize
```

---

### Issue: CORS Errors in Frontend

**Solution:**
Ensure FastAPI server is running and CORS middleware is enabled:
```python
# In src/api/server.py
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

---

### Issue: API Server Not Responding

**Solution:**
1. Verify server is running: `http://localhost:8000`
2. Check port 8000 is not in use:
   ```bash
   netstat -an | findstr :8000  # Windows
   lsof -i :8000                 # macOS/Linux
   ```
3. Run server explicitly:
   ```bash
   cd src
   uvicorn api.server:app --reload --host 0.0.0.0 --port 8000
   ```

---

## Security Considerations

> ⚠️ **Note**: This is a demonstration/educational system. For production use, implement:
- Password hashing (bcrypt, argon2)
- JWT token-based authentication
- HTTPS/TLS encryption
- Role-based access control (RBAC) on API
- Input validation and sanitization
- Database encryption
- Audit logging
- Rate limiting

---

## Future Enhancements

- [ ] Multi-camera support for distributed campuses
- [ ] Deep learning-based face detection (YOLO)
- [ ] Automated SMS/email attendance notifications
- [ ] Mobile app integration
- [ ] Biometric liveness detection (anti-spoofing)
- [ ] Scheduled automated attendance
- [ ] Advanced analytics and predictive modeling
- [ ] Integration with student information system (SIS)
- [ ] Docker containerization
- [ ] CI/CD pipeline

---

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE) file for details.

---

## Support & Contribution

For issues, feature requests, or contributions, please refer to the [docs](docs/face_rec.md) for technical specifications.

## Tech Stack

- **Backend**: Python, FastAPI, SQLite
- **Frontend**: HTML, CSS, JavaScript, Chart.js
- **Computer Vision**: OpenCV, face_recognition, dlib, MediaPipe

## License

See [LICENSE](LICENSE) for details.
