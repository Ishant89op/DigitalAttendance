"""
Integration test fixtures — run against a real, disposable PostgreSQL database.

    set ATTENDX_TEST_DB_* (or DB_*) to a server you can create databases on, then:
    python -m pytest

Each test session creates `attendx_test_<random>` and drops it afterwards.
"""

from __future__ import annotations

import os
import secrets
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# Isolate generated secrets for the test run before any app module loads.
os.environ.setdefault("ATTENDX_INSTANCE_DIR", tempfile.mkdtemp(prefix="attendx-test-"))
for key in ("HOST", "PORT", "USER", "PASSWORD"):
    if os.getenv(f"ATTENDX_TEST_DB_{key}"):
        os.environ[f"DB_{key}"] = os.environ[f"ATTENDX_TEST_DB_{key}"]
TEST_DB = os.environ.setdefault("ATTENDX_TEST_DB_NAME", f"attendx_test_{secrets.token_hex(4)}")
os.environ["DB_NAME"] = TEST_DB

import asyncpg  # noqa: E402
import httpx  # noqa: E402

STRONG = "Str0ng-Passw0rd!"


def _server_kwargs() -> dict:
    return dict(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "5432")),
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASSWORD") or None,
    )


@pytest.fixture(scope="session", autouse=True)
async def database():
    try:
        admin = await asyncpg.connect(database="postgres", **_server_kwargs())
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"PostgreSQL not reachable for integration tests: {exc}")
    await admin.execute(f'CREATE DATABASE "{TEST_DB}"')
    await admin.close()

    from core.database import close_pool, get_conn, init_pool
    from migrations.schema import run_migrations

    await init_pool()
    await run_migrations()
    async with get_conn() as conn:
        await conn.execute((ROOT / "seed.sql").read_text(encoding="utf-8"))
        # A second, unrelated semester/department to test isolation.
        await conn.execute(
            """
            INSERT INTO courses (course_id, course_name, department, semester) VALUES ('EC101', 'Circuits', 'ECE', 2);
            INSERT INTO teachers (teacher_id, name, department) VALUES ('T900', 'Other Dept Teacher', 'ECE');
            INSERT INTO course_teachers (course_id, teacher_id) VALUES ('EC101', 'T900');
            INSERT INTO students (student_id, name, department, semester) VALUES ('ECE001', 'Other Student', 'ECE', 2);
            """
        )
    await run_migrations()   # credential rows for seeded people
    yield
    await close_pool()
    admin = await asyncpg.connect(database="postgres", **_server_kwargs())
    await admin.execute(f'DROP DATABASE IF EXISTS "{TEST_DB}" WITH (FORCE)')
    await admin.close()


@pytest.fixture(autouse=True)
def _reset_limits(monkeypatch):
    from core import auth
    auth.login_limiter.reset()
    auth.api_limiter.reset()

    # Never spawn camera processes from tests.
    import api.routers.lecture as lecture_router

    async def _no_camera(_classroom_id):
        return False

    async def _not_running(_classroom_id):
        return False

    monkeypatch.setattr(lecture_router, "start_recognition_process", _no_camera)
    monkeypatch.setattr(lecture_router, "stop_recognition_process", _no_camera)
    monkeypatch.setattr(lecture_router, "is_running_async", _not_running)


@pytest.fixture
async def make_client():
    from api.server import app

    clients: list[httpx.AsyncClient] = []

    def _make() -> httpx.AsyncClient:
        c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost")
        clients.append(c)
        return c

    yield _make
    for c in clients:
        await c.aclose()


async def set_password(role: str, user_id: str, password: str = STRONG, must_change: bool = False) -> None:
    from core.database import get_conn
    from core.security import hash_secret

    async with get_conn() as conn:
        await conn.execute(
            """
            INSERT INTO login_credentials (role, principal_id, password_hash, must_change_password)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (role, principal_id) DO UPDATE
            SET password_hash = EXCLUDED.password_hash, must_change_password = EXCLUDED.must_change_password,
                failed_attempts = 0, locked_until = NULL, temp_expires_at = NULL
            """,
            role, user_id, hash_secret(password), must_change,
        )


async def set_pin(classroom_id: str, pin: str = "482916") -> None:
    from core.database import get_conn
    from core.security import hash_secret

    async with get_conn() as conn:
        await conn.execute(
            "UPDATE classrooms SET access_pin_hash = $2, pin_failed_attempts = 0, pin_locked_until = NULL WHERE classroom_id = $1",
            classroom_id, hash_secret(pin),
        )


class Session:
    """Logged-in client that sends the CSRF header automatically."""

    def __init__(self, client: httpx.AsyncClient, csrf: str):
        self.client = client
        self.csrf = csrf

    async def get(self, url, **kw):
        return await self.client.get(url, **kw)

    async def post(self, url, json=None, **kw):
        headers = {"X-CSRF-Token": self.csrf, **kw.pop("headers", {})}
        return await self.client.post(url, json=json, headers=headers, **kw)

    async def put(self, url, json=None, **kw):
        return await self.client.put(url, json=json, headers={"X-CSRF-Token": self.csrf}, **kw)

    async def delete(self, url, **kw):
        return await self.client.delete(url, headers={"X-CSRF-Token": self.csrf}, **kw)


@pytest.fixture
async def login(make_client):
    async def _login(role: str, user_id: str, password: str = STRONG, expect: int = 200) -> Session:
        if role == "classroom":
            await set_pin(user_id, password if password != STRONG else "482916")
            password = password if password != STRONG else "482916"
        else:
            await set_password(role, user_id, password)
        client = make_client()
        res = await client.post("/auth/login", json={"role": role, "user_id": user_id, "password": password})
        assert res.status_code == expect, res.text
        return Session(client, res.json().get("csrf_token", ""))

    return _login
