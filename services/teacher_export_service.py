"""
Teacher attendance export helpers.

Exports are intentionally dependency-free so the API keeps working without
extra reporting packages installed.
"""

from __future__ import annotations

from datetime import datetime
from html import escape


def build_attendance_excel(report: dict) -> bytes:
    """Return a simple Excel-compatible HTML workbook."""
    course = report["course"]
    students = report["students"]

    generated_at = _safe_text(report.get("generated_at", ""))
    title = f"{course['course_id']} - {course['course_name']}"
    rows = []
    for student in students:
        rows.append(
            "<tr>"
            f"<td>{escape(_safe_text(student['student_id']))}</td>"
            f"<td>{escape(_safe_text(student['name']))}</td>"
            f"<td>{escape(_safe_text(student.get('email') or '-'))}</td>"
            f"<td>{student['total_lectures']}</td>"
            f"<td>{student['attended']}</td>"
            f"<td>{student['percentage']}</td>"
            f"<td>{escape(_safe_text(_format_timestamp(student.get('last_present_at'))))}</td>"
            f"<td>{'Yes' if student.get('face_registered') else 'No'}</td>"
            "</tr>"
        )

    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<style>
body {{ font-family: Arial, sans-serif; font-size: 12px; }}
h1 {{ font-size: 18px; margin-bottom: 4px; }}
.meta {{ margin-bottom: 16px; color: #444; }}
table {{ border-collapse: collapse; width: 100%; }}
th, td {{ border: 1px solid #cfcfcf; padding: 6px 8px; text-align: left; }}
th {{ background: #eef4ff; font-weight: 700; }}
</style>
</head>
<body>
<h1>{escape(_safe_text(title))}</h1>
<div class="meta">
  <div>Teacher(s): {escape(_safe_text(course.get('teacher_names') or '-'))}</div>
  <div>Department: {escape(_safe_text(course.get('department') or '-'))}</div>
  <div>Semester: {course.get('semester', '-')}</div>
  <div>Total students: {course.get('total_students', 0)}</div>
  <div>Total lectures: {course.get('total_lectures', 0)}</div>
  <div>Average attendance: {course.get('avg_attendance_pct', 0)}%</div>
  <div>Generated: {escape(generated_at)}</div>
</div>
<table>
  <thead>
    <tr>
      <th>Student ID</th>
      <th>Name</th>
      <th>Email</th>
      <th>Total Lectures</th>
      <th>Attended</th>
      <th>Attendance %</th>
      <th>Last Present</th>
      <th>Face Registered</th>
    </tr>
  </thead>
  <tbody>
    {''.join(rows)}
  </tbody>
</table>
</body>
</html>"""
    return html.encode("utf-8")


def build_attendance_pdf(report: dict) -> bytes:
    """Return a simple text-table PDF."""
    course = report["course"]
    students = report["students"]

    lines = [
        "AttendX Attendance Report",
        f"Course   : {_safe_text(course['course_id'])} - {_safe_text(course['course_name'])}",
        f"Teacher  : {_safe_text(course.get('teacher_names') or '-')}",
        f"Dept/Sem : {_safe_text(course.get('department') or '-')} / {course.get('semester', '-')}",
        f"Lectures : {course.get('total_lectures', 0)}    Students: {course.get('total_students', 0)}    Avg: {course.get('avg_attendance_pct', 0)}%",
        f"Generated: {_safe_text(report.get('generated_at', ''))}",
        "",
        _fixed_row(("Student ID", "Name", "Lectures", "Attended", "%", "Last Present"), (12, 26, 10, 10, 8, 18)),
        "-" * 96,
    ]

    for student in students:
        lines.append(
            _fixed_row(
                (
                    student["student_id"],
                    student["name"],
                    student["total_lectures"],
                    student["attended"],
                    f"{student['percentage']}%",
                    _format_timestamp(student.get("last_present_at")) or "-",
                ),
                (12, 26, 10, 10, 8, 18),
            )
        )

    return _render_simple_pdf(lines, title=f"{course['course_id']} Attendance Report")


def build_export_filename(course_id: str, fmt: str) -> str:
    suffix = datetime.now().strftime("%Y%m%d")
    extension = "xls" if fmt == "excel" else "pdf"
    safe_course = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in course_id)
    return f"{safe_course}_attendance_till_date_{suffix}.{extension}"


def _fixed_row(values: tuple[object, ...], widths: tuple[int, ...]) -> str:
    parts = []
    for value, width in zip(values, widths):
        text = _safe_text(value)
        if len(text) > width:
            text = text[: max(0, width - 3)] + "..."
        parts.append(text.ljust(width))
    return " ".join(parts)


def _render_simple_pdf(lines: list[str], title: str) -> bytes:
    page_width = 792
    page_height = 612
    margin_left = 36
    margin_top = 36
    line_height = 11
    usable_lines = 46

    pages = [lines[i:i + usable_lines] for i in range(0, len(lines), usable_lines)] or [[]]
    objects: list[bytes] = []
    offsets: list[int] = [0]

    def add_object(body: bytes) -> int:
        obj_id = len(objects) + 1
        objects.append(f"{obj_id} 0 obj\n".encode("ascii") + body + b"\nendobj\n")
        return obj_id

    catalog_id = add_object(b"<< /Type /Catalog /Pages 2 0 R >>")
    pages_placeholder_id = add_object(b"<< /Type /Pages /Count 0 /Kids [] >>")
    font_id = add_object(b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier >>")

    page_ids: list[int] = []
    content_ids: list[int] = []
    for page_index, page_lines in enumerate(pages, start=1):
        stream_lines = [
            "BT",
            "/F1 9 Tf",
            f"{margin_left} {page_height - margin_top} Td",
            f"{line_height} TL",
        ]
        for idx, line in enumerate(page_lines):
            rendered = _pdf_escape(_safe_text(line))
            if idx == 0:
                stream_lines.append(f"({rendered}) Tj")
            else:
                stream_lines.append("T*")
                stream_lines.append(f"({rendered}) Tj")
        stream_lines.extend([
            "T*",
            f"(Page {page_index} of {len(pages)} - {_pdf_escape(_safe_text(title))}) Tj",
            "ET",
        ])
        stream = "\n".join(stream_lines).encode("latin-1", errors="replace")
        content_id = add_object(
            f"<< /Length {len(stream)} >>\nstream\n".encode("ascii") + stream + b"\nendstream"
        )
        page_id = add_object(
            (
                f"<< /Type /Page /Parent {pages_placeholder_id} 0 R "
                f"/MediaBox [0 0 {page_width} {page_height}] "
                f"/Resources << /Font << /F1 {font_id} 0 R >> >> "
                f"/Contents {content_id} 0 R >>"
            ).encode("ascii")
        )
        content_ids.append(content_id)
        page_ids.append(page_id)

    kids = " ".join(f"{page_id} 0 R" for page_id in page_ids)
    objects[pages_placeholder_id - 1] = (
        f"{pages_placeholder_id} 0 obj\n<< /Type /Pages /Count {len(page_ids)} /Kids [{kids}] >>\nendobj\n"
    ).encode("ascii")

    pdf = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"
    for obj in objects:
        offsets.append(len(pdf))
        pdf += obj

    xref_pos = len(pdf)
    pdf += f"xref\n0 {len(objects) + 1}\n".encode("ascii")
    pdf += b"0000000000 65535 f \n"
    for offset in offsets[1:]:
        pdf += f"{offset:010} 00000 n \n".encode("ascii")
    pdf += (
        f"trailer\n<< /Size {len(objects) + 1} /Root {catalog_id} 0 R >>\n"
        f"startxref\n{xref_pos}\n%%EOF"
    ).encode("ascii")
    return pdf


def _pdf_escape(text: str) -> str:
    safe = []
    for char in text:
        code = ord(char)
        if char in ("\\", "(", ")"):
            safe.append("\\" + char)
        elif 32 <= code <= 126:
            safe.append(char)
        else:
            safe.append("?")
    return "".join(safe)


def _format_timestamp(value: object) -> str:
    if not value:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%d %b %Y %H:%M")
    return _safe_text(value)


def _safe_text(value: object) -> str:
    if value is None:
        return ""
    return str(value)
