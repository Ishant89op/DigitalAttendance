"""
Analytics service — all read-heavy reporting queries.

Designed for low latency:
  - All aggregations happen in PostgreSQL (not Python).
  - Indexes on attendance(student_id), attendance(lecture_id), attendance(timestamp)
    make these fast even on large datasets.
"""

import logging
from datetime import datetime, timezone

from core.database import get_conn
from config.settings import analytics as cfg

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# STUDENT ANALYTICS
# ─────────────────────────────────────────────

async def get_student_summary(student_id: str) -> dict:
    """
    Full attendance summary for a student across all their subjects.

    Returns overall percentage + per-subject breakdown + alert flags.
    """
    async with get_conn() as conn:

        # --- per-subject stats ---
        rows = await conn.fetch(
            """
            SELECT
                c.course_id,
                c.course_name,
                COUNT(DISTINCT ls.lecture_id)                      AS total_lectures,
                COUNT(DISTINCT a.lecture_id)                       AS attended,
                ROUND(
                    COUNT(DISTINCT a.lecture_id)::NUMERIC
                    / NULLIF(COUNT(DISTINCT ls.lecture_id), 0) * 100,
                    2
                )                                                  AS percentage
            FROM   courses c
            JOIN   students s ON s.department = c.department
                              AND s.semester  = c.semester
            LEFT   JOIN lecture_sessions ls ON ls.course_id = c.course_id
                                           AND ls.status    = 'closed'
            LEFT   JOIN attendance a ON a.lecture_id = ls.lecture_id
                                    AND a.student_id  = $1
            WHERE  s.student_id = $1
            GROUP  BY c.course_id, c.course_name
            ORDER  BY c.course_name
            """,
            student_id,
        )

        # --- overall stats ---
        overall = await conn.fetchrow(
            """
            SELECT
                COUNT(DISTINCT ls.lecture_id)     AS total_lectures,
                COUNT(DISTINCT a.lecture_id)       AS total_attended
            FROM   courses c
            JOIN   students s ON s.department = c.department
                              AND s.semester  = c.semester
            LEFT   JOIN lecture_sessions ls ON ls.course_id = c.course_id
                                           AND ls.status    = 'closed'
            LEFT   JOIN attendance a ON a.lecture_id = ls.lecture_id
                                    AND a.student_id  = $1
            WHERE  s.student_id = $1
            """,
            student_id,
        )

    subjects = []
    for r in rows:
        pct = float(r["percentage"] or 0)
        subjects.append({
            "course_id":       r["course_id"],
            "course_name":     r["course_name"],
            "total_lectures":  r["total_lectures"],
            "attended":        r["attended"],
            "percentage":      pct,
            "status": (
                "critical" if pct < cfg.critical_threshold
                else "warning" if pct < cfg.low_attendance_threshold
                else "good"
            ),
        })

    total     = overall["total_lectures"] or 0
    attended  = overall["total_attended"] or 0
    overall_pct = round(attended / total * 100, 2) if total else 0.0

    return {
        "student_id":       student_id,
        "overall_percentage": overall_pct,
        "total_lectures":   total,
        "total_attended":   attended,
        "alert": overall_pct < cfg.low_attendance_threshold,
        "subjects":         subjects,
    }


async def get_student_history(
    student_id: str,
    course_id: str | None = None,
    limit: int = 50,
) -> list[dict]:
    """Recent attendance history for a student, optionally filtered by course."""
    async with get_conn() as conn:
        rows = await conn.fetch(
            """
            SELECT
                a.timestamp,
                a.source,
                ls.course_id,
                c.course_name,
                ls.classroom_id
            FROM   attendance a
            JOIN   lecture_sessions ls ON ls.lecture_id = a.lecture_id
            JOIN   courses c ON c.course_id = ls.course_id
            WHERE  a.student_id = $1
              AND  ($2::TEXT IS NULL OR ls.course_id = $2)
            ORDER  BY a.timestamp DESC
            LIMIT  $3
            """,
            student_id, course_id, limit,
        )
    return [dict(r) for r in rows]


# ─────────────────────────────────────────────
# TEACHER ANALYTICS
# ─────────────────────────────────────────────

