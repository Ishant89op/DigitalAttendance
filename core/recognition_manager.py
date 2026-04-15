"""
Recognition process manager with DB-backed session tracking.

The API may restart independently of the camera process on Windows, so an
in-memory registry alone is not enough to know whether recognition is active.
We persist the launched PID in the database and verify that PID when asked.
"""

import asyncio
import logging
import os
import shlex
import signal
import subprocess
import sys
import time
from pathlib import Path

from core.database import get_conn, transaction

logger = logging.getLogger(__name__)

IS_WINDOWS = sys.platform == "win32"
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# classroom_id -> process handle (subprocess.Popen on Windows, asyncio.Process elsewhere)
_processes: dict[str, subprocess.Popen | asyncio.subprocess.Process] = {}


def build_manual_command(classroom_id: str) -> str:
    """Return a copy-pasteable command to start recognition manually."""
    script_path = str(PROJECT_ROOT / "main.py")
    if IS_WINDOWS:
        return f'python "{script_path}" recognize --classroom {classroom_id}'
    return shlex.join(["python3", script_path, "recognize", "--classroom", classroom_id])


def is_running(classroom_id: str) -> bool:
    """Fast in-memory check used as a first pass before consulting the DB."""
    proc = _processes.get(classroom_id)
    if proc is None:
        return False
    if IS_WINDOWS:
        return proc.poll() is None
    return proc.returncode is None


async def is_running_async(classroom_id: str) -> bool:
    """
    Check whether recognition is active for a classroom.

    This validates both the in-memory process registry and the persisted PID in
    recognition_sessions, cleaning up stale rows when needed.
    """
    if is_running(classroom_id):
        proc = _processes[classroom_id]
        await _upsert_session(classroom_id, _get_pid(proc))
        return True

    _processes.pop(classroom_id, None)

    async with get_conn() as conn:
        row = await conn.fetchrow(
            """
            SELECT pid
            FROM recognition_sessions
            WHERE classroom_id = $1
            """,
            classroom_id,
        )

    if not row:
        return False

    pid = int(row["pid"])
    if _pid_alive(pid):
        return True

    await _delete_session(classroom_id)
    return False


async def start_recognition_process(classroom_id: str) -> bool:
    """
    Spawn recognition for a classroom.

    Returns True only when a new process was launched. If a healthy process
    already exists, returns False.
    """
    if await is_running_async(classroom_id):
        logger.info("Recognition already running for %s", classroom_id)
        return False

    python_exe = _resolve_python_executable()
    cmd = [
        str(python_exe),
        str(PROJECT_ROOT / "main.py"),
        "recognize",
        "--classroom",
        classroom_id,
    ]
    env = os.environ.copy()
    env["CLASSROOM_ID"] = classroom_id
    env["PYTHONUNBUFFERED"] = "1"

    try:
        if IS_WINDOWS:
            proc = subprocess.Popen(
                cmd,
                cwd=str(PROJECT_ROOT),
                env=env,
                creationflags=0x00000010,  # CREATE_NEW_CONSOLE
            )
        else:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=str(PROJECT_ROOT),
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            asyncio.create_task(_stream_logs(classroom_id, proc))

        _processes[classroom_id] = proc
        await _upsert_session(classroom_id, _get_pid(proc))

        logger.info(
            "Recognition process started for %s (pid=%d) using %s",
            classroom_id,
            _get_pid(proc),
            python_exe,
        )
        return True
    except Exception as exc:
        logger.error("Failed to start recognition process for %s: %s", classroom_id, exc)
        await _delete_session(classroom_id)
        return False


