from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

import api.routers.analytics as analytics_router
import api.routers.attendance as attendance_router
import api.routers.auth as auth_router


class FakeConn:
    def __init__(self, fetchvals: list[object] | None = None) -> None:
        self.fetchvals = list(fetchvals or [])
        self.executed: list[tuple[tuple[object, ...], dict]] = []

    async def fetchval(self, *args, **kwargs):
        if self.fetchvals:
            return self.fetchvals.pop(0)
        return None

    async def execute(self, *args, **kwargs):
        self.executed.append((args, kwargs))
        return "UPDATE 1"


class FakeConnCtx:
    def __init__(self, conn: FakeConn) -> None:
        self.conn = conn

    async def __aenter__(self) -> FakeConn:
        return self.conn

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False


def build_client() -> TestClient:
    app = FastAPI()
    app.include_router(analytics_router.router)
    app.include_router(attendance_router.router)
    app.include_router(auth_router.router)
    return TestClient(app)


def test_student_forecast_endpoint_calls_service(monkeypatch):
    calls: dict[str, object] = {}

    async def fake_forecast(student_id: str, recent_window: int, projection_lectures: int):
        calls["student_id"] = student_id
        calls["recent_window"] = recent_window
        calls["projection_lectures"] = projection_lectures
        return {"student_id": student_id, "courses": []}

    monkeypatch.setattr(analytics_router, "get_student_risk_forecast", fake_forecast)

    with build_client() as client:
        response = client.get(
            "/analytics/student/S100/forecast?recent_window=4&projection_lectures=9"
        )

    assert response.status_code == 200
    assert response.json()["student_id"] == "S100"
    assert calls == {
        "student_id": "S100",
        "recent_window": 4,
        "projection_lectures": 9,
    }


def test_mark_reminders_sent_uses_request_body(monkeypatch):
    calls: dict[str, object] = {}

    async def fake_mark(reminder_ids=None):
        calls["reminder_ids"] = reminder_ids
        return {"updated": len(reminder_ids or [])}

    monkeypatch.setattr(analytics_router, "mark_defaulter_reminders_sent", fake_mark)

    with build_client() as client:
        response = client.post(
            "/analytics/admin/reminders/mark-sent",
            json={"reminder_ids": [11, 12, 13]},
        )

    assert response.status_code == 200
    assert response.json() == {"updated": 3}
    assert calls["reminder_ids"] == [11, 12, 13]


def test_admin_export_excel_uses_filtered_builder(monkeypatch):
    async def fake_report(**kwargs):
        return {
            "generated_at": "2026-01-01T00:00:00+00:00",
            "filters": kwargs,
            "summary": {"records": 1, "unique_students": 1, "unique_lectures": 1},
            "rows": [{"lecture_id": 1}],
        }

    monkeypatch.setattr(analytics_router, "get_filtered_attendance_export", fake_report)
    monkeypatch.setattr(
        analytics_router,
        "build_filtered_attendance_excel",
        lambda report: b"excel-bytes",
    )

    with build_client() as client:
        response = client.get(
            "/analytics/admin/export?format=excel&course_id=CS101&from_date=2026-01-01&to_date=2026-01-31"
        )

    assert response.status_code == 200
    assert response.content == b"excel-bytes"
    assert "attachment; filename=" in response.headers["content-disposition"]


def test_create_dispute_endpoint_calls_service(monkeypatch):
    calls: dict[str, object] = {}

    async def fake_create(student_id, course_id, lecture_id, reason, evidence):
        calls.update(
            {
                "student_id": student_id,
                "course_id": course_id,
                "lecture_id": lecture_id,
                "reason": reason,
                "evidence": evidence,
            }
        )
        return {"dispute_id": 55, "status": "open"}

    monkeypatch.setattr(attendance_router, "create_dispute", fake_create)

    with build_client() as client:
        response = client.post(
            "/attendance/disputes",
            json={
                "student_id": "202411001",
                "course_id": "CS204",
                "lecture_id": 42,
                "reason": "Marked absent by mistake",
                "evidence": "Was in class",
            },
        )

    assert response.status_code == 200
    assert response.json() == {"dispute_id": 55, "status": "open"}
    assert calls["student_id"] == "202411001"
    assert calls["course_id"] == "CS204"
    assert calls["lecture_id"] == 42


def test_resolve_dispute_endpoint_calls_service(monkeypatch):
    calls: dict[str, object] = {}

    async def fake_resolve(dispute_id, reviewer_id, reviewer_role, action, resolution_note):
        calls.update(
            {
                "dispute_id": dispute_id,
                "reviewer_id": reviewer_id,
                "reviewer_role": reviewer_role,
                "action": action,
                "resolution_note": resolution_note,
            }
        )
        return {"dispute_id": dispute_id, "status": action}

    monkeypatch.setattr(attendance_router, "resolve_dispute", fake_resolve)

    with build_client() as client:
        response = client.post(
            "/attendance/disputes/88/resolve",
            json={
                "reviewer_id": "T001",
                "reviewer_role": "teacher",
                "action": "approved",
                "resolution_note": "Confirmed present",
            },
        )

    assert response.status_code == 200
    assert response.json() == {"dispute_id": 88, "status": "approved"}
    assert calls["dispute_id"] == 88
    assert calls["reviewer_role"] == "teacher"


def test_change_password_endpoint_success(monkeypatch):
    fake_conn = FakeConn(fetchvals=["oldhash"])  # old password exists
    monkeypatch.setattr(auth_router, "get_conn", lambda: FakeConnCtx(fake_conn))

    with build_client() as client:
        response = client.post(
            "/auth/change-password",
            json={
                "role": "student",
                "user_id": "202411001",
                "current_password": "old-pass",
                "new_password": "new-pass-123",
            },
        )

    assert response.status_code == 200
    assert response.json()["message"] == "Password updated successfully."
    assert len(fake_conn.executed) == 1


def test_reset_password_endpoint_success(monkeypatch):
    # fetchval calls: admin auth check, target existence check
    fake_conn = FakeConn(fetchvals=[1, 1])
    monkeypatch.setattr(auth_router, "get_conn", lambda: FakeConnCtx(fake_conn))

    with build_client() as client:
        response = client.post(
            "/auth/reset-password",
            json={
                "admin_id": "A001",
                "admin_password": "admin-pass",
                "target_role": "student",
                "target_user_id": "202411001",
                "new_password": "reset-pass-123",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["target_role"] == "student"
    assert payload["target_user_id"] == "202411001"
    assert len(fake_conn.executed) == 1
