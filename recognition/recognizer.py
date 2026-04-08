"""
Face Recognition Engine — threaded architecture for smooth, lag-free video.

Architecture (3 independent threads):
  ┌─────────────────┐    latest frame    ┌─────────────────┐
  │  FrameGrabber   │ ─────────────────► │  Detector       │
  │  Thread         │    (atomically     │  Thread         │
  │  cap.read() at  │     overwritten)   │  model.get()    │
  │  full camera FPS│                    │  cosine match   │
  └─────────────────┘                    └────────┬────────┘
          │                                       │ cached results
          │ latest frame                          ▼
          └──────────────────────────►  Main thread (Display)
                                        _draw_frame()
                                        preview.show()
                                        30 fps, never waits

  AsyncWorker thread owns its own asyncio event loop.
  DB calls (mark_attendance, get_active_lecture) are submitted
  via run_coroutine_threadsafe() — they never block any other thread.

Result: display always runs at camera FPS regardless of model speed.
"""

import argparse
import asyncio
import logging
import os
import sys
import threading
import time
from collections import Counter
from concurrent.futures import Future

import cv2
import numpy as np

from core.database import init_pool, close_pool
from utils.face_utils import get_model, load_known_faces, cosine_match
from utils.preview import create_preview_window, detect_preview_backend
from attendance.attendance_manager import mark_attendance
from services.lecture_service import get_active_lecture, start_lecture
from config.settings import recog as cfg

logger = logging.getLogger(__name__)

# ── Tuning constants ──────────────────────────────────────────────────────────
RECOGNITION_BUFFER   = 3      # consecutive matched frames before marking
RELOAD_INTERVAL_SECS = 60     # how often face DB is refreshed from storage
LECTURE_POLL_SECS    = 5      # how often to query DB for active lecture
AUTO_START           = True   # auto-start lecture from schedule if none active
DISPLAY_WIDTH        = 800    # preview window width
DISPLAY_HEIGHT       = 520    # preview window height
# ─────────────────────────────────────────────────────────────────────────────

PREVIEW_BACKEND = detect_preview_backend()
SHOW_WINDOW = PREVIEW_BACKEND != "none"
if PREVIEW_BACKEND == "tk":
    print("  [Note] OpenCV GUI is unavailable. Using Tk preview window instead.\n")
elif PREVIEW_BACKEND == "none":
    print("  [Note] No GUI preview backend is available — running headless.")
    print("  To restore a native preview window, run:")
    print("    pip uninstall opencv-python-headless -y")
    print("    pip install --force-reinstall opencv-python\n")