async def get_live_lecture_attendance(lecture_id: int) -> dict:
    """
    Real-time attendance snapshot for an active lecture.
    Designed to be polled frequently — index-backed, fast.
    """
    async with get_conn() as conn:
        lecture = await conn.fetchrow(
            """
            SELECT ls.lecture_id, ls.course_id, c.course_name,
                   ls.classroom_id, ls.start_time,
                   COUNT(a.id) AS present_count
            FROM   lecture_sessions ls
            JOIN   courses c ON c.course_id = ls.course_id
            LEFT   JOIN attendance a ON a.lecture_id = ls.lecture_id
            WHERE  ls.lecture_id = $1
            GROUP  BY ls.lecture_id, c.course_name
            """,
            lecture_id,
        )
        if not lecture:
            return {}

        # enrolled = students in same dept + semester as this course
        enrolled = await conn.fetchval(
            """
            SELECT COUNT(*) FROM students s
            JOIN   courses c ON c.department = s.department
                             AND c.semester   = s.semester
            WHERE  c.course_id = $1
            """,
            lecture["course_id"],
        )

        absent_rows = await conn.fetch(
            """
            SELECT s.student_id, s.name
            FROM   students s
            JOIN   courses c ON c.department = s.department
                             AND c.semester   = s.semester
            WHERE  c.course_id = $1
              AND  s.student_id NOT IN (
                  SELECT student_id FROM attendance
                  WHERE  lecture_id = $2
              )
            ORDER  BY s.name
            """,
            lecture["course_id"], lecture_id,
        )

    present = int(lecture["present_count"])
    total   = int(enrolled or 0)

    return {
        "lecture_id":     lecture_id,
        "course_id":      lecture["course_id"],
        "course_name":    lecture["course_name"],
        "classroom_id":   lecture["classroom_id"],
        "start_time":     lecture["start_time"],
        "enrolled":       total,
        "present":        present,
        "absent":         total - present,
        "percentage":     round(present / total * 100, 2) if total else 0.0,
        "absent_students": [dict(r) for r in absent_rows],
    }


async def get_teacher_course_stats(teacher_id: str) -> list[dict]:
    """Per-course attendance averages for all courses taught by this teacher."""
    async with get_conn() as conn:
        rows = await conn.fetch(
            """
            SELECT
                c.course_id,
                c.course_name,
                COUNT(DISTINCT ls.lecture_id)          AS total_lectures,
                ROUND(AVG(lecture_pct.pct), 2)         AS avg_attendance_pct
            FROM   course_teachers ct
            JOIN   courses c ON c.course_id = ct.course_id
            LEFT   JOIN lecture_sessions ls ON ls.course_id = c.course_id
                                           AND ls.status    = 'closed'
            LEFT   JOIN LATERAL (
                SELECT
                    ls2.lecture_id,
                    COUNT(a.id)::NUMERIC
                    / NULLIF(
                        (SELECT COUNT(*) FROM students s2
                         JOIN courses c2 ON c2.department = s2.department
                                        AND c2.semester   = s2.semester
                         WHERE c2.course_id = ls2.course_id), 0
                    ) * 100 AS pct
                FROM lecture_sessions ls2
                LEFT JOIN attendance a ON a.lecture_id = ls2.lecture_id
                WHERE ls2.lecture_id = ls.lecture_id
                GROUP BY ls2.lecture_id, ls2.course_id
            ) lecture_pct ON TRUE
            WHERE  ct.teacher_id = $1
            GROUP  BY c.course_id, c.course_name
            ORDER  BY c.course_name
            """,
            teacher_id,
        )
    return [dict(r) for r in rows]


