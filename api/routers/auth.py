"""Authentication endpoints for role-based login."""

import os
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from core.database import get_conn

router = APIRouter(prefix="/auth", tags=["Auth"])


DEFAULT_ADMIN_ID = os.getenv("ADMIN_LOGIN_ID", "admin")
DEFAULT_ADMIN_PASSWORD = os.getenv("ADMIN_LOGIN_PASSWORD", "admin123")


class LoginRequest(BaseModel):
    role: str
    user_id: str
    password: str


class ChangePasswordRequest(BaseModel):
    role: str
    user_id: str
    current_password: str
    new_password: str


class ResetPasswordRequest(BaseModel):
    admin_id: str
    admin_password: str
    target_role: str
    target_user_id: str
    new_password: str


def _normalize_role(value: str) -> str:
    return value.strip().lower()


def _validate_password_strength(password: str) -> None:
    if len(password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters.")


@router.post("/login", summary="Role-based login with password")
async def login(req: LoginRequest):
    role = _normalize_role(req.role)
    user_id = req.user_id.strip()
    password = req.password

    if not user_id:
        raise HTTPException(status_code=400, detail="User ID is required.")
    if not password:
        raise HTTPException(status_code=400, detail="Password is required.")

    async with get_conn() as conn:
        if role == "student":
            row = await conn.fetchrow(
                """
                SELECT s.student_id AS user_id, s.name
                FROM students s
                JOIN login_credentials lc
                  ON lc.role = 'student'
                 AND lc.principal_id = s.student_id
                WHERE s.student_id = $1
                  AND lc.password_hash = encode(digest($2::TEXT, 'sha256'), 'hex')
                LIMIT 1
                """,
                user_id,
                password,
            )
        elif role == "teacher":
            row = await conn.fetchrow(
                """
                SELECT t.teacher_id AS user_id, t.name
                FROM teachers t
                JOIN login_credentials lc
                  ON lc.role = 'teacher'
                 AND lc.principal_id = t.teacher_id
                WHERE t.teacher_id = $1
                  AND lc.password_hash = encode(digest($2::TEXT, 'sha256'), 'hex')
                LIMIT 1
                """,
                user_id,
                password,
            )
        elif role == "admin":
            row = await conn.fetchrow(
                """
                SELECT lc.principal_id AS user_id
                FROM login_credentials lc
                WHERE lc.role = 'admin'
                  AND lc.principal_id = $1
                  AND lc.password_hash = encode(digest($2::TEXT, 'sha256'), 'hex')
                LIMIT 1
                """,
                user_id,
                password,
            )
            if not row and user_id == DEFAULT_ADMIN_ID and password == DEFAULT_ADMIN_PASSWORD:
                row = {"user_id": DEFAULT_ADMIN_ID}

            if row:
                return {
                    "role": "admin",
                    "user_id": row["user_id"],
                    "name": "Administrator",
                }
        else:
            raise HTTPException(status_code=400, detail="Unsupported role.")

    if not row:
        raise HTTPException(status_code=401, detail="Invalid ID or password.")

    return {
        "role": role,
        "user_id": row["user_id"],
        "name": row["name"],
    }


@router.post("/change-password", summary="Change password for current user")
async def change_password(req: ChangePasswordRequest):
    role = _normalize_role(req.role)
    user_id = req.user_id.strip()
    current_password = req.current_password
    new_password = req.new_password

    if role not in {"student", "teacher", "admin"}:
        raise HTTPException(status_code=400, detail="Unsupported role.")
    if not user_id or not current_password or not new_password:
        raise HTTPException(status_code=400, detail="Missing required fields.")
    _validate_password_strength(new_password)

    async with get_conn() as conn:
        old_hash = await conn.fetchval(
            """
            SELECT password_hash
            FROM login_credentials
            WHERE role = $1
              AND principal_id = $2
              AND password_hash = encode(digest($3::TEXT, 'sha256'), 'hex')
            """,
            role,
            user_id,
            current_password,
        )
        if not old_hash:
            raise HTTPException(status_code=401, detail="Current password is incorrect.")

        await conn.execute(
            """
            UPDATE login_credentials
            SET password_hash = encode(digest($3::TEXT, 'sha256'), 'hex'),
                updated_at = NOW()
            WHERE role = $1 AND principal_id = $2
            """,
            role,
            user_id,
            new_password,
        )

    return {"message": "Password updated successfully."}


@router.post("/reset-password", summary="Admin reset password for any role")
async def reset_password(req: ResetPasswordRequest):
    admin_id = req.admin_id.strip()
    admin_password = req.admin_password
    target_role = _normalize_role(req.target_role)
    target_user_id = req.target_user_id.strip()
    new_password = req.new_password

    if target_role not in {"student", "teacher", "admin"}:
        raise HTTPException(status_code=400, detail="Unsupported target role.")
    if not admin_id or not admin_password or not target_user_id or not new_password:
        raise HTTPException(status_code=400, detail="Missing required fields.")
    _validate_password_strength(new_password)

    async with get_conn() as conn:
        admin_ok = await conn.fetchval(
            """
            SELECT 1
            FROM login_credentials
            WHERE role = 'admin'
              AND principal_id = $1
              AND password_hash = encode(digest($2::TEXT, 'sha256'), 'hex')
            LIMIT 1
            """,
            admin_id,
            admin_password,
        )

        if not admin_ok and not (
            admin_id == DEFAULT_ADMIN_ID and admin_password == DEFAULT_ADMIN_PASSWORD
        ):
            raise HTTPException(status_code=401, detail="Admin authentication failed.")

        if target_role == "student":
            exists = await conn.fetchval(
                "SELECT 1 FROM students WHERE student_id = $1 LIMIT 1",
                target_user_id,
            )
        elif target_role == "teacher":
            exists = await conn.fetchval(
                "SELECT 1 FROM teachers WHERE teacher_id = $1 LIMIT 1",
                target_user_id,
            )
        else:
            exists = 1

        if not exists:
            raise HTTPException(status_code=404, detail="Target user not found.")

        await conn.execute(
            """
            INSERT INTO login_credentials (role, principal_id, password_hash)
            VALUES ($1, $2, encode(digest($3::TEXT, 'sha256'), 'hex'))
            ON CONFLICT (role, principal_id) DO UPDATE
            SET password_hash = EXCLUDED.password_hash,
                updated_at = NOW()
            """,
            target_role,
            target_user_id,
            new_password,
        )

    return {
        "message": "Password reset successful.",
        "target_role": target_role,
        "target_user_id": target_user_id,
    }
