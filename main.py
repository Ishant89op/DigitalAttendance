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
import os
import sys
from pathlib import Path

try:
    from dotenv import load_dotenv
except ModuleNotFoundError as exc:
    raise SystemExit(
        "Missing project dependencies for this interpreter.\n"
        "Activate the project virtual environment first:\n"
        "  .\\venv\\Scripts\\Activate.ps1\n"
        "Then run:\n"
        "  python main.py register"
    ) from exc

load_dotenv(dotenv_path=Path(__file__).resolve().with_name(".env"), override=False)

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

    # recognizer manages its own threads + async worker internally — call directly
    from recognition.recognizer import main
    main(args.classroom)


def cmd_server():
    import uvicorn
    uvicorn.run(
        "api.server:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
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