async def stop_recognition_process(classroom_id: str) -> bool:
    """Stop recognition for a classroom, using either a live handle or stored PID."""
    proc = _processes.get(classroom_id)
    if proc is not None:
        try:
            if IS_WINDOWS:
                if proc.poll() is None:
                    proc.terminate()
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait(timeout=5)
            else:
                if proc.returncode is None:
                    proc.terminate()
                    try:
                        await asyncio.wait_for(proc.wait(), timeout=5.0)
                    except asyncio.TimeoutError:
                        proc.kill()
                        await proc.wait()
        except Exception as exc:
            logger.warning("Could not stop in-memory recognition process for %s: %s", classroom_id, exc)
        finally:
            _processes.pop(classroom_id, None)

    async with get_conn() as conn:
        row = await conn.fetchrow(
            """
            SELECT pid
            FROM recognition_sessions
            WHERE classroom_id = $1
            """,
            classroom_id,
        )

    stopped = False
    if row:
        pid = int(row["pid"])
        stopped = _terminate_pid(pid) or stopped

    await _delete_session(classroom_id)
    logger.info("Recognition process stopped for %s", classroom_id)
    return stopped or proc is not None


async def stop_all() -> None:
    """Stop all known recognition sessions, including persisted ones."""
    async with get_conn() as conn:
        rows = await conn.fetch("SELECT classroom_id FROM recognition_sessions")
    classroom_ids = {row["classroom_id"] for row in rows}
    classroom_ids.update(_processes.keys())

    for classroom_id in list(classroom_ids):
        await stop_recognition_process(classroom_id)


async def cleanup_dead_sessions() -> int:
    """Remove persisted recognition sessions whose PIDs no longer exist."""
    async with get_conn() as conn:
        rows = await conn.fetch("SELECT classroom_id, pid FROM recognition_sessions")

    removed = 0
    for row in rows:
        if not _pid_alive(int(row["pid"])):
            await _delete_session(row["classroom_id"])
            removed += 1

    if removed:
        logger.info("Cleaned up %d stale recognition session record(s).", removed)
    return removed


async def _upsert_session(classroom_id: str, pid: int) -> None:
    async with transaction() as conn:
        await conn.execute(
            """
            INSERT INTO recognition_sessions (classroom_id, pid)
            VALUES ($1, $2)
            ON CONFLICT (classroom_id) DO UPDATE
            SET pid = EXCLUDED.pid,
                updated_at = NOW()
            """,
            classroom_id,
            pid,
        )


async def _delete_session(classroom_id: str) -> None:
    async with transaction() as conn:
        await conn.execute(
            "DELETE FROM recognition_sessions WHERE classroom_id = $1",
            classroom_id,
        )


def _resolve_python_executable() -> Path:
    candidates: list[Path] = []
    if IS_WINDOWS:
        candidates.extend([
            PROJECT_ROOT / ".venv" / "Scripts" / "python.exe",
            PROJECT_ROOT / "venv" / "Scripts" / "python.exe",
        ])
    else:
        candidates.extend([
            PROJECT_ROOT / ".venv" / "bin" / "python",
            PROJECT_ROOT / "venv" / "bin" / "python",
        ])
    candidates.append(Path(sys.executable))

    for candidate in candidates:
        if candidate.exists():
            return candidate
    return Path(sys.executable)


def _get_pid(proc: subprocess.Popen | asyncio.subprocess.Process) -> int:
    return int(proc.pid)


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    else:
        return True


def _terminate_pid(pid: int) -> bool:
    if not _pid_alive(pid):
        return False

    try:
        if IS_WINDOWS:
            result = subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True,
                text=True,
                check=False,
            )
            return result.returncode == 0

        os.kill(pid, signal.SIGTERM)
        deadline = time.time() + 5
        while time.time() < deadline:
            if not _pid_alive(pid):
                return True
            time.sleep(0.1)

        os.kill(pid, signal.SIGKILL)
        return not _pid_alive(pid)
    except Exception as exc:
        logger.warning("Failed to terminate PID %s: %s", pid, exc)
        return False


async def _stream_logs(classroom_id: str, proc: asyncio.subprocess.Process) -> None:
    """Stream subprocess stdout to the API logger on non-Windows platforms."""
    try:
        while True:
            line = await proc.stdout.readline()
            if not line:
                break
            decoded = line.decode("utf-8", errors="replace").rstrip()
            if decoded:
                logger.info("[%s] %s", classroom_id, decoded)
    except Exception:
        pass
    finally:
        _processes.pop(classroom_id, None)
        await _delete_session(classroom_id)
        logger.info(
            "Recognition process for %s exited (code=%s)",
            classroom_id,
            proc.returncode,
        )
