# Digital Attendance System

Smart biometric attendance platform using facial recognition, designed for academic institutions.

## Project Structure

```
DigitalAttendance/
├── src/                  # Python backend
│   ├── main.py           # CLI entry point
│   ├── api/              # FastAPI REST server
│   ├── attendance/       # Attendance logic
│   ├── database/         # SQLite database layer
│   ├── recognition/      # Face recognition engine
│   ├── registration/     # Student registration
│   └── utils/            # Face loader utilities
├── dashboard/            # Web frontend
│   ├── index.html        # Login page
│   ├── student.html      # Student dashboard
│   ├── teacher.html      # Teacher dashboard
│   ├── admin.html        # Admin panel
│   ├── css/style.css     # Design system
│   └── js/               # JavaScript modules
├── docs/                 # Documentation
│   └── face_rec.md       # System specification
├── requirements.txt      # Python dependencies
└── face_recognition/     # Legacy source (original)
```

## Setup

> **Requires Python 3.10–3.12.** The `face-recognition` / `dlib` libraries do not support Python 3.13+ yet.

1. **Create a virtual environment** (using Python 3.12)
   ```
   # Use the full path to your Python 3.12 installation
   "C:\...\Python312\python.exe" -m venv venv
   ```

2. **Activate the virtual environment**
   ```
   # PowerShell
   .\venv\Scripts\Activate.ps1

   # CMD
   venv\Scripts\activate.bat
   ```

3. **Install dlib** (pre-built wheel — avoids needing C++ compiler)
   ```
   pip install https://github.com/z-mahmud22/Dlib_Windows_Python3.x/raw/main/dlib-19.24.99-cp312-cp312-win_amd64.whl
   ```

4. **Install face recognition models**
   ```
   pip install git+https://github.com/ageitgey/face_recognition_models
   ```

5. **Install remaining dependencies**
   ```
   pip install -r requirements.txt
   ```

6. **Initialize database**
   ```
   cd src
   python main.py
   # Select option 1 — Initialize Database
   # Select option 2 — Create Default Teacher
   ```

   **Create an admin user** (run from `src/`):
   ```
   python create_admin.py
   ```

   **Default credentials:**

   | Role | User ID | Password |
   |------|---------|----------|
   | Teacher | `teacher1` | `1234` |
   | Admin | `admin1` | `1234` |

7. **Start the API server**
   ```
   cd src
   uvicorn api.server:app --reload
   ```

8. **Run the dashboard**
   ```
   cd dashboard
   python -m http.server 5500
   ```

9. **Open browser**
   ```
   http://localhost:5500
   ```

## Tech Stack

- **Backend**: Python, FastAPI, SQLite
- **Frontend**: HTML, CSS, JavaScript, Chart.js
- **Computer Vision**: OpenCV, face_recognition, dlib, MediaPipe

## License

See [LICENSE](LICENSE) for details.