async def get_teacher_dashboard(teacher_id: str) -> dict:
    """Teacher-facing overview across assigned courses."""
    async with get_conn() as conn:
        rows = await conn.fetch(
            """
            WITH taught_courses AS (
                SELECT DISTINCT
                    c.course_id,
                    c.course_name,
                    c.department,
                    c.semester,
                    c.credits
                FROM course_teachers ct
                JOIN courses c ON c.course_id = ct.course_id
                WHERE ct.teacher_id = $1
            ),
            enrolled AS (
                SELECT
                    tc.course_id,
                    COUNT(s.student_id) AS total_students
                FROM taught_courses tc
                LEFT JOIN students s
                       ON s.department = tc.department
                      AND s.semester = tc.semester
                GROUP BY tc.course_id
            ),
            lecture_pct AS (
                SELECT
                    ls.course_id,
                    ls.lecture_id,
                    ls.classroom_id,
                    ls.status,
                    ls.start_time,
                    ls.end_time,
                    COUNT(a.id) AS present_count
                FROM lecture_sessions ls
                LEFT JOIN attendance a ON a.lecture_id = ls.lecture_id
                GROUP BY ls.course_id, ls.lecture_id, ls.classroom_id, ls.status, ls.start_time, ls.end_time
            ),
            latest_today AS (
                SELECT DISTINCT ON (ls.course_id)
                    ls.course_id,
                    ls.lecture_id,
                    ls.classroom_id,
                    ls.status,
                    ls.start_time,
                    ls.end_time
                FROM lecture_sessions ls
                WHERE ls.start_time::DATE = CURRENT_DATE
                ORDER BY ls.course_id, ls.start_time DESC, ls.lecture_id DESC
            )
            SELECT
                tc.course_id,
                tc.course_name,
                tc.department,
                tc.semester,
                tc.credits,
                COALESCE(e.total_students, 0) AS total_students,
                COUNT(DISTINCT lp.lecture_id) FILTER (WHERE lp.status = 'closed') AS total_lectures,
                COALESCE(
                    ROUND(
                        AVG(
                            CASE
                                WHEN COALESCE(e.total_students, 0) = 0 OR lp.status <> 'closed' THEN NULL
                                ELSE lp.present_count::NUMERIC / e.total_students * 100
                            END
                        ),
                        2
                    ),
                    0
                ) AS avg_attendance_pct,
                MAX(lp.start_time) FILTER (WHERE lp.status = 'closed') AS last_lecture_at,
                lt.lecture_id AS today_lecture_id,
                lt.classroom_id AS today_classroom_id,
                lt.status AS today_status,
                lt.start_time AS today_start_time,
                lt.end_time AS today_end_time,
                (
                    SELECT STRING_AGG(t.name, ', ' ORDER BY t.name)
                    FROM course_teachers ct2
                    JOIN teachers t ON t.teacher_id = ct2.teacher_id
                    WHERE ct2.course_id = tc.course_id
                ) AS teacher_names
            FROM taught_courses tc
            LEFT JOIN enrolled e ON e.course_id = tc.course_id
            LEFT JOIN lecture_pct lp ON lp.course_id = tc.course_id
            LEFT JOIN latest_today lt ON lt.course_id = tc.course_id
            GROUP BY
                tc.course_id,
                tc.course_name,
                tc.department,
                tc.semester,
                tc.credits,
                e.total_students,
                lt.lecture_id,
                lt.classroom_id,
                lt.status,
                lt.start_time,
                lt.end_time
            ORDER BY tc.course_name
            """,
            teacher_id,
        )

    courses = []
    for row in rows:
        course = dict(row)
        course["avg_attendance_pct"] = float(course["avg_attendance_pct"] or 0)
        courses.append(course)

    total_courses = len(courses)
    total_students = sum(int(course["total_students"] or 0) for course in courses)
    total_lectures = sum(int(course["total_lectures"] or 0) for course in courses)
    avg_attendance = round(
        sum(course["avg_attendance_pct"] for course in courses) / total_courses, 2
    ) if total_courses else 0.0

    return {
        "teacher_id": teacher_id,
        "summary": {
            "total_courses": total_courses,
            "total_students": total_students,
            "total_lectures": total_lectures,
            "avg_attendance_pct": avg_attendance,
        },
        "courses": courses,
    }


