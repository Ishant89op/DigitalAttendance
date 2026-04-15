"""
Smart Digital Attendance System — CLI entry point.

Usage:
    python main.py db                           — Run schema migrations
    python main.py register                     — Start face registration terminal
    python main.py recognize                    — Start recognition (CR-2113 default)
    python main.py recognize --classroom CR-LAB — Start for a specific classroom
    python main.py server                       — Start the FastAPI server
"""

import asyncio
import logging
import sys
import os

# ── Load .env automatically so VS Code terminal env injection is not needed ──
def _load_dotenv():
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if not os.path.exists(env_path):
        return
    with open(env_path) as f:
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


def cmd_db():
    from core.database import init_pool, close_pool
    from migrations.schema import run_migrations

    async def _run():
        await init_pool()
        await run_migrations()
        await close_pool()
        print("Schema migration complete.")

    asyncio.run(_run())


def cmd_register():
    from core.database import init_pool, close_pool
    from registration.register_student import register_student

    async def _run():
        await init_pool()
        await register_student()
        await close_pool()

    asyncio.run(_run())


def cmd_recognize():
    import argparse
    parser = argparse.ArgumentParser(description="Face Attendance Recognition Engine")
    parser.add_argument(
        "--classroom",
        default=os.getenv("CLASSROOM_ID", "CR-2113"),
        help="Classroom ID to monitor (default: CR-2113, env: CLASSROOM_ID)",
    )
    args, _ = parser.parse_known_args(sys.argv[2:])

    from recognition.recognizer import main
    asyncio.run(main(args.classroom))


def cmd_server():
    import argparse
    import uvicorn

    parser = argparse.ArgumentParser(description="AttendX API Server")
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Enable auto-reload (not recommended for Windows camera workflows).",
    )
    args, _ = parser.parse_known_args(sys.argv[2:])

    reload_enabled = args.reload or os.getenv("ATTENDX_RELOAD", "").lower() in {
        "1", "true", "yes",
    }

    uvicorn.run(
        "api.server:app",
        host="0.0.0.0",
        port=8000,
        reload=reload_enabled,
        log_level="info",
    )


COMMANDS = {
    "db":        cmd_db,
    "register":  cmd_register,
    "recognize": cmd_recognize,
    "server":    cmd_server,
}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(__doc__)
        print("Available commands:", ", ".join(COMMANDS))
        sys.exit(1)

    COMMANDS[sys.argv[1]]()
