"""
Security regression suite.

Every test here encodes an attack that worked against the previous version
of AttendX (no sessions, client-asserted identity, plaintext PINs, unsalted
hashes, unrestricted uploads) and must now fail.
"""

from __future__ import annotations

import hashlib
import zlib

import pytest

from tests.conftest import STRONG, Session, set_password

STUDENT_A, STUDENT_B = "202411052", "202411090"
TEACHER_DBMS, TEACHER_COA = "T002", "T001"   # T002 teaches CS204, T001 teaches CS208


# ─────────────────────────────────────────────
# Authentication is mandatory
# ─────────────────────────────────────────────

PUBLIC = {("POST", "/auth/login"), ("GET", "/auth/session"), ("GET", "/health"), ("GET", "/")}


def _all_api_routes():
    from api.server import app
    spec = app.openapi()
    for path, ops in spec["paths"].items():
        for method in ops:
            yield method.upper(), path


async def test_every_endpoint_requires_a_session(make_client):
    client = make_client()
    checked = 0
    for method, path in _all_api_routes():
        if (method, path) in PUBLIC:
            continue
        url = (path.replace("{student_id}", STUDENT_A).replace("{teacher_id}", TEACHER_DBMS)
               .replace("{course_id}", "CS204").replace("{classroom_id}", "CR-2113")
               .replace("{lecture_id}", "1").replace("{dispute_id}", "1")
               .replace("{file_name}", "20260101000000_" + "a" * 32 + ".pdf").replace("{kind}", "students"))
        res = await client.request(method, url, json={})
        assert res.status_code == 401, f"{method} {path} -> {res.status_code}"
        checked += 1
    assert checked > 40


async def test_identity_is_never_taken_from_the_request(login):
    # Old API: POST /auth/login just echoed the role; any client could then
    # claim any user_id. Now the server derives identity from the session.
    s = await login("student", STUDENT_A)
    res = await s.post("/attendance/disputes", json={
        "student_id": STUDENT_B,              # ignored: not part of the schema
        "course_id": "CS204", "reason": "testing identity binding",
    })
    assert res.status_code == 200, res.text
    assert res.json()["student_id"] == STUDENT_A


# ─────────────────────────────────────────────
# Horizontal & vertical privilege escalation
# ─────────────────────────────────────────────

@pytest.mark.parametrize("path", [
    f"/analytics/student/{STUDENT_B}",
    f"/analytics/student/{STUDENT_B}/history",
    f"/analytics/student/{STUDENT_B}/forecast",
    f"/attendance/disputes/student/{STUDENT_B}",
])
async def test_student_cannot_read_another_student(login, path):
    s = await login("student", STUDENT_A)
    assert (await s.get(path)).status_code == 403


@pytest.mark.parametrize("path", [
    "/admin/students", "/admin/audit-log", "/analytics/admin/dashboard",
    "/analytics/admin/export", f"/analytics/teacher/{TEACHER_DBMS}/dashboard", "/attendance/disputes",
])
async def test_student_cannot_reach_staff_endpoints(login, path):
    s = await login("student", STUDENT_A)
    assert (await s.get(path)).status_code == 403


async def test_teacher_is_confined_to_own_courses(login):
    t = await login("teacher", TEACHER_DBMS)
    assert (await t.get(f"/analytics/teacher/{TEACHER_DBMS}/courses/CS204")).status_code == 200
    assert (await t.get(f"/analytics/teacher/{TEACHER_COA}/dashboard")).status_code == 403
    assert (await t.get(f"/analytics/teacher/{TEACHER_DBMS}/courses/CS208")).status_code == 404
    assert (await t.get("/admin/classrooms")).status_code == 403
    # Classroom list for teachers never exposes PIN material.
    rooms = (await t.get("/lecture/classrooms")).json()
    assert rooms and all("pin" not in "".join(r.keys()) for r in rooms)