async def get_teacher_course_detail(teacher_id: str, course_id: str) -> dict | None:
    """Full student-level attendance detail for one teacher course."""
    async with get_conn() as conn:
        course = await conn.fetchrow(
            """
            SELECT
                c.course_id,
                c.course_name,
                c.department,
                c.semester,
                c.credits,
                (
                    SELECT STRING_AGG(t.name, ', ' ORDER BY t.name)
                    FROM course_teachers ct2
                    JOIN teachers t ON t.teacher_id = ct2.teacher_id
                    WHERE ct2.course_id = c.course_id
                ) AS teacher_names
            FROM course_teachers ct
            JOIN courses c ON c.course_id = ct.course_id
            WHERE ct.teacher_id = $1
              AND c.course_id = $2
            GROUP BY c.course_id, c.course_name, c.department, c.semester, c.credits
            """,
            teacher_id,
            course_id,
        )
        if not course:
            return None

        total_students = await conn.fetchval(
            """
            SELECT COUNT(*)
            FROM students s
            WHERE s.department = $1
              AND s.semester = $2
            """,
            course["department"],
            course["semester"],
        )

        students = await conn.fetch(
            """
            SELECT
                s.student_id,
                s.name,
                s.email,
                s.department,
                s.semester,
                (s.face_encoding IS NOT NULL) AS face_registered,
                COUNT(DISTINCT ls.lecture_id) AS total_lectures,
                COUNT(DISTINCT a.lecture_id) AS attended,
                COALESCE(
                    ROUND(
                        COUNT(DISTINCT a.lecture_id)::NUMERIC
                        / NULLIF(COUNT(DISTINCT ls.lecture_id), 0) * 100,
                        2
                    ),
                    0
                ) AS percentage,
                MAX(a.timestamp) AS last_present_at
            FROM students s
            LEFT JOIN lecture_sessions ls
                   ON ls.course_id = $1
                  AND ls.status = 'closed'
            LEFT JOIN attendance a
                   ON a.lecture_id = ls.lecture_id
                  AND a.student_id = s.student_id
            WHERE s.department = $2
              AND s.semester = $3
            GROUP BY s.student_id, s.name, s.email, s.department, s.semester, s.face_encoding
            ORDER BY s.name
            """,
            course_id,
            course["department"],
            course["semester"],
        )

        lectures = await conn.fetch(
            """
            WITH enrolled AS (
                SELECT COUNT(*) AS total_students
                FROM students s
                WHERE s.department = $1
                  AND s.semester = $2
            )
            SELECT
                ls.lecture_id,
                ls.classroom_id,
                ls.teacher_id,
                ls.status,
                ls.start_time,
                ls.end_time,
                COUNT(a.id) AS present_count,
                COALESCE(
                    ROUND(
                        COUNT(a.id)::NUMERIC
                        / NULLIF((SELECT total_students FROM enrolled), 0) * 100,
                        2
                    ),
                    0
                ) AS percentage
            FROM lecture_sessions ls
            LEFT JOIN attendance a ON a.lecture_id = ls.lecture_id
            WHERE ls.course_id = $3
            GROUP BY ls.lecture_id
            ORDER BY ls.start_time DESC, ls.lecture_id DESC
            LIMIT 20
            """,
            course["department"],
            course["semester"],
            course_id,
        )

    total_lectures = max((int(row["total_lectures"] or 0) for row in students), default=0)
    avg_attendance_pct = round(
        sum(float(row["percentage"] or 0) for row in students) / len(students), 2
    ) if students else 0.0

    course_data = dict(course)
    course_data.update({
        "total_students": int(total_students or 0),
        "total_lectures": total_lectures,
        "avg_attendance_pct": avg_attendance_pct,
    })

    return {
        "teacher_id": teacher_id,
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "course": course_data,
        "students": [dict(row) for row in students],
        "recent_lectures": [dict(row) for row in lectures],
    }


# ─────────────────────────────────────────────
# ADMIN ANALYTICS
# ─────────────────────────────────────────────

