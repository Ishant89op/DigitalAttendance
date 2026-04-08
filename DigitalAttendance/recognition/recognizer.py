"""
Face Recognition Engine — camera preview with GUI auto-detection fallback.

Shows live camera window if OpenCV GUI is available, otherwise runs headless.
To enable the window: pip uninstall opencv-python-headless -y && pip install opencv-python

Run:
    python main.py recognize --classroom CR-2113
"""

import argparse
import asyncio
import logging
import os
import sys
import time
from collections import Counter

import cv2
import numpy as np

from core.database import init_pool, close_pool
from utils.face_utils import get_model, load_known_faces, cosine_match
from attendance.attendance_manager import mark_attendance
from services.lecture_service import get_active_lecture, start_lecture
from config.settings import recog as cfg

logger = logging.getLogger(__name__)

RECOGNITION_BUFFER   = 3
RELOAD_INTERVAL_SECS = 60
WAIT_POLL_SECS       = 3
AUTO_START           = True

# Auto-detect GUI support
def _has_gui():
    try:
        cv2.namedWindow("_test", cv2.WINDOW_NORMAL)
        cv2.destroyWindow("_test")
        return True
    except cv2.error:
        return False

SHOW_WINDOW = _has_gui()
if not SHOW_WINDOW:
    print("  [Note] OpenCV GUI not available — running headless (terminal output only).")
    print("  To enable camera preview window, run:")
    print("    pip uninstall opencv-python-headless -y")
    print("    pip install opencv-python\n")

known_matrix : np.ndarray = np.empty((0, cfg.embedding_dim), dtype=np.float32)
known_names  : list[str]  = []
known_ids    : list[str]  = []
last_reload  : float      = 0.0
last_seen    : dict       = {}
frame_buffer : Counter    = Counter()

_flash_name  : str   = ""
_flash_until : float = 0.0


async def reload_faces_if_needed() -> None:
    global known_matrix, known_names, known_ids, last_reload
    if time.time() - last_reload < RELOAD_INTERVAL_SECS:
        return
    known_matrix, known_names, known_ids = await load_known_faces()
    last_reload = time.time()
    logger.info("Face DB reloaded — %d registered students", len(known_ids))


def on_cooldown(student_id: str) -> bool:
    return (time.time() - last_seen.get(student_id, 0)) < cfg.cooldown_seconds


def _print_status(classroom_id, lecture_id, present_count, enrolled):
    bar = chr(9608) * present_count + chr(9617) * max(0, enrolled - present_count)
    sys.stdout.write(
        f"\r  [{classroom_id}] Lecture #{lecture_id}  "
        f"Present: {present_count}/{enrolled}  [{bar}]   "
    )
    sys.stdout.flush()