async def test_teacher_cannot_run_or_edit_someone_elses_lecture(login):
    owner = await login("teacher", TEACHER_COA)
    started = await owner.post("/lecture/start", json={"classroom_id": "CR-2113", "course_id": "CS208"})
    assert started.status_code == 200, started.text
    lecture_id = started.json()["lecture_id"]

    other = await login("teacher", TEACHER_DBMS)
    assert (await other.post("/lecture/start", json={"classroom_id": "CR-2113", "course_id": "CS208"})).status_code == 403
    assert (await other.post("/lecture/start", json={"classroom_id": "CR-2113", "course_id": "CS204"})).status_code == 409
    assert (await other.get(f"/lecture/{lecture_id}/live")).status_code == 403
    assert (await other.post("/attendance/override", json={"student_id": STUDENT_A, "lecture_id": lecture_id, "present": True})).status_code == 403
    assert (await other.post("/lecture/end", json={"lecture_id": lecture_id})).status_code == 403

    ok = await owner.post("/attendance/override", json={"student_id": STUDENT_A, "lecture_id": lecture_id, "present": True})
    assert ok.status_code == 200 and ok.json()["changed"] is True
    # A student from another department can never be marked into this lecture.
    assert (await owner.post("/attendance/override", json={"student_id": "ECE001", "lecture_id": lecture_id, "present": True})).status_code == 400
    assert (await owner.post("/lecture/end", json={"lecture_id": lecture_id})).status_code == 200


async def test_classroom_device_is_bound_to_its_room(login):
    lab = await login("classroom", "CR-LAB")
    # Body classroom_id is ignored: the session decides the room.
    res = await lab.post("/lecture/start", json={"classroom_id": "CR-2113", "course_id": "CS208"})
    assert res.status_code == 403   # CS208 is not scheduled in CR-LAB
    assert (await lab.get("/lecture/upcoming/CR-2113")).status_code == 403
    assert (await lab.post("/lecture/force-close/CR-2113")).status_code == 403
    assert (await lab.get("/lecture/upcoming/CR-LAB")).status_code == 200


async def test_admin_only_actions(login):
    t = await login("teacher", TEACHER_DBMS)
    assert (await t.post("/auth/issue-password", json={"target_role": "student", "target_user_id": STUDENT_A})).status_code == 403
    assert (await t.post("/attendance/mark", json={"student_id": STUDENT_A, "lecture_id": 1})).status_code == 403
    assert (await t.put("/admin/classrooms/CR-2113/pin", json={"pin": "739104"})).status_code == 403


# ─────────────────────────────────────────────
# Sessions, CSRF, lockout, password lifecycle
# ─────────────────────────────────────────────

async def test_state_changes_require_csrf_token(login):
    s = await login("admin", "admin")
    res = await s.client.post("/admin/courses", json={"course_id": "X1", "course_name": "x", "department": "CSE", "semester": 1})
    assert res.status_code == 403
    res = await s.client.post("/admin/courses", headers={"X-CSRF-Token": "forged"},
                              json={"course_id": "X1", "course_name": "x", "department": "CSE", "semester": 1})
    assert res.status_code == 403


async def test_session_cookie_is_hardened(make_client):
    await set_password("student", STUDENT_A)
    client = make_client()
    res = await client.post("/auth/login", json={"role": "student", "user_id": STUDENT_A, "password": STRONG})
    cookie = res.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie and "path=/" in cookie
    # Only a digest of the token is stored server-side.
    from core.database import get_conn
    token = client.cookies.get("attendx_session")
    async with get_conn() as conn:
        assert not await conn.fetchval("SELECT 1 FROM auth_sessions WHERE token_hash = $1", token)
        assert await conn.fetchval("SELECT 1 FROM auth_sessions WHERE token_hash = $1",
                                   hashlib.sha256(token.encode()).hexdigest())


async def test_logout_revokes_the_session(login):
    s = await login("student", STUDENT_A)
    assert (await s.post("/auth/logout")).status_code == 200
    assert (await s.get("/auth/me")).status_code == 401