# ══════════════════════════════════════════════════════════════════════════════
# ASYNC WORKER — owns its own event loop on a daemon thread
# All DB coroutines are submitted via submit() and run here.
# ══════════════════════════════════════════════════════════════════════════════
class AsyncWorker(threading.Thread):
    """Dedicated thread that runs an asyncio event loop for all DB operations."""

    def __init__(self):
        super().__init__(daemon=True, name="AsyncWorker")
        self.loop = asyncio.new_event_loop()

    def run(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def submit(self, coro) -> Future:
        """Schedule a coroutine and return a concurrent.futures.Future."""
        return asyncio.run_coroutine_threadsafe(coro, self.loop)

    def stop(self):
        self.loop.call_soon_threadsafe(self.loop.stop)


# ══════════════════════════════════════════════════════════════════════════════
# FRAME GRABBER — runs cap.read() continuously in its own thread
# Overwrites a single slot with the newest frame; never queues old frames.
# ══════════════════════════════════════════════════════════════════════════════
class FrameGrabber(threading.Thread):
    """Continuously reads frames from the camera and exposes the latest one."""

    def __init__(self, cap: cv2.VideoCapture):
        super().__init__(daemon=True, name="FrameGrabber")
        self._cap = cap
        self._frame: np.ndarray | None = None
        self._lock = threading.Lock()
        self._stop_event = threading.Event()

    def run(self):
        while not self._stop_event.is_set():
            ret, frame = self._cap.read()
            if ret:
                with self._lock:
                    self._frame = frame

    def get_latest(self) -> np.ndarray | None:
        with self._lock:
            return None if self._frame is None else self._frame.copy()

    def stop(self):
        self._stop_event.set()


# ══════════════════════════════════════════════════════════════════════════════
# DETECTOR — runs InsightFace in its own thread
# Picks up the latest frame, processes it, writes results to shared state.
# Never blocks the display thread.
# ══════════════════════════════════════════════════════════════════════════════
class Detector(threading.Thread):
    """Runs face detection + matching in a background thread."""

    def __init__(self, grabber: FrameGrabber, async_worker: AsyncWorker, classroom_id: str):
        super().__init__(daemon=True, name="Detector")
        self._grabber = grabber
        self._worker  = async_worker
        self._classroom_id = classroom_id

        # Shared state — written by detector, read by display thread
        self._results_lock = threading.Lock()
        self._cached_faces: list       = []
        self._cached_results: list     = []
        self._present_today: set       = set()
        self._lecture_id: int | None   = None
        self._enrolled: int            = 0

        # Internal detection state
        self._frame_buffer: Counter    = Counter()
        self._last_seen: dict          = {}
        self._known_matrix: np.ndarray = np.empty((0, cfg.embedding_dim), dtype=np.float32)
        self._known_names: list[str]   = []
        self._known_ids: list[str]     = []
        self._last_reload: float       = 0.0
        self._last_lecture_poll: float = 0.0

        self._stop_event = threading.Event()
        self._model = None

    # ── Public read-only accessors (called from display thread) ───────────────
    def get_display_state(self):
        """Return snapshot of current detection results for drawing."""
        with self._results_lock:
            return (
                list(self._cached_faces),
                list(self._cached_results),
                len(self._present_today),
                self._enrolled,
                self._lecture_id,
            )

    # ── Internal helpers ──────────────────────────────────────────────────────
    def _on_cooldown(self, sid: str) -> bool:
        return (time.time() - self._last_seen.get(sid, 0)) < cfg.cooldown_seconds

    def _reload_faces(self):
        if time.time() - self._last_reload < RELOAD_INTERVAL_SECS:
            return
        fut = self._worker.submit(load_known_faces())
        try:
            mat, names, ids = fut.result(timeout=10)
            self._known_matrix = mat
            self._known_names  = names
            self._known_ids    = ids
            self._enrolled     = len(ids)
            self._last_reload  = time.time()
            logger.info("Face DB reloaded — %d registered students", len(ids))
        except Exception as e:
            logger.warning("Face DB reload failed: %s", e)

    def _poll_lecture(self):
        if time.monotonic() - self._last_lecture_poll < LECTURE_POLL_SECS:
            return
        self._last_lecture_poll = time.monotonic()

        fut = self._worker.submit(get_active_lecture(self._classroom_id))
        try:
            lid = fut.result(timeout=5)
        except Exception:
            return

        if not lid and AUTO_START:
            fut2 = self._worker.submit(start_lecture(self._classroom_id))
            try:
                lid = fut2.result(timeout=5)
                if lid:
                    logger.info("Auto-started lecture #%d in %s", lid, self._classroom_id)
                    with self._results_lock:
                        self._present_today.clear()
                    self._frame_buffer.clear()
                    with self._results_lock:
                        self._cached_faces   = []
                        self._cached_results = []
            except Exception:
                pass

        with self._results_lock:
            self._lecture_id = lid

    # ── Main detection loop ───────────────────────────────────────────────────
    def run(self):
        self._model = get_model()

        # Warm-up pass — ONNX JIT before first real frame
        blank = np.zeros((480, 640, 3), dtype=np.uint8)
        try:
            self._model.get(blank)
        except Exception:
            pass

        self._reload_faces()

        while not self._stop_event.is_set():
            self._reload_faces()
            self._poll_lecture()

            with self._results_lock:
                current_lecture = self._lecture_id

            if not current_lecture:
                time.sleep(0.05)
                continue

            frame = self._grabber.get_latest()
            if frame is None:
                time.sleep(0.01)
                continue

            # ── Run InsightFace (blocking — but in its own thread, so display is fine)
            try:
                raw_faces = self._model.get(frame)
            except Exception as e:
                logger.warning("Detection error: %s", e)
                continue

            if raw_faces:
                faces = sorted(
                    raw_faces,
                    key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]),
                    reverse=True,
                )[:cfg.max_faces_per_frame]
            else:
                faces = []

            with self._results_lock:
                known_matrix = self._known_matrix
                known_ids    = self._known_ids
                known_names  = self._known_names
                present_snap = set(self._present_today)

            face_results = []
            pending_marks: list[tuple[str, str, float]] = []   # (sid, name, score)

            for face in faces:
                idx, score = cosine_match(face.embedding, known_matrix)
                if idx is not None and score >= cfg.similarity_threshold:
                    sid  = known_ids[idx]
                    name = known_names[idx]
                    self._frame_buffer[sid] += 1
                    if self._frame_buffer[sid] >= RECOGNITION_BUFFER and not self._on_cooldown(sid):
                        pending_marks.append((sid, name, score))
                        self._frame_buffer[sid] = 0
                    face_results.append((sid, name, sid in present_snap))
                else:
                    face_results.append(None)

            # Fire-and-forget DB writes (non-blocking)
            for sid, name, score in pending_marks:
                self._do_mark(sid, name, score, current_lecture)

            with self._results_lock:
                self._cached_faces   = faces
                self._cached_results = face_results

    def _do_mark(self, sid: str, name: str, score: float, lecture_id: int):
        """Submit attendance mark to async worker; update local state on success."""
        def _callback(fut: Future):
            try:
                marked = fut.result()
                if marked:
                    self._last_seen[sid] = time.time()
                    with self._results_lock:
                        self._present_today.add(sid)
                    sys.stdout.write("\n")
                    logger.info("MARKED  %-20s  %-12s  score=%.3f", name, sid, score)
            except Exception as e:
                logger.error("Attendance mark failed for %s: %s", sid, e)

        fut = self._worker.submit(mark_attendance(sid, lecture_id))
        fut.add_done_callback(_callback)

    def stop(self):
        self._stop_event.set()


