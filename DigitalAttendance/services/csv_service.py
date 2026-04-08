"""
CSV bulk import service — used by admin to seed the database.

Accepts file paths (saved from UploadFile to a temp location).
All imports are transactional: either all rows succeed or none do.
"""

import csv
import logging
from pathlib import Path

from core.database import transaction

logger = logging.getLogger(__name__)


async def import_students(file_path: str) -> dict:
    """
    Expected CSV columns:
        student_id, name, email, department, semester
    """
    inserted, skipped = 0, 0
    rows = _read_csv(file_path)

    async with transaction() as conn:
        for row in rows:
            try:
                await conn.execute(
                    """
                    INSERT INTO students (student_id, name, email, department, semester)
                    VALUES ($1, $2, $3, $4, $5)
                    ON CONFLICT (student_id) DO NOTHING
                    """,
                    row["student_id"].strip(),
                    row["name"].strip(),
                    row.get("email", "").strip() or None,
                    row["department"].strip(),
                    int(row["semester"]),
                )
                inserted += 1
            except Exception as e:
                logger.warning("Skipped student row %s: %s", row, e)
                skipped += 1

    logger.info("Students import: %d inserted, %d skipped.", inserted, skipped)
    return {"inserted": inserted, "skipped": skipped}


async def import_teachers(file_path: str) -> dict:
    """
    Expected CSV columns:
        teacher_id, name, email, department
    """
    inserted, skipped = 0, 0
    rows = _read_csv(file_path)

    async with transaction() as conn:
        for row in rows:
            try:
                await conn.execute(
                    """
                    INSERT INTO teachers (teacher_id, name, email, department)
                    VALUES ($1, $2, $3, $4)
                    ON CONFLICT (teacher_id) DO NOTHING
                    """,
                    row["teacher_id"].strip(),
                    row["name"].strip(),
                    row.get("email", "").strip() or None,
                    row["department"].strip(),
                )
                inserted += 1
            except Exception as e:
                logger.warning("Skipped teacher row %s: %s", row, e)
                skipped += 1

    return {"inserted": inserted, "skipped": skipped}


async def import_courses(file_path: str) -> dict:
    """
    Expected CSV columns:
        course_id, course_name, department, semester, [credits]
    """
    inserted, skipped = 0, 0
    rows = _read_csv(file_path)

    async with transaction() as conn:
        for row in rows:
            try:
                await conn.execute(
                    """
                    INSERT INTO courses (course_id, course_name, department, semester, credits)
                    VALUES ($1, $2, $3, $4, $5)
                    ON CONFLICT (course_id) DO NOTHING
                    """,
                    row["course_id"].strip(),
                    row["course_name"].strip(),
                    row["department"].strip(),
                    int(row["semester"]),
                    int(row.get("credits", 3)),
                )
                inserted += 1
            except Exception as e:
                logger.warning("Skipped course row %s: %s", row, e)
                skipped += 1

    return {"inserted": inserted, "skipped": skipped}


async def import_schedule(file_path: str) -> dict:
    """
    Expected CSV columns:
        course_id, classroom_id, day_of_week, start_time, end_time

    start_time / end_time in HH:MM format (e.g. 09:00, 10:30)
    day_of_week must match: Monday/Tuesday/.../Sunday
    """
    inserted, skipped = 0, 0
    rows = _read_csv(file_path)

    async with transaction() as conn:
        for row in rows:
            try:
                await conn.execute(
                    """
                    INSERT INTO weekly_schedule
                        (course_id, classroom_id, day_of_week, start_time, end_time)
                    VALUES ($1, $2, $3, $4::TIME, $5::TIME)
                    """,
                    row["course_id"].strip(),
                    row["classroom_id"].strip(),
                    row["day_of_week"].strip(),
                    row["start_time"].strip(),
                    row["end_time"].strip(),
                )
                inserted += 1
            except Exception as e:
                logger.warning("Skipped schedule row %s: %s", row, e)
                skipped += 1

    return {"inserted": inserted, "skipped": skipped}


async def import_course_teachers(file_path: str) -> dict:
    """
    Expected CSV columns:
        course_id, teacher_id
    """
    inserted, skipped = 0, 0
    rows = _read_csv(file_path)

    async with transaction() as conn:
        for row in rows:
            try:
                await conn.execute(
                    """
                    INSERT INTO course_teachers (course_id, teacher_id)
                    VALUES ($1, $2)
                    ON CONFLICT (course_id, teacher_id) DO NOTHING
                    """,
                    row["course_id"].strip(),
                    row["teacher_id"].strip(),
                )
                inserted += 1
            except Exception as e:
                logger.warning("Skipped course_teacher row %s: %s", row, e)
                skipped += 1

    return {"inserted": inserted, "skipped": skipped}


# ─────────────────────────────────────────────
# HELPER
# ─────────────────────────────────────────────

def _read_csv(file_path: str) -> list[dict]:
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"CSV file not found: {file_path}")
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))