async def test_lockout_after_repeated_failures(make_client):
    await set_password("student", STUDENT_B)
    client = make_client()
    for _ in range(5):
        r = await client.post("/auth/login", json={"role": "student", "user_id": STUDENT_B, "password": "wrong-password-1"})
        assert r.status_code == 401
    r = await client.post("/auth/login", json={"role": "student", "user_id": STUDENT_B, "password": STRONG})
    assert r.status_code == 429, "correct password must not bypass an active lock"


async def test_ip_rate_limit_on_login(make_client):
    client = make_client()
    codes = [(await client.post("/auth/login", json={"role": "student", "user_id": f"nobody{i}", "password": "x"})).status_code
             for i in range(22)]
    assert codes.count(429) >= 1


async def test_unknown_and_known_users_get_the_same_error(make_client):
    await set_password("student", STUDENT_A)
    client = make_client()
    a = await client.post("/auth/login", json={"role": "student", "user_id": STUDENT_A, "password": "Wrong-pass-123"})
    b = await client.post("/auth/login", json={"role": "student", "user_id": "ghost99", "password": "Wrong-pass-123"})
    assert a.status_code == b.status_code == 401
    assert a.json() == b.json()


async def test_temporary_password_forces_a_change(login, make_client):
    admin = await login("admin", "admin")
    issued = await admin.post("/auth/issue-password", json={"target_role": "student", "target_user_id": STUDENT_B})
    assert issued.status_code == 200
    temp = issued.json()["temporary_password"]

    client = make_client()
    res = await client.post("/auth/login", json={"role": "student", "user_id": STUDENT_B, "password": temp})
    assert res.status_code == 200 and res.json()["must_change_password"] is True
    s = Session(client, res.json()["csrf_token"])
    assert (await s.get(f"/analytics/student/{STUDENT_B}")).status_code == 403   # gated until changed

    weak = await s.post("/auth/change-password", json={"current_password": temp, "new_password": "password1"})
    assert weak.status_code == 400
    ok = await s.post("/auth/change-password", json={"current_password": temp, "new_password": "N3w-Secret-Phrase"})
    assert ok.status_code == 200
    s.csrf = ok.json()["csrf_token"]
    assert (await s.get(f"/analytics/student/{STUDENT_B}")).status_code == 200


async def test_password_is_stored_with_scrypt(login):
    await login("student", STUDENT_A)
    from core.database import get_conn
    async with get_conn() as conn:
        stored = await conn.fetchval("SELECT password_hash FROM login_credentials WHERE role='student' AND principal_id=$1", STUDENT_A)
    assert stored.startswith("scrypt$15$8$1$")


async def test_legacy_default_credentials_are_disabled():
    from core.database import get_conn
    from migrations.schema import run_migrations
    async with get_conn() as conn:
        await conn.execute(
            "UPDATE login_credentials SET password_hash = encode(digest(principal_id, 'sha256'), 'hex') WHERE principal_id = '202411064'"
        )
    await run_migrations()
    async with get_conn() as conn:
        row = await conn.fetchrow("SELECT password_hash, must_change_password FROM login_credentials WHERE principal_id = '202411064'")
    assert row["password_hash"] is None and row["must_change_password"] is True


async def test_classroom_pins_are_hashed_and_policy_checked(login):
    admin = await login("admin", "admin")
    assert (await admin.put("/admin/classrooms/CR-2113/pin", json={"pin": "1234"})).status_code == 400
    assert (await admin.put("/admin/classrooms/CR-2113/pin", json={"pin": "123456"})).status_code == 400
    assert (await admin.put("/admin/classrooms/CR-2113/pin", json={"pin": "739104"})).status_code == 200
    listed = (await admin.get("/admin/classrooms")).json()
    assert all("access_pin" not in r and "access_pin_hash" not in r for r in listed)
    from core.database import get_conn
    async with get_conn() as conn:
        assert (await conn.fetchval("SELECT access_pin_hash FROM classrooms WHERE classroom_id='CR-2113'")).startswith("scrypt$")


# ─────────────────────────────────────────────
# Uploads
# ─────────────────────────────────────────────

