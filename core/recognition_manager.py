"""
Recognition process manager — Windows-compatible with detached console.

On Windows, spawning cv2.imshow inside a piped subprocess fails because
the child process has no desktop context. The fix is to use subprocess.Popen
with CREATE_NEW_CONSOLE so it gets its own visible terminal window with full
desktop access — the camera and GUI work correctly.

On Linux/Mac the old asyncio approach works fine so we keep that as fallback.
"""

import asyncio
import logging
import os
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

IS_WINDOWS = sys.platform == "win32"

# classroom_id → process handle (subprocess.Popen on Windows, asyncio.Process on Linux)
_processes: dict = {}


async def start_recognition_process(classroom_id: str) -> bool:
    """
    Spawn recognition engine for a classroom.
    On Windows: opens a new console window (so camera/GUI works).
    On Linux/Mac: background asyncio subprocess.
    Returns True if started, False if already running.
    """
    # Check if already running
    if classroom_id in _processes:
        proc = _processes[classroom_id]
        if IS_WINDOWS:
            if proc.poll() is None:   # still running
                logger.info("Recognition already running for %s", classroom_id)
                return False
        else:
            if proc.returncode is None:
                logger.info("Recognition already running for %s", classroom_id)
                return False
        del _processes[classroom_id]

    project_root = Path(__file__).parent.parent

    cmd = [
        sys.executable,
        str(project_root / "main.py"),
        "recognize",
        "--classroom", classroom_id,
    ]

    env = os.environ.copy()
    env["CLASSROOM_ID"] = classroom_id

    try:
        if IS_WINDOWS:
            # CREATE_NO_WINDOW = 0x08000000  — gives the child its own invisible session
            # so cv2.imshow and VideoCapture work properly without a console window
            CREATE_NO_WINDOW = 0x08000000

            proc = subprocess.Popen(
                cmd,
                cwd=str(project_root),
                env=env,
                creationflags=CREATE_NO_WINDOW,
                # Don't pipe stdout — let it print to its own console window
            )
            _processes[classroom_id] = proc
            logger.info(
                "Recognition process started for %s (pid=%d) — "
                "in background.",
                classroom_id, proc.pid
            )
        else:
            # Linux / Mac — asyncio subprocess works fine
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=str(project_root),
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            _processes[classroom_id] = proc
            logger.info(
                "Recognition process started for %s (pid=%d)", classroom_id, proc.pid
            )
            asyncio.create_task(_stream_logs(classroom_id, proc))

        return True

    except Exception as e:
        logger.error("Failed to start recognition process: %s", e)
        return False


async def stop_recognition_process(classroom_id: str) -> bool:
    """Kill the recognition process. Returns True if killed."""
    proc = _processes.get(classroom_id)
    if not proc:
        return False

    try:
        if IS_WINDOWS:
            if proc.poll() is not None:
                del _processes[classroom_id]
                return False
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
        else:
            if proc.returncode is not None:
                del _processes[classroom_id]
                return False
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()

        del _processes[classroom_id]
        logger.info("Recognition process stopped for %s", classroom_id)
        return True

    except Exception as e:
        logger.error("Error stopping recognition process: %s", e)
        return False


async def stop_all() -> None:
    """Stop all running recognition processes — called at server shutdown."""
    for classroom_id in list(_processes.keys()):
        await stop_recognition_process(classroom_id)


def is_running(classroom_id: str) -> bool:
    """Check if recognition is currently active for a classroom."""
    proc = _processes.get(classroom_id)
    if proc is None:
        return False
    if IS_WINDOWS:
        return proc.poll() is None
    return proc.returncode is None


async def _stream_logs(classroom_id: str, proc) -> None:
    """Stream subprocess stdout to server logger (Linux/Mac only)."""
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
    logger.info("Recognition process for %s exited (code=%s)",
                classroom_id, proc.returncode)