def _draw_frame(frame, faces, face_results, classroom_id, lecture_id, present_count, enrolled):
    display = frame.copy()
    h, w = display.shape[:2]

    for i, face in enumerate(faces):
        x1, y1, x2, y2 = [int(v) for v in face.bbox]
        if i < len(face_results) and face_results[i] is not None:
            sid, name, score, was_marked = face_results[i]
            color = (0, 255, 80) if was_marked else (0, 200, 0)
            label = f"{name}  {score:.2f}"
        else:
            color = (0, 60, 220)
            label = "Unknown"
        cv2.rectangle(display, (x1, y1), (x2, y2), color, 2)
        (lw, lh), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 1)
        cv2.rectangle(display, (x1, y1 - lh - 10), (x1 + lw + 6, y1), color, -1)
        cv2.putText(display, label, (x1 + 3, y1 - 5),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 1, cv2.LINE_AA)

    overlay = display.copy()
    cv2.rectangle(overlay, (0, 0), (w, 38), (15, 15, 30), -1)
    cv2.addWeighted(overlay, 0.75, display, 0.25, 0, display)
    pct = int(100 * present_count / enrolled) if enrolled else 0
    cv2.putText(display, f"Room: {classroom_id}", (10, 26),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (180, 180, 180), 1, cv2.LINE_AA)
    lect_txt = f"Lecture #{lecture_id}" if lecture_id else "No active lecture"
    cv2.putText(display, lect_txt, (w // 2 - 65, 26),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (100, 220, 255), 1, cv2.LINE_AA)
    cv2.putText(display, f"Present: {present_count}/{enrolled} ({pct}%)", (w - 230, 26),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (80, 255, 120), 1, cv2.LINE_AA)

    if time.time() < _flash_until and _flash_name:
        cv2.putText(display, f"MARKED  {_flash_name}", (w // 2 - 160, h // 2),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 255, 100), 3, cv2.LINE_AA)

    if not lecture_id:
        cv2.putText(display, "Waiting for lecture to start ...", (w // 2 - 190, h // 2),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.9, (80, 180, 255), 2, cv2.LINE_AA)
    return display


async def run_recognition(classroom_id: str) -> None:
    global last_reload, _flash_name, _flash_until

    last_reload = 0.0
    await reload_faces_if_needed()

    if len(known_ids) == 0:
        logger.warning("No registered faces found. Run 'python main.py register' first.")

    model = get_model()

    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        logger.warning("Camera index 0 failed — trying index 1 ...")
        cap = cv2.VideoCapture(1)
    if not cap.isOpened():
        logger.error("Cannot open camera. Check it is connected and not used by another app.")
        return

    cap.set(cv2.CAP_PROP_FRAME_WIDTH,  640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

    logger.info("=" * 55)
    logger.info("  AttendX Recognition Engine")
    logger.info("  Classroom : %s", classroom_id)
    logger.info("  Students  : %d registered", len(known_ids))
    if SHOW_WINDOW:
        logger.info("  Camera window open — press Q or ESC to quit")
    else:
        logger.info("  Running headless — press Ctrl+C to stop")
    logger.info("=" * 55)

    if SHOW_WINDOW:
        win = f"AttendX — {classroom_id}"
        cv2.namedWindow(win, cv2.WINDOW_NORMAL)
        cv2.resizeWindow(win, 800, 520)

    lecture_id    = None
    present_today = set()

    try:
        while True:
            await reload_faces_if_needed()

            lecture_id = await get_active_lecture(classroom_id)
            if not lecture_id and AUTO_START:
                lecture_id = await start_lecture(classroom_id)
                if lecture_id:
                    present_today.clear()
                    frame_buffer.clear()
                    logger.info("Auto-started lecture #%d in %s", lecture_id, classroom_id)

            ret, frame = cap.read()
            if not ret:
                logger.warning("Camera read failed — retrying ...")
                await asyncio.sleep(1)
                continue

            faces        = []
            face_results = []

            if lecture_id:
                raw_faces = model.get(frame)
                if raw_faces:
                    faces = sorted(
                        raw_faces,
                        key=lambda f: (f.bbox[2]-f.bbox[0]) * (f.bbox[3]-f.bbox[1]),
                        reverse=True
                    )[:cfg.max_faces_per_frame]

                    for face in faces:
                        idx, score = cosine_match(face.embedding, known_matrix)
                        was_marked = False
                        if idx is not None and score >= cfg.similarity_threshold:
                            sid  = known_ids[idx]
                            name = known_names[idx]
                            frame_buffer[sid] += 1
                            if frame_buffer[sid] >= RECOGNITION_BUFFER and not on_cooldown(sid):
                                marked = await mark_attendance(sid, lecture_id)
                                if marked:
                                    last_seen[sid]  = time.time()
                                    present_today.add(sid)
                                    was_marked   = True
                                    _flash_name  = name
                                    _flash_until = time.time() + 2.5
                                    sys.stdout.write("\n")
                                    logger.info("MARKED  %-20s  %-12s  score=%.3f", name, sid, score)
                                frame_buffer[sid] = 0
                            face_results.append((sid, name, score, was_marked))
                        else:
                            face_results.append(None)

            if SHOW_WINDOW:
                display = _draw_frame(frame, faces, face_results,
                                      classroom_id, lecture_id,
                                      len(present_today), len(known_ids))
                cv2.imshow(win, display)
                key = cv2.waitKey(1) & 0xFF
                if key in (ord('q'), 27):
                    logger.info("User quit — stopping.")
                    break

            _print_status(classroom_id, lecture_id, len(present_today), len(known_ids))
            await asyncio.sleep(0.04)

    except (asyncio.CancelledError, KeyboardInterrupt):
        pass
    finally:
        cap.release()
        if SHOW_WINDOW:
            cv2.destroyAllWindows()
        sys.stdout.write("\n")
        logger.info("Recognition engine stopped.")


async def main(classroom_id: str) -> None:
    await init_pool()
    try:
        await run_recognition(classroom_id)
    finally:
        await close_pool()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--classroom",
        default=os.getenv("CLASSROOM_ID", "CR-2113"),
    )
    args = parser.parse_args()
    asyncio.run(main(args.classroom))
