"""Authentication endpoints: sign-in, sessions, password lifecycle."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from config.settings import security as sec_cfg
from core.auth import (
    Principal,
    audit,
    clear_session_cookie,
    create_session,
    current_principal,
    enforce_login_rate,
    require,
    revoke_all_sessions,
    revoke_session,
    to_thread,
)
from core.database import get_conn, transaction
from core.security import (
    ID_PATTERN,
    csrf_for,
    generate_temporary_password,
    hash_secret,
    is_valid_id,
    needs_rehash,
    password_problems,
    verify_secret,
)

router = APIRouter(prefix="/auth", tags=["Auth"])

GENERIC_LOGIN_ERROR = "Invalid ID or password."


class LoginRequest(BaseModel):
    role: Literal["student", "teacher", "admin", "classroom"]
    user_id: str = Field(min_length=1, max_length=32)
    password: str = Field(min_length=1, max_length=sec_cfg.password_max_length)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=sec_cfg.password_max_length)
    new_password: str = Field(min_length=1, max_length=sec_cfg.password_max_length)


class IssuePasswordRequest(BaseModel):
    target_role: Literal["student", "teacher", "admin"]
    target_user_id: str = Field(pattern=ID_PATTERN)


def _lock_duration(failed_attempts: int) -> timedelta:
    over = max(0, failed_attempts - sec_cfg.lockout_threshold)
    seconds = min(sec_cfg.lockout_base_seconds * (2 ** over), sec_cfg.lockout_max_seconds)
    return timedelta(seconds=seconds)


async def _principal_exists(conn, role: str, user_id: str) -> bool:
    if role == "student":
        return bool(await conn.fetchval("SELECT 1 FROM students WHERE student_id = $1", user_id))
    if role == "teacher":
        return bool(await conn.fetchval("SELECT 1 FROM teachers WHERE teacher_id = $1", user_id))
    return True


async def _login_account(request: Request, role: str, user_id: str, password: str) -> tuple[bool, str]:
    """Verify a student/teacher/admin password. Returns (must_change, name)."""
    now = datetime.now(timezone.utc)
    async with get_conn() as conn:
        row = await conn.fetchrow(
            """
            SELECT password_hash, failed_attempts, locked_until,
                   must_change_password, temp_expires_at
            FROM login_credentials
            WHERE role = $1 AND principal_id = $2
            """,
            role, user_id,
        )
        exists = row is not None and await _principal_exists(conn, role, user_id)

    if row and row["locked_until"] and row["locked_until"] > now:
        # Burn the same CPU as a real check so lock state is not a timing oracle.
        await to_thread(verify_secret, password, None)
        await audit("login_locked", user_id, None, {"role": role}, request)
        raise HTTPException(
            status_code=429,
            detail="Account temporarily locked after repeated failures. Try again later.",
        )

    stored = row["password_hash"] if (row and exists) else None
    ok = await to_thread(verify_secret, password, stored)

    if ok and row["temp_expires_at"] and row["temp_expires_at"] < now:
        ok = False
        await audit("login_temp_password_expired", user_id, None, {"role": role}, request)

    if not ok:
        if row:
            attempts = int(row["failed_attempts"] or 0) + 1
            locked_until = now + _lock_duration(attempts) if attempts >= sec_cfg.lockout_threshold else None
            async with get_conn() as conn:
                await conn.execute(
                    """
                    UPDATE login_credentials
                    SET failed_attempts = $3, locked_until = COALESCE($4, locked_until)
                    WHERE role = $1 AND principal_id = $2
                    """,
                    role, user_id, attempts, locked_until,
                )
            if locked_until:
                await audit("account_locked", user_id, None, {"role": role, "attempts": attempts}, request)
        await audit("login_failed", user_id, None, {"role": role}, request)
        raise HTTPException(status_code=401, detail=GENERIC_LOGIN_ERROR)

    new_hash = await to_thread(hash_secret, password) if needs_rehash(stored) else None
    async with get_conn() as conn:
        await conn.execute(
            """
            UPDATE login_credentials
            SET failed_attempts = 0, locked_until = NULL, last_login_at = NOW(),
                password_hash = COALESCE($3, password_hash)
            WHERE role = $1 AND principal_id = $2
            """,
            role, user_id, new_hash,
        )
        if role == "student":
            name = await conn.fetchval("SELECT name FROM students WHERE student_id = $1", user_id)
        elif role == "teacher":
            name = await conn.fetchval("SELECT name FROM teachers WHERE teacher_id = $1", user_id)
        else:
            name = "Administrator"
    return bool(row["must_change_password"]), name or user_id


async def _login_classroom(request: Request, classroom_id: str, pin: str) -> str:
    now = datetime.now(timezone.utc)
    async with get_conn() as conn:
        row = await conn.fetchrow(
            """
            SELECT room_number, access_pin_hash, pin_failed_attempts, pin_locked_until
            FROM classrooms WHERE classroom_id = $1
            """,
            classroom_id,
        )

    if row and row["pin_locked_until"] and row["pin_locked_until"] > now:
        await to_thread(verify_secret, pin, None)
        raise HTTPException(
            status_code=429,
            detail="Device temporarily locked after repeated failures. Try again later.",
        )

    ok = await to_thread(verify_secret, pin, row["access_pin_hash"] if row else None)
    if not ok:
        if row:
            attempts = int(row["pin_failed_attempts"] or 0) + 1
            locked_until = now + _lock_duration(attempts) if attempts >= sec_cfg.lockout_threshold else None
            async with get_conn() as conn:
                await conn.execute(
                    """
                    UPDATE classrooms
                    SET pin_failed_attempts = $2, pin_locked_until = COALESCE($3, pin_locked_until)
                    WHERE classroom_id = $1
                    """,
                    classroom_id, attempts, locked_until,
                )
        await audit("classroom_login_failed", classroom_id, None, {}, request)
        raise HTTPException(status_code=401, detail="Invalid classroom ID or PIN.")

    async with get_conn() as conn:
        await conn.execute(
            "UPDATE classrooms SET pin_failed_attempts = 0, pin_locked_until = NULL WHERE classroom_id = $1",
            classroom_id,
        )
    return row["room_number"] or classroom_id


@router.post("/login", summary="Sign in (student, teacher, admin or classroom device)")
async def login(req: LoginRequest, request: Request, response: Response):
    enforce_login_rate(request)
    user_id = req.user_id.strip()
    if not is_valid_id(user_id):
        await to_thread(verify_secret, req.password, None)
        raise HTTPException(status_code=401, detail=GENERIC_LOGIN_ERROR)

    if req.role == "classroom":
        name = await _login_classroom(request, user_id, req.password)
        must_change = False
    else:
        must_change, name = await _login_account(request, req.role, user_id, req.password)

    csrf = await create_session(
        request, response, role=req.role, principal_id=user_id, must_change_password=must_change,
    )
    await audit("login_success", user_id, None, {"role": req.role}, request)
    return {
        "role": req.role,
        "user_id": user_id,
        "name": name,
        "must_change_password": must_change,
        "csrf_token": csrf,
    }


@router.get("/session", summary="Is this browser signed in? (never 401s)")
async def session_status(request: Request):
    try:
        principal = await current_principal(request)
    except HTTPException:
        return {"authenticated": False}
    return {
        "authenticated": True,
        "role": principal.role,
        "must_change_password": principal.must_change_password,
        "csrf_token": csrf_for(principal.token),
    }


@router.get("/me", summary="Current session")
async def me(principal: Principal = Depends(current_principal)):
    return {
        "role": principal.role,
        "user_id": principal.user_id,
        "name": principal.name,
        "must_change_password": principal.must_change_password,
        "csrf_token": csrf_for(principal.token),
    }


@router.post("/logout", summary="End the current session")
async def logout(request: Request, response: Response, principal: Principal = Depends(current_principal)):
    await revoke_session(principal.token)
    clear_session_cookie(request, response)
    await audit("logout", principal.user_id, None, {"role": principal.role}, request)
    return {"message": "Signed out."}


@router.post("/change-password", summary="Change your own password")
async def change_password(
    req: ChangePasswordRequest,
    request: Request,
    response: Response,
    principal: Principal = Depends(current_principal),
):
    if principal.role == "classroom":
        raise HTTPException(status_code=403, detail="Classroom PINs are managed by an admin.")

    async with get_conn() as conn:
        stored = await conn.fetchval(
            "SELECT password_hash FROM login_credentials WHERE role = $1 AND principal_id = $2",
            principal.role, principal.user_id,
        )
    if not await to_thread(verify_secret, req.current_password, stored):
        await audit("password_change_failed", principal.user_id, None, {"role": principal.role}, request)
        raise HTTPException(status_code=401, detail="Current password is incorrect.")

    problems = password_problems(req.new_password, principal.user_id)
    if req.new_password == req.current_password:
        problems.append("New password must be different from the current one.")
    if problems:
        raise HTTPException(status_code=400, detail=" ".join(problems))

    new_hash = await to_thread(hash_secret, req.new_password)
    async with transaction() as conn:
        await conn.execute(
            """
            UPDATE login_credentials
            SET password_hash = $3, must_change_password = FALSE, temp_expires_at = NULL,
                failed_attempts = 0, locked_until = NULL, updated_at = NOW()
            WHERE role = $1 AND principal_id = $2
            """,
            principal.role, principal.user_id, new_hash,
        )
        # Every device is signed out; this one gets a fresh session below.
        await revoke_all_sessions(principal.role, principal.user_id, conn=conn)
        await audit("password_changed", principal.user_id, None, {"role": principal.role}, request, conn=conn)

    csrf = await create_session(request, response, role=principal.role, principal_id=principal.user_id)
    return {"message": "Password updated.", "csrf_token": csrf}


@router.post("/issue-password", summary="Admin: issue a one-time password for an account")
async def issue_password(
    req: IssuePasswordRequest,
    request: Request,
    admin: Principal = Depends(require("admin")),
):
    async with get_conn() as conn:
        if not await _principal_exists(conn, req.target_role, req.target_user_id):
            raise HTTPException(status_code=404, detail="Account not found.")

    temp = generate_temporary_password()
    temp_hash = await to_thread(hash_secret, temp)
    expires = datetime.now(timezone.utc) + timedelta(hours=sec_cfg.temp_password_ttl_hours)
    async with transaction() as conn:
        await conn.execute(
            """
            INSERT INTO login_credentials
                (role, principal_id, password_hash, must_change_password, temp_expires_at, updated_at)
            VALUES ($1, $2, $3, TRUE, $4, NOW())
            ON CONFLICT (role, principal_id) DO UPDATE
            SET password_hash = EXCLUDED.password_hash,
                must_change_password = TRUE,
                temp_expires_at = EXCLUDED.temp_expires_at,
                failed_attempts = 0, locked_until = NULL, updated_at = NOW()
            """,
            req.target_role, req.target_user_id, temp_hash, expires,
        )
        await revoke_all_sessions(req.target_role, req.target_user_id, conn=conn)
        await audit(
            "password_issued", admin.user_id, req.target_user_id,
            {"target_role": req.target_role}, request, conn=conn,
        )

    return {
        "target_role": req.target_role,
        "target_user_id": req.target_user_id,
        "temporary_password": temp,
        "expires_at": expires.isoformat(),
        "message": "Share this once, privately. The user must set a new password at first sign-in.",
    }