# ══════════════════════════════════════════════════════════════════════════════
# OVERLAY DRAW HELPER
# ══════════════════════════════════════════════════════════════════════════════
def _draw_frame(frame, faces, face_results, classroom_id, lecture_id, present_count, enrolled):
    display = frame.copy()
    h, w = display.shape[:2]

    for i, face in enumerate(faces):
        x1, y1, x2, y2 = [int(v) for v in face.bbox]
        if i < len(face_results) and face_results[i] is not None:
            sid, name, is_marked = face_results[i]
            color = (0, 255, 80) if is_marked else (0, 200, 0)
            label = f"{name} (Marked)" if is_marked else name
        else:
            color = (0, 60, 220)
            label = "Unknown"
        cv2.rectangle(display, (x1, y1), (x2, y2), color, 2)
        (lw, lh), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 1)
        cv2.rectangle(display, (x1, y1 - lh - 10), (x1 + lw + 6, y1), color, -1)
        cv2.putText(display, label, (x1 + 3, y1 - 5),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 1, cv2.LINE_AA)

    # HUD bar
    bar_overlay = display.copy()
    cv2.rectangle(bar_overlay, (0, 0), (w, 38), (15, 15, 30), -1)
    cv2.addWeighted(bar_overlay, 0.75, display, 0.25, 0, display)
    cv2.putText(display, f"Room: {classroom_id}", (10, 26),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (180, 180, 180), 1, cv2.LINE_AA)
    lect_txt = f"Lecture #{lecture_id}" if lecture_id else "No active lecture"
    cv2.putText(display, lect_txt, (w // 2 - 65, 26),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (100, 220, 255), 1, cv2.LINE_AA)
    cv2.putText(display, f"Present: {present_count}/{enrolled}", (w - 180, 26),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (80, 255, 120), 1, cv2.LINE_AA)

    if not lecture_id:
        cv2.putText(display, "Waiting for lecture to start ...", (w // 2 - 190, h // 2),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.9, (80, 180, 255), 2, cv2.LINE_AA)
    return display


# ══════════════════════════════════════════════════════════════════════════════
# CAMERA OPEN HELPER
# ══════════════════════════════════════════════════════════════════════════════
def _open_camera() -> cv2.VideoCapture | None:
    for idx in (0, 1):
        cap = cv2.VideoCapture(idx, cv2.CAP_DSHOW)
        if cap.isOpened():
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter.fourcc(*"MJPG"))
            cap.set(cv2.CAP_PROP_FRAME_WIDTH,  640)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            cap.set(cv2.CAP_PROP_FPS, 30)
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            logger.info("Camera %d opened (MJPG, 640×480, FPS=30, buffer=1)", idx)
            return cap
    return None


# ══════════════════════════════════════════════════════════════════════════════
# MAIN ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════
def run_recognition(classroom_id: str) -> None:
    """
    Main camera + display loop.  Runs on the calling thread (process main thread).
    All heavy work is off-loaded to background threads.
    """
    # ── Start async worker (DB operations) ────────────────────────────────────
    async_worker = AsyncWorker()
    async_worker.start()

    # ── Init DB pool on the async worker's loop ────────────────────────────────
    init_fut = async_worker.submit(init_pool())
    try:
        init_fut.result(timeout=15)
    except Exception as e:
        logger.error("DB pool init failed: %s", e)
        async_worker.stop()
        return

    # ── Open camera ───────────────────────────────────────────────────────────
    cap = _open_camera()
    if cap is None:
        logger.error("Cannot open camera. Check it is connected and not used by another app.")
        async_worker.stop()
        return

    # ── Start frame grabber thread ─────────────────────────────────────────────
    grabber = FrameGrabber(cap)
    grabber.start()

    # ── Start detector thread ──────────────────────────────────────────────────
    detector = Detector(grabber, async_worker, classroom_id)
    detector.start()

    logger.info("=" * 55)
    logger.info("  AttendX Recognition Engine")
    logger.info("  Classroom : %s", classroom_id)
    if SHOW_WINDOW:
        logger.info("  Camera window open — press Q or ESC to quit")
    else:
        logger.info("  Running headless — press Ctrl+C to stop")
    logger.info("=" * 55)

    # ── Create preview window ──────────────────────────────────────────────────
    preview = None
    if SHOW_WINDOW:
        preview = create_preview_window(f"AttendX — {classroom_id}", DISPLAY_WIDTH, DISPLAY_HEIGHT)
        if preview is None:
            logger.warning("Preview window creation failed — running headless.")

    # ── Display loop (main thread — full camera FPS, never stalls) ────────────
    try:
        while True:
            frame = grabber.get_latest()
            if frame is None:
                time.sleep(0.01)
                continue

            faces, face_results, present_count, enrolled, lecture_id = detector.get_display_state()

            if preview is not None:
                display = _draw_frame(frame, faces, face_results,
                                      classroom_id, lecture_id,
                                      present_count, enrolled)
                keep_running = preview.show(display)
                if not keep_running:
                    logger.info("User quit — stopping.")
                    break
            else:
                # Headless: just print status, sleep to avoid busy-loop
                bar = chr(9608) * present_count + chr(9617) * max(0, enrolled - present_count)
                sys.stdout.write(
                    f"\r  [{classroom_id}] Lecture #{lecture_id}  "
                    f"Present: {present_count}/{enrolled}  [{bar}]   "
                )
                sys.stdout.flush()
                time.sleep(0.1)

    except KeyboardInterrupt:
        pass
    finally:
        detector.stop()
        grabber.stop()
        grabber.join(timeout=2)
        detector.join(timeout=5)
        cap.release()
        if preview is not None:
            preview.close()
        sys.stdout.write("\n")
        logger.info("Recognition engine stopped.")

        close_fut = async_worker.submit(close_pool())
        try:
            close_fut.result(timeout=5)
        except Exception:
            pass
        async_worker.stop()
        async_worker.join(timeout=3)


# ══════════════════════════════════════════════════════════════════════════════
# CLI entry (called from main.py)
# ══════════════════════════════════════════════════════════════════════════════
def main(classroom_id: str) -> None:
    """Synchronous entry point — called by main.py cmd_recognize()."""
    run_recognition(classroom_id)


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
    run_recognition(args.classroom)
