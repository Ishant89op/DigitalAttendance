# AttendX

**Face-recognition attendance that marks itself — with security built in, not bolted on.**

Students walk into class and look at the camera. AttendX recognises enrolled students in real time
(InsightFace, 512‑D embeddings, liveness checks), marks them present, and gives every role a focused
dashboard: students see whether they can afford to skip a lecture, faculty run sessions and fix
mistakes, admins manage the institution — and every action lands in an append-only audit log.

![stack](https://img.shields.io/badge/FastAPI-PostgreSQL-4f46e5) ![tests](https://img.shields.io/badge/security%20tests-43%20passing-15803d) ![python](https://img.shields.io/badge/python-3.11+-0369a1)

---

## What it does

| Role | Highlights |
|---|---|
| **Student** | Overall & per-subject attendance, **skip budget** ("you can miss 2 more" / "attend the next 3 to reach 75 %"), trend-based risk forecast, full present/absent history, disputes with PDF evidence |
| **Faculty** | Course dashboards, live session console (present / not-yet-seen, one-click corrections), bulk corrections for past lectures, dispute queue, Excel/PDF exports with date ranges |
| **Admin** | Institution overview + **security posture panel**, people management with one-time passwords, classrooms / device PINs / schedule / assignments, CSV import with per-row validation, risk forecast & weekly defaulter reminders, filtered exports, audit log |
| **Classroom device** | Kiosk view: upcoming lectures, one-tap start, live ring of present/enrolled, "just marked" feed |

### Recognition pipeline

1. **Detect & embed** — InsightFace `buffalo_l` produces a 512‑D embedding per face.
2. **Match** — cosine similarity against *only the students enrolled in the running course*, with a strict
   threshold **and** a winner-vs-runner-up margin, so look-alikes are not confused.
3. **Liveness** — motion, scale and landmark-geometry change plus **blink detection (EAR)** before a
   student can be marked; photos and phone screens fail.
4. **Confirm** — 3 consecutive confident frames, then a cooldown; duplicates are idempotent in SQL.
5. **Register safely** — 20-sample capture, consistency check, and **duplicate-face blocking** (one person
   cannot enrol under two IDs to give proxy attendance).

---

## Security

This version is a hardening of the original project, where login only echoed a role back and every
endpoint trusted the `student_id` / `teacher_id` sent by the browser. The full threat model is in
[SECURITY.md](SECURITY.md). In short:

- **Server-side sessions** — 256-bit random token in an `HttpOnly; SameSite=Strict` cookie; only its
  SHA‑256 digest is stored. Idle (30 min) + absolute (12 h) expiry, revocation on logout/password change,
  max 5 concurrent sessions per account.
- **CSRF** — every state-changing request needs `X-CSRF-Token`, an HMAC of the session token.
- **Authorization on every route** — role checks plus ownership checks (own record, own course, own
  classroom). A teacher cannot see or edit another teacher's lecture; a classroom device can only operate
  its own room; students only ever see themselves. Identity always comes from the session, never the body.
- **Passwords** — scrypt (N=2¹⁵, r=8, 32 MiB per guess), per-hash salt, constant-time verify,
  transparent upgrade of legacy unsalted SHA‑256, strength policy, no default passwords anywhere.
  Accounts start with **no password**; admins issue 72-hour one-time passwords that must be changed.
- **Brute-force protection** — per-account lockout with exponential back-off, per-IP rate limits,
  identical errors and timing for "no such user" vs "wrong password".
- **Biometric privacy** — face templates encrypted at rest with **AES‑256‑GCM**, bound to the student ID
  as associated data (a template copied onto another student fails to decrypt). Admins can erase a template.
- **Uploads** — evidence PDFs are size-capped, checked for JavaScript / launch actions / embedded files
  (including inside compressed object streams and hex-escaped names), stored outside the web root under
  random names, served only to the owner, the course's teacher or an admin, with a `sandbox` CSP.
- **Browser hardening** — strict CSP (`script-src 'self'`, no inline script or style), `X-Frame-Options: DENY`,
  `nosniff`, `no-referrer`, COOP/CORP, Permissions-Policy, `no-store` on API responses, Host allow-list
  (DNS-rebinding defence). All rendered data goes through an escape-by-default template helper.
- **Data integrity** — attendance can only be written for students enrolled in that lecture's course;
  dispute approval and its attendance change happen in one transaction; spreadsheet-formula injection is
  neutralised in exports; generic error messages (no stack traces or SQL in responses).

`tests/test_security.py` turns each of these into an attack that must fail — **43 tests, all passing**.

---

## Quick start

**Requirements:** Python 3.11+, PostgreSQL 13+, a webcam for recognition.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env          # set DB_* (and optionally ADMIN_LOGIN_PASSWORD)

python main.py db               # create schema, bootstrap the admin account
psql -U postgres -d attendance_system -f seed.sql      # optional sample institution
python scripts/demo_history.py --weeks 5               # optional: realistic past attendance for demos
python main.py server           # → http://localhost:8000
```

**First sign-in:** choose *Admin*, ID `admin`, and the one-time password from
`instance/initial_admin_password.txt` (or your `ADMIN_LOGIN_PASSWORD`). You'll be asked to set a new one.
Then, in **People**, issue one-time passwords to faculty/students, and in **Academics** set a device PIN
for each classroom.

**Register a face** (on the camera PC): `python main.py register`
**Run recognition manually:** `python main.py recognize --classroom CR-2113` (normally started for you when a
teacher or the classroom device presses *Start attendance*).

### CLI

| Command | Purpose |
|---|---|
| `python main.py server` | API + web UI |
| `python main.py db` | Migrations (idempotent; also run at server start) |
| `python main.py register` | Face registration terminal |
| `python main.py recognize --classroom ID` | Recognition engine for one room |
| `python main.py set-password --role admin --id admin` | Local account recovery (prompts securely) |
| `python main.py encrypt-faces` | Encrypt any legacy plaintext face templates |

### Tests

```powershell
$env:DB_PASSWORD="..."      # any Postgres you can CREATE DATABASE on
python -m pytest -q          # creates and drops a throwaway attendx_test_* database
```

---

## Architecture

```
ui/  (vanilla JS, served same-origin)          recognition/  camera loop, liveness, matching
  core.js  safe templating, API client, shell   registration/ 20-sample capture, duplicate check
  login · student · teacher · admin · classroom
        │  HttpOnly session cookie + X-CSRF-Token
        ▼
api/server.py   TrustedHost → security headers → body cap → rate limit
api/routers/    auth · lecture · attendance · analytics · admin
core/           auth.py (sessions, RBAC, ownership) · security.py (scrypt, AES-GCM, CSRF)
services/       analytics (SQL aggregations) · disputes · CSV import · exports · schedule
migrations/     idempotent schema + one-time security upgrades
        ▼
PostgreSQL      sessions · credentials · attendance (UNIQUE per student+lecture) · audit_log
```

All aggregation happens in PostgreSQL with indexes on attendance `(student_id)`, `(lecture_id)`,
`(timestamp)`, lectures `(course_id, status)` and `(classroom_id, status)`.

### Upgrading from v2

Run the server once (or `python main.py db`). The migration automatically:
disables the old guessable defaults (password = own ID, `admin/admin123`, PIN `1234`), hashes strong
legacy PINs and drops the plaintext column, encrypts plaintext face templates, and creates an admin
account if none is usable. Then issue one-time passwords to users from **People**.

---

Built at IIIT Vadodara · contributors: [@KavyaSharma1806](https://github.com/KavyaSharma1806), [@ShreyashChaurasia](https://github.com/ShreyashChaurasia), [@Ishant89op](https://github.com/Ishant89op)