async def get_admin_dashboard() -> dict:
    """System-wide overview for the admin dashboard."""
    async with get_conn() as conn:

        totals = await conn.fetchrow(
            """
            SELECT
                (SELECT COUNT(*) FROM students)          AS total_students,
                (SELECT COUNT(*) FROM teachers)          AS total_teachers,
                (SELECT COUNT(*) FROM courses)           AS total_courses,
                (SELECT COUNT(*) FROM lecture_sessions
                 WHERE status = 'active')                AS active_lectures,
                (SELECT COUNT(*) FROM attendance
                 WHERE timestamp::DATE = CURRENT_DATE)  AS today_attendance
            """
        )

        # daily trend — last 30 days
        daily_trend = await conn.fetch(
            """
            SELECT
                timestamp::DATE              AS day,
                COUNT(*)                     AS count
            FROM   attendance
            WHERE  timestamp >= NOW() - INTERVAL '30 days'
            GROUP  BY day
            ORDER  BY day
            """
        )

        # departments attendance average
        dept_stats = await conn.fetch(
            """
            SELECT
                s.department,
                COUNT(DISTINCT s.student_id)                AS students,
                ROUND(
                    COUNT(DISTINCT a.id)::NUMERIC
                    / NULLIF(
                        COUNT(DISTINCT s.student_id)
                        * NULLIF(
                            (SELECT COUNT(*) FROM lecture_sessions ls2
                             JOIN courses c2 ON c2.course_id = ls2.course_id
                             WHERE c2.department = s.department
                               AND ls2.status = 'closed'), 0
                        ), 0
                    ) * 100, 2
                )                                           AS avg_pct
            FROM   students s
            LEFT   JOIN courses c ON c.department = s.department
                                  AND c.semester   = s.semester
            LEFT   JOIN lecture_sessions ls ON ls.course_id = c.course_id
                                           AND ls.status    = 'closed'
            LEFT   JOIN attendance a ON a.lecture_id = ls.lecture_id
                                    AND a.student_id  = s.student_id
            GROUP  BY s.department
            ORDER  BY s.department
            """
        )

        # low attendance students (below threshold)
        low_att = await conn.fetch(
            """
            SELECT
                s.student_id,
                s.name,
                s.department,
                s.semester,
                ROUND(
                    COUNT(DISTINCT a.lecture_id)::NUMERIC
                    / NULLIF(COUNT(DISTINCT ls.lecture_id), 0) * 100, 2
                ) AS percentage
            FROM   students s
            JOIN   courses c ON c.department = s.department
                             AND c.semester   = s.semester
            LEFT   JOIN lecture_sessions ls ON ls.course_id = c.course_id
                                           AND ls.status    = 'closed'
            LEFT   JOIN attendance a ON a.lecture_id = ls.lecture_id
                                    AND a.student_id  = s.student_id
            GROUP  BY s.student_id, s.name, s.department, s.semester
            HAVING ROUND(
                COUNT(DISTINCT a.lecture_id)::NUMERIC
                / NULLIF(COUNT(DISTINCT ls.lecture_id), 0) * 100, 2
            ) < $1
            ORDER  BY percentage ASC
            LIMIT  50
            """,
            cfg.low_attendance_threshold,
        )

    by_department = [dict(r) for r in dept_stats]

    return {
        "totals": dict(totals),
        "daily_trend": [{"day": str(r["day"]), "count": r["count"]}
                        for r in daily_trend],
        "by_department": by_department,
        "department_stats": by_department,
        "low_attendance_students": [dict(r) for r in low_att],
        "thresholds": {
            "warning":  cfg.low_attendance_threshold,
            "critical": cfg.critical_threshold,
        },
    }


async def get_low_attendance_alerts() -> list[dict]:
    """
    Return students with attendance below the warning threshold.
    Broken down per subject.
    """
    async with get_conn() as conn:
        rows = await conn.fetch(
            """
            SELECT
                s.student_id,
                s.name,
                s.department,
                c.course_id,
                c.course_name,
                COUNT(DISTINCT ls.lecture_id)            AS total,
                COUNT(DISTINCT a.lecture_id)             AS attended,
                ROUND(
                    COUNT(DISTINCT a.lecture_id)::NUMERIC
                    / NULLIF(COUNT(DISTINCT ls.lecture_id), 0) * 100, 2
                )                                        AS percentage
            FROM   students s
            JOIN   courses c ON c.department = s.department
                             AND c.semester   = s.semester
            LEFT   JOIN lecture_sessions ls ON ls.course_id = c.course_id
                                           AND ls.status    = 'closed'
            LEFT   JOIN attendance a ON a.lecture_id = ls.lecture_id
                                    AND a.student_id  = s.student_id
            GROUP  BY s.student_id, s.name, s.department, c.course_id, c.course_name
            HAVING ROUND(
                COUNT(DISTINCT a.lecture_id)::NUMERIC
                / NULLIF(COUNT(DISTINCT ls.lecture_id), 0) * 100, 2
            ) < $1
            ORDER  BY percentage ASC
            """,
            cfg.low_attendance_threshold,
        )
    return [dict(r) for r in rows]
