"""
CSV bulk import service — used by admin to seed the database.

Input is the decoded CSV text (the router enforces size and encoding).
Every row is validated in Python first, then inserted inside its own
SAVEPOINT so one bad row cannot abort the rest of the import. Imported
accounts get no usable password; an admin issues one-time passwords.
"""

from __future__ import annotations

import csv
import io
import logging
import re

from config.settings import uploads as cfg
from core.database import transaction
from core.security import is_valid_id

logger = logging.getLogger(__name__)

_DAYS = {"Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"}
_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_DEPT_RE = re.compile(r"^[A-Za-z0-9 &._\-]{1,32}$")
_EMAIL_RE = re.compile(r"^[^@\s<>\"']+@[^@\s<>\"']+\.[A-Za-z]{2,}$")


class CsvImportError(ValueError):
    """Raised for file-level problems (missing columns, too many rows)."""


class _RowError(ValueError):
    pass


def _parse(text: str, required: set[str]) -> list[dict]:
    reader = csv.DictReader(io.StringIO(text))
    headers = {h.strip() for h in (reader.fieldnames or [])}
    missing = required - headers
    if missing:
        raise CsvImportError(f"Missing column(s): {', '.join(sorted(missing))}")
    rows: list[dict] = []
    for row in reader:
        if len(rows) >= cfg.max_csv_rows:
            raise CsvImportError(f"Too many rows (max {cfg.max_csv_rows}).")
        rows.append({(k or "").strip(): (v or "").strip() for k, v in row.items() if k})
    return rows


def _id(row: dict, key: str) -> str:
    value = row.get(key, "")
    if not is_valid_id(value):
        raise _RowError(f"invalid {key}")
    return value


def _name(row: dict, key: str) -> str:
    value = " ".join(row.get(key, "").split())
    if not value or len(value) > 120:
        raise _RowError(f"invalid {key}")
    return value


def _dept(row: dict) -> str:
    value = row.get("department", "")
    if not _DEPT_RE.match(value):
        raise _RowError("invalid department")
    return value


def _email(row: dict) -> str | None:
    value = row.get("email", "")
    if not value:
        return None
    if len(value) > 254 or not _EMAIL_RE.match(value):
        raise _RowError("invalid email")
    return value


def _int(row: dict, key: str, lo: int, hi: int, default: int | None = None) -> int:
    raw = row.get(key, "")
    if raw == "" and default is not None:
        return default
    try:
        value = int(raw)
    except ValueError:
        raise _RowError(f"invalid {key}")
    if not lo <= value <= hi:
        raise _RowError(f"{key} out of range")
    return value


async def _run(rows: list[dict], build, sql: str, after=None) -> dict:
    inserted = skipped = 0
    errors: list[str] = []
    async with transaction() as conn:
        for line_no, row in enumerate(rows, start=2):
            try:
                params = build(row)
            except _RowError as exc:
                skipped += 1
                if len(errors) < 20:
                    errors.append(f"line {line_no}: {exc}")
                continue
            try:
                async with conn.transaction():          # SAVEPOINT per row
                    result = await conn.execute(sql, *params)
                    if result.endswith(" 1"):
                        inserted += 1
                        if after:
                            await after(conn, params)
                    else:
                        skipped += 1
            except Exception as exc:                     # FK / check violations
                skipped += 1
                logger.info("CSV row %d rejected: %s", line_no, type(exc).__name__)
                if len(errors) < 20:
                    errors.append(f"line {line_no}: rejected by database ({type(exc).__name__})")
    return {"inserted": inserted, "skipped": skipped, "errors": errors}


async def _create_login(role: str):
    async def _after(conn, params):
        await conn.execute(
            """
            INSERT INTO login_credentials (role, principal_id, password_hash, must_change_password)
            VALUES ($1, $2, NULL, TRUE)
            ON CONFLICT (role, principal_id) DO NOTHING
            """,
            role, params[0],
        )
    return _after


async def import_students(text: str) -> dict:
    """Columns: student_id, name, email, department, semester"""
    rows = _parse(text, {"student_id", "name", "department", "semester"})
    return await _run(
        rows,
        lambda r: (_id(r, "student_id"), _name(r, "name"), _email(r), _dept(r), _int(r, "semester", 1, 12)),
        """
        INSERT INTO students (student_id, name, email, department, semester)
        VALUES ($1, $2, $3, $4, $5)
        ON CONFLICT (student_id) DO NOTHING
        """,
        await _create_login("student"),
    )


async def import_teachers(text: str) -> dict:
    """Columns: teacher_id, name, email, department"""
    rows = _parse(text, {"teacher_id", "name", "department"})
    return await _run(
        rows,
        lambda r: (_id(r, "teacher_id"), _name(r, "name"), _email(r), _dept(r)),
        """
        INSERT INTO teachers (teacher_id, name, email, department)
        VALUES ($1, $2, $3, $4)
        ON CONFLICT (teacher_id) DO NOTHING
        """,
        await _create_login("teacher"),
    )


async def import_courses(text: str) -> dict:
    """Columns: course_id, course_name, department, semester, [credits]"""
    rows = _parse(text, {"course_id", "course_name", "department", "semester"})
    return await _run(
        rows,
        lambda r: (_id(r, "course_id"), _name(r, "course_name"), _dept(r),
                   _int(r, "semester", 1, 12), _int(r, "credits", 0, 12, default=3)),
        """
        INSERT INTO courses (course_id, course_name, department, semester, credits)
        VALUES ($1, $2, $3, $4, $5)
        ON CONFLICT (course_id) DO NOTHING
        """,
    )


def _schedule_row(r: dict) -> tuple:
    day = r.get("day_of_week", "").capitalize()
    start, end = r.get("start_time", ""), r.get("end_time", "")
    if day not in _DAYS:
        raise _RowError("invalid day_of_week")
    if not _TIME_RE.match(start) or not _TIME_RE.match(end) or end <= start:
        raise _RowError("invalid start_time/end_time (use HH:MM)")
    return (_id(r, "course_id"), _id(r, "classroom_id"), day, start, end)


async def import_schedule(text: str) -> dict:
    """Columns: course_id, classroom_id, day_of_week, start_time, end_time (HH:MM)"""
    rows = _parse(text, {"course_id", "classroom_id", "day_of_week", "start_time", "end_time"})
    return await _run(
        rows,
        _schedule_row,
        """
        INSERT INTO weekly_schedule (course_id, classroom_id, day_of_week, start_time, end_time)
        SELECT $1, $2, $3, $4::TIME, $5::TIME
        WHERE NOT EXISTS (
            SELECT 1 FROM weekly_schedule
            WHERE course_id = $1 AND classroom_id = $2 AND day_of_week = $3
              AND start_time = $4::TIME AND end_time = $5::TIME
        )
        """,
    )


async def import_course_teachers(text: str) -> dict:
    """Columns: course_id, teacher_id"""
    rows = _parse(text, {"course_id", "teacher_id"})
    return await _run(
        rows,
        lambda r: (_id(r, "course_id"), _id(r, "teacher_id")),
        """
        INSERT INTO course_teachers (course_id, teacher_id)
        VALUES ($1, $2)
        ON CONFLICT (course_id, teacher_id) DO NOTHING
        """,
    )