def _pdf(body: bytes) -> bytes:
    return b"%PDF-1.4\n" + body + b"\ntrailer<</Root 1 0 R>>\n%%EOF\n"


@pytest.mark.parametrize("payload", [
    b"1 0 obj<</Type/Catalog/OpenAction<</S/JavaScript/JS(app.alert(1))>>>>endobj",
    b"1 0 obj<</Type/Catalog/Names<</EmbeddedFiles 2 0 R>>>>endobj",
    b"1 0 obj<</S/Launch/F(cmd.exe)>>endobj",
    b"1 0 obj<</S/J#61vaScript>>endobj",                       # hex-escaped name
])
async def test_active_pdfs_are_rejected(login, payload):
    s = await login("student", STUDENT_A)
    res = await s.post("/attendance/disputes/evidence", files={"file": ("cert.pdf", _pdf(payload), "application/pdf")})
    assert res.status_code == 400


async def test_javascript_hidden_in_object_stream_is_rejected(login):
    hidden = zlib.compress(b"<</S/JavaScript/JS(app.alert(1))>>")
    body = b"5 0 obj<</Type/ObjStm/N 1/First 4/Filter/FlateDecode/Length %d>>stream\n" % len(hidden) + hidden + b"\nendstream endobj"
    s = await login("student", STUDENT_A)
    res = await s.post("/attendance/disputes/evidence", files={"file": ("cert.pdf", _pdf(body), "application/pdf")})
    assert res.status_code == 400


async def test_non_pdf_is_rejected(login):
    s = await login("student", STUDENT_A)
    res = await s.post("/attendance/disputes/evidence", files={"file": ("cert.pdf", b"<script>alert(1)</script>", "application/pdf")})
    assert res.status_code == 400


async def test_evidence_access_is_owner_teacher_or_admin(login):
    image_like = zlib.compress(bytes(range(256)) * 400)     # binary stream data may contain "/JS" by chance
    clean = _pdf(b"1 0 obj<</Type/Catalog>>endobj\n2 0 obj<</Length %d/Filter/FlateDecode>>stream\n" % len(image_like) + image_like + b"\nendstream endobj")
    owner = await login("student", STUDENT_A)
    up = await owner.post("/attendance/disputes/evidence", files={"file": ("medical.pdf", clean, "application/pdf")})
    assert up.status_code == 200, up.text
    name = up.json()["file_name"]
    assert (await owner.post("/attendance/disputes", json={"course_id": "CS204", "reason": "medical leave", "evidence_file": name})).status_code == 200

    url = f"/attendance/disputes/evidence/{name}"
    got = await owner.get(url)
    assert got.status_code == 200 and "sandbox" in got.headers["content-security-policy"]
    assert (await (await login("student", STUDENT_B)).get(url)).status_code == 404
    assert (await (await login("teacher", TEACHER_DBMS)).get(url)).status_code == 200      # teaches CS204
    assert (await (await login("teacher", TEACHER_COA)).get(url)).status_code == 404       # does not
    # Another student cannot attach someone else's file to their own dispute.
    thief = await login("student", STUDENT_B)
    assert (await thief.post("/attendance/disputes", json={"course_id": "CS204", "reason": "steal", "evidence_file": name})).status_code == 400


async def test_path_traversal_is_impossible(login):
    s = await login("admin", "admin")
    for bad in ["..%2F..%2Fseed.sql", "..\\..\\main.py", "x.pdf"]:
        assert (await s.get(f"/attendance/disputes/evidence/{bad}")).status_code in (404, 422)


async def test_csv_import_validates_rows_independently(login):
    s = await login("admin", "admin")
    csv = ("student_id,name,email,department,semester\n"
           "NEW001,Good Row,good@example.com,CSE,4\n"
           "bad id!,Broken,,CSE,4\n"
           "NEW002,Bad Sem,,CSE,99\n"
           "NEW003,Also Good,,CSE,4\n")
    res = await s.post("/admin/upload/students", files={"file": ("s.csv", csv.encode(), "text/csv")})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["inserted"] == 2 and body["skipped"] == 2 and len(body["errors"]) == 2


