"""
AttendX — CLI entry point.

Usage:
    python main.py db                                   Run schema migrations
    python main.py server                               Start the API + web UI
    python main.py register                             Face registration terminal
    python main.py recognize [--classroom CR-2113]      Start recognition for a classroom
    python main.py set-password --role admin --id admin Set a password interactively (recovery)
    python main.py encrypt-faces                        Encrypt legacy plaintext face templates
"""

import asyncio
import getpass
import logging
import os
import sys


# ── Load .env automatically so VS Code terminal env injection is not needed ──
def _load_dotenv():
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if not os.path.exists(env_path):
        return
    with open(env_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key   = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:   # don't overwrite real env vars
                os.environ[key] = value


_load_dotenv()
# ─────────────────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


def _with_pool(coro_factory):
    from core.database import init_pool, close_pool

    async def _run():
        await init_pool()
        try:
            await coro_factory()
        finally:
            await close_pool()

    asyncio.run(_run())


def cmd_db():
    from migrations.schema import run_migrations

    async def _run():
        await run_migrations()
        print("Schema migration complete.")

    _with_pool(_run)


def cmd_register():
    from registration.register_student import register_student
    _with_pool(register_student)


def cmd_recognize():
    import argparse
    from core.security import is_valid_id

    parser = argparse.ArgumentParser(description="Face Attendance Recognition Engine")
    parser.add_argument(
        "--classroom",
        default=os.getenv("CLASSROOM_ID", "CR-2113"),
        help="Classroom ID to monitor (default: CR-2113, env: CLASSROOM_ID)",
    )
    args, _ = parser.parse_known_args(sys.argv[2:])
    if not is_valid_id(args.classroom):
        print("Invalid classroom ID.")
        sys.exit(2)

    from recognition.recognizer import main
    asyncio.run(main(args.classroom))


def cmd_server():
    import argparse
    import uvicorn
    from config.settings import api as api_cfg

    parser = argparse.ArgumentParser(description="AttendX API Server")
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Enable auto-reload (not recommended for Windows camera workflows).",
    )
    args, _ = parser.parse_known_args(sys.argv[2:])

    reload_enabled = args.reload or os.getenv("ATTENDX_RELOAD", "").lower() in {"1", "true", "yes"}

    uvicorn.run(
        "api.server:app",
        host=api_cfg.host,
        port=api_cfg.port,
        reload=reload_enabled,
        log_level="info",
        server_header=False,
        proxy_headers=False,
    )


def cmd_set_password():
    import argparse
    from core.security import hash_secret, is_valid_id, password_problems

    parser = argparse.ArgumentParser(description="Set an account password (local recovery)")
    parser.add_argument("--role", required=True, choices=["admin", "teacher", "student"])
    parser.add_argument("--id", required=True, dest="user_id")
    args, _ = parser.parse_known_args(sys.argv[2:])
    if not is_valid_id(args.user_id):
        print("Invalid ID.")
        sys.exit(2)

    password = getpass.getpass("New password: ")
    if password != getpass.getpass("Repeat password: "):
        print("Passwords do not match.")
        sys.exit(1)
    problems = password_problems(password, args.user_id)
    if problems:
        print("Rejected:\n  - " + "\n  - ".join(problems))
        sys.exit(1)

    async def _run():
        from core.database import transaction
        pw_hash = await asyncio.to_thread(hash_secret, password)
        async with transaction() as conn:
            await conn.execute(
                """
                INSERT INTO login_credentials (role, principal_id, password_hash, must_change_password, updated_at)
                VALUES ($1, $2, $3, FALSE, NOW())
                ON CONFLICT (role, principal_id) DO UPDATE
                SET password_hash = EXCLUDED.password_hash, must_change_password = FALSE,
                    temp_expires_at = NULL, failed_attempts = 0, locked_until = NULL, updated_at = NOW()
                """,
                args.role, args.user_id, pw_hash,
            )
            await conn.execute(
                "UPDATE auth_sessions SET revoked_at = NOW() WHERE role = $1 AND principal_id = $2 AND revoked_at IS NULL",
                args.role, args.user_id,
            )
            await conn.execute(
                "INSERT INTO audit_log (event_type, actor_id, target_id, detail) "
                "VALUES ('password_set_cli', 'local_console', $1, jsonb_build_object('role', $2::TEXT))",
                args.user_id, args.role,
            )
        print(f"Password set for {args.role} '{args.user_id}'. Existing sessions were signed out.")

    _with_pool(_run)


def cmd_encrypt_faces():
    from core.database import transaction
    from core.security import encrypt_face_template, is_encrypted_template

    async def _run():
        migrated = 0
        async with transaction() as conn:
            rows = await conn.fetch(
                "SELECT student_id, face_encoding FROM students WHERE face_encoding IS NOT NULL FOR UPDATE"
            )
            for row in rows:
                blob = bytes(row["face_encoding"])
                if is_encrypted_template(blob):
                    continue
                await conn.execute(
                    "UPDATE students SET face_encoding = $1 WHERE student_id = $2",
                    encrypt_face_template(row["student_id"], blob), row["student_id"],
                )
                migrated += 1
        print(f"Encrypted {migrated} legacy face template(s); {len(rows) - migrated} already encrypted.")

    _with_pool(_run)


COMMANDS = {
    "db":            cmd_db,
    "register":      cmd_register,
    "recognize":     cmd_recognize,
    "server":        cmd_server,
    "set-password":  cmd_set_password,
    "encrypt-faces": cmd_encrypt_faces,
}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(__doc__)
        print("Available commands:", ", ".join(COMMANDS))
        sys.exit(1)

    COMMANDS[sys.argv[1]]()
