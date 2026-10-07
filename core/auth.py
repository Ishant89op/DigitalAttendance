"""
Authentication & authorization.

Model
-----
* A successful login creates a server-side session row. The browser receives
  an opaque 256-bit token in an HttpOnly, SameSite=Strict cookie; the database
  stores only its SHA-256 digest.
* Every state-changing request must also carry X-CSRF-Token, an HMAC of the
  session token that the UI receives at login / from /auth/me.
* Sessions expire after an idle timeout and an absolute lifetime, and are
  revoked on logout, password change and admin reset.
* Routes declare who may call them with `Depends(require(...))`; resource
  ownership (own student record, own course, own classroom) is checked with
  the helpers at the bottom of this module.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, Request, Response

from config.settings import security as cfg
from core.database import get_conn
from core.security import csrf_for, csrf_valid, new_session_token, token_digest

logger = logging.getLogger(__name__)

ROLES = {"student", "teacher", "admin", "classroom"}
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


@dataclass(frozen=True)
class Principal:
    role: str
    user_id: str
    name: str
    token: str
    must_change_password: bool

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


# ─────────────────────────────────────────────
# CLIENT METADATA
# ─────────────────────────────────────────────

def client_ip(request: Request) -> str:
    # X-Forwarded-For is deliberately ignored: the API is not meant to sit
    # behind an untrusted proxy, and trusting the header would let any client
    # pick its own rate-limit bucket.
    return request.client.host if request.client else "unknown"


def _user_agent(request: Request) -> str:
    return (request.headers.get("user-agent") or "")[:200]


# ─────────────────────────────────────────────
# RATE LIMITING (in-process sliding window)
# ─────────────────────────────────────────────

class SlidingWindowLimiter:
    def __init__(self, limit: int, window_s: float):
        self.limit = limit
        self.window_s = window_s
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def hit(self, key: str) -> bool:
        """Record one hit; return False when the key is over its limit."""
        now = time.monotonic()
        bucket = self._hits[key]
        while bucket and now - bucket[0] > self.window_s:
            bucket.popleft()
        if len(bucket) >= self.limit:
            return False
        bucket.append(now)
        if len(self._hits) > 50_000:      # bound memory under a flood
            self._prune(now)
        return True

    def retry_after(self, key: str) -> int:
        bucket = self._hits.get(key)
        if not bucket:
            return 0
        return max(1, int(self.window_s - (time.monotonic() - bucket[0])))

    def _prune(self, now: float) -> None:
        for key in [k for k, b in self._hits.items() if not b or now - b[-1] > self.window_s]:
            del self._hits[key]

    def reset(self) -> None:
        self._hits.clear()


login_limiter = SlidingWindowLimiter(cfg.login_rate_per_ip, cfg.login_rate_window_s)
api_limiter = SlidingWindowLimiter(cfg.api_rate_per_ip, 60)


def enforce_login_rate(request: Request) -> None:
    key = client_ip(request)
    if not login_limiter.hit(key):
        raise HTTPException(
            status_code=429,
            detail="Too many sign-in attempts. Try again later.",
            headers={"Retry-After": str(login_limiter.retry_after(key))},
        )


# ─────────────────────────────────────────────
# AUDIT
# ─────────────────────────────────────────────

async def audit(
    event_type: str,
    actor_id: str | None,
    target_id: str | None = None,
    detail: dict | None = None,
    request: Request | None = None,
    conn=None,
) -> None:
    payload = dict(detail or {})
    if request is not None:
        payload.setdefault("ip", client_ip(request))
    payload.setdefault("ts", datetime.now(timezone.utc).isoformat())
    sql = (
        "INSERT INTO audit_log (event_type, actor_id, target_id, detail) "
        "VALUES ($1, $2, $3, $4::JSONB)"
    )
    try:
        if conn is not None:
            await conn.execute(sql, event_type, actor_id, target_id, json.dumps(payload, default=str))
        else:
            async with get_conn() as c:
                await c.execute(sql, event_type, actor_id, target_id, json.dumps(payload, default=str))
    except Exception:
        # Auditing must never take the request down with it.
        logger.exception("Failed to write audit event %s", event_type)


# ─────────────────────────────────────────────
# SESSIONS
# ─────────────────────────────────────────────

def _idle_window(role: str) -> timedelta:
    minutes = cfg.classroom_idle_minutes if role == "classroom" else cfg.session_idle_minutes
    return timedelta(minutes=minutes)


def _cookie_secure(request: Request) -> bool:
    mode = cfg.cookie_secure.strip().lower()
    if mode in {"1", "true", "yes", "on"}:
        return True
    if mode in {"0", "false", "no", "off"}:
        return False
    return request.url.scheme == "https"


async def create_session(
    request: Request,
    response: Response,
    *,
    role: str,
    principal_id: str,
    must_change_password: bool = False,
) -> str:
    """Create a session, set the cookie, and return the CSRF token for the UI."""
    token = new_session_token()
    now = datetime.now(timezone.utc)
    absolute = now + timedelta(hours=cfg.session_absolute_hours)
    async with get_conn() as conn:
        await conn.execute(
            """
            INSERT INTO auth_sessions
                (token_hash, role, principal_id, created_at, last_seen_at,
                 expires_at, ip, user_agent, must_change_password)
            VALUES ($1, $2, $3, $4, $4, $5, $6, $7, $8)
            """,
            token_digest(token), role, principal_id, now, absolute,
            client_ip(request), _user_agent(request), must_change_password,
        )
        # Cap concurrent sessions per account: keep the newest N.
        await conn.execute(
            """
            UPDATE auth_sessions SET revoked_at = NOW()
            WHERE role = $1 AND principal_id = $2 AND revoked_at IS NULL
              AND token_hash NOT IN (
                  SELECT token_hash FROM auth_sessions
                  WHERE role = $1 AND principal_id = $2 AND revoked_at IS NULL
                  ORDER BY created_at DESC
                  LIMIT $3
              )
            """,
            role, principal_id, cfg.max_sessions_per_user,
        )

    response.set_cookie(
        cfg.session_cookie,
        token,
        max_age=cfg.session_absolute_hours * 3600,
        httponly=True,
        secure=_cookie_secure(request),
        samesite="strict",
        path="/",
    )
    return csrf_for(token)


def clear_session_cookie(request: Request, response: Response) -> None:
    response.delete_cookie(
        cfg.session_cookie, path="/", httponly=True,
        secure=_cookie_secure(request), samesite="strict",
    )


async def revoke_session(token: str) -> None:
    async with get_conn() as conn:
        await conn.execute(
            "UPDATE auth_sessions SET revoked_at = NOW() WHERE token_hash = $1 AND revoked_at IS NULL",
            token_digest(token),
        )


async def revoke_all_sessions(role: str, principal_id: str, except_token: str | None = None, conn=None) -> None:
    sql = """
        UPDATE auth_sessions SET revoked_at = NOW()
        WHERE role = $1 AND principal_id = $2 AND revoked_at IS NULL
          AND ($3::TEXT IS NULL OR token_hash <> $3)
    """
    keep = token_digest(except_token) if except_token else None
    if conn is not None:
        await conn.execute(sql, role, principal_id, keep)
        return
    async with get_conn() as c:
        await c.execute(sql, role, principal_id, keep)


async def purge_expired_sessions() -> int:
    async with get_conn() as conn:
        result = await conn.execute(
            """
            DELETE FROM auth_sessions
            WHERE expires_at < NOW() - INTERVAL '1 day'
               OR revoked_at < NOW() - INTERVAL '1 day'
            """
        )
    return int(result.split()[-1])


async def _load_principal(token: str) -> Principal | None:
    async with get_conn() as conn:
        row = await conn.fetchrow(
            """
            SELECT s.role, s.principal_id, s.last_seen_at, s.expires_at,
                   s.must_change_password,
                   COALESCE(st.name, t.name, c.room_number,
                            CASE WHEN s.role = 'admin' THEN 'Administrator' END,
                            s.principal_id) AS display_name
            FROM auth_sessions s
            LEFT JOIN students   st ON s.role = 'student'   AND st.student_id  = s.principal_id
            LEFT JOIN teachers   t  ON s.role = 'teacher'   AND t.teacher_id   = s.principal_id
            LEFT JOIN classrooms c  ON s.role = 'classroom' AND c.classroom_id = s.principal_id
            WHERE s.token_hash = $1 AND s.revoked_at IS NULL
            """,
            token_digest(token),
        )
        if not row:
            return None

        now = datetime.now(timezone.utc)
        if row["expires_at"] <= now or now - row["last_seen_at"] > _idle_window(row["role"]):
            await conn.execute(
                "UPDATE auth_sessions SET revoked_at = NOW() WHERE token_hash = $1",
                token_digest(token),
            )
            return None

        # Throttle last-seen writes to once a minute per session.
        if now - row["last_seen_at"] > timedelta(seconds=60):
            await conn.execute(
                "UPDATE auth_sessions SET last_seen_at = NOW() WHERE token_hash = $1",
                token_digest(token),
            )

    return Principal(
        role=row["role"],
        user_id=row["principal_id"],
        name=row["display_name"],
        token=token,
        must_change_password=bool(row["must_change_password"]),
    )


# ─────────────────────────────────────────────
# DEPENDENCIES
# ─────────────────────────────────────────────

# Endpoints a user may still reach while a password change is pending.
_PASSWORD_CHANGE_ALLOWLIST = {"/auth/me", "/auth/session", "/auth/logout", "/auth/change-password"}


async def current_principal(request: Request) -> Principal:
    token = request.cookies.get(cfg.session_cookie)
    if not token or len(token) > 128:
        raise HTTPException(status_code=401, detail="Sign in required.")

    principal = await _load_principal(token)
    if principal is None:
        raise HTTPException(status_code=401, detail="Session expired. Sign in again.")

    if request.method in UNSAFE_METHODS and not csrf_valid(token, request.headers.get("x-csrf-token")):
        await audit("csrf_rejected", principal.user_id, None,
                    {"path": request.url.path, "role": principal.role}, request)
        raise HTTPException(status_code=403, detail="Security token missing or invalid. Reload the page.")

    if principal.must_change_password and request.url.path not in _PASSWORD_CHANGE_ALLOWLIST:
        raise HTTPException(status_code=403, detail="password_change_required")

    request.state.principal = principal
    return principal


def require(*roles: str):
    """Dependency factory: allow only the given roles (admin is never implied)."""
    unknown = set(roles) - ROLES
    if unknown:
        raise ValueError(f"Unknown roles: {unknown}")
    allowed = frozenset(roles)

    async def _dep(request: Request, principal: Principal = Depends(current_principal)) -> Principal:
        if principal.role not in allowed:
            await audit("access_denied", principal.user_id, None,
                        {"path": request.url.path, "role": principal.role}, request)
            raise HTTPException(status_code=403, detail="You do not have access to this resource.")
        return principal

    return _dep


# ─────────────────────────────────────────────
# OWNERSHIP CHECKS
# ─────────────────────────────────────────────

def forbid() -> HTTPException:
    return HTTPException(status_code=403, detail="You do not have access to this resource.")


def assert_self(principal: Principal, user_id: str) -> None:
    """Students/teachers may only address their own records; admins any."""
    if principal.is_admin:
        return
    if principal.user_id != user_id:
        raise forbid()


async def teaches(teacher_id: str, course_id: str | None) -> bool:
    if not course_id:
        return False
    async with get_conn() as conn:
        return bool(await conn.fetchval(
            "SELECT 1 FROM course_teachers WHERE teacher_id = $1 AND course_id = $2",
            teacher_id, course_id,
        ))


async def assert_course_access(principal: Principal, course_id: str) -> None:
    if principal.is_admin:
        return
    if principal.role == "teacher" and await teaches(principal.user_id, course_id):
        return
    raise forbid()


async def assert_classroom_access(principal: Principal, classroom_id: str) -> None:
    if principal.role in {"admin", "teacher"}:
        return
    if principal.role == "classroom" and principal.user_id == classroom_id:
        return
    raise forbid()


async def lecture_context(lecture_id: int) -> dict | None:
    async with get_conn() as conn:
        row = await conn.fetchrow(
            "SELECT lecture_id, course_id, classroom_id, status FROM lecture_sessions WHERE lecture_id = $1",
            lecture_id,
        )
    return dict(row) if row else None


async def assert_lecture_access(principal: Principal, lecture_id: int) -> dict:
    """Teacher of the course, the classroom device it runs in, or admin."""
    ctx = await lecture_context(lecture_id)
    if ctx is None:
        # Same answer as "forbidden" for non-admins, so IDs cannot be probed.
        if principal.is_admin:
            raise HTTPException(status_code=404, detail="Lecture not found.")
        raise forbid()
    if principal.is_admin:
        return ctx
    if principal.role == "teacher" and await teaches(principal.user_id, ctx["course_id"]):
        return ctx
    if principal.role == "classroom" and principal.user_id == ctx["classroom_id"]:
        return ctx
    raise forbid()


async def to_thread(fn, *args):
    """Run CPU-heavy work (hashing) off the event loop."""
    return await asyncio.to_thread(fn, *args)