# ─────────────────────────────────────────────
# Integrity, transport, injection
# ─────────────────────────────────────────────

async def test_student_cannot_dispute_a_course_they_do_not_take(login):
    s = await login("student", STUDENT_A)
    assert (await s.post("/attendance/disputes", json={"course_id": "EC101", "reason": "not my course"})).status_code == 400


async def test_sql_injection_payloads_are_inert(login):
    s = await login("admin", "admin")
    res = await s.get("/admin/students", params={"department": "CSE' OR '1'='1"})
    assert res.status_code == 200 and res.json() == []
    assert (await s.get("/analytics/student/1' OR '1'='1")).status_code == 422


async def test_security_headers_and_host_allowlist(make_client):
    from httpx import ASGITransport, AsyncClient
    from api.server import app
    client = make_client()
    res = await client.get("/login.html")
    h = res.headers
    assert "script-src 'self'" in h["content-security-policy"] and "unsafe-inline" not in h["content-security-policy"]
    assert h["x-frame-options"] == "DENY" and h["x-content-type-options"] == "nosniff"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://attacker.example") as evil:
        assert (await evil.get("/health")).status_code == 400


async def test_errors_do_not_leak_internals(login):
    s = await login("admin", "admin")
    dup = await s.post("/admin/students", json={"student_id": STUDENT_A, "name": "dup", "department": "CSE", "semester": 4})
    assert dup.status_code == 409
    assert "duplicate key" not in dup.text and "asyncpg" not in dup.text


async def test_date_filtered_export_works(login):
    s = await login("admin", "admin")
    res = await s.get("/analytics/admin/export", params={"format": "excel", "from_date": "2026-01-01", "to_date": "2026-12-31"})
    assert res.status_code == 200 and res.headers["content-disposition"].startswith("attachment")
    assert (await s.get("/analytics/admin/export", params={"from_date": "2026-12-31", "to_date": "2026-01-01"})).status_code == 400


def test_export_cells_cannot_inject_formulas():
    from services.teacher_export_service import _safe_text
    assert _safe_text("=HYPERLINK(\"http://x\")").startswith("'")
    assert _safe_text("Kavya") == "Kavya"


def test_face_templates_are_encrypted_and_bound_to_student():
    import numpy as np
    from utils.face_utils import decode_template, encode_template
    vec = np.random.default_rng(1).normal(size=512).astype(np.float32)
    blob = encode_template("S1", vec)
    assert blob[:4] == b"AXF1" and vec.tobytes() not in blob
    assert np.allclose(decode_template("S1", blob), vec / np.linalg.norm(vec), atol=1e-6)
    assert decode_template("S2", blob) is None          # swapped onto another student → rejected
    tampered = blob[:-1] + bytes([blob[-1] ^ 1])
    assert decode_template("S1", tampered) is None


async def test_legacy_plaintext_pins_are_migrated():
    from core.database import get_conn
    from migrations.schema import run_migrations
    async with get_conn() as conn:
        await conn.execute("ALTER TABLE classrooms ADD COLUMN access_pin TEXT")
        await conn.execute("UPDATE classrooms SET access_pin = '1234', access_pin_hash = NULL WHERE classroom_id = 'CR-LAB'")
        await conn.execute("UPDATE classrooms SET access_pin = '739104', access_pin_hash = NULL WHERE classroom_id = 'CR-2113'")
    await run_migrations()
    async with get_conn() as conn:
        assert not await conn.fetchval(
            "SELECT 1 FROM information_schema.columns WHERE table_name='classrooms' AND column_name='access_pin'")
        weak = await conn.fetchval("SELECT access_pin_hash FROM classrooms WHERE classroom_id='CR-LAB'")
        strong = await conn.fetchval("SELECT access_pin_hash FROM classrooms WHERE classroom_id='CR-2113'")
    assert weak is None                     # 1234 is disabled, not carried over
    assert strong.startswith("scrypt$")
