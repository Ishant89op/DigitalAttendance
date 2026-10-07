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
import traceback
from collections import Counter
from pathlib import Path

import cv2
import numpy as np

from core.database import init_pool, close_pool
from utils.face_utils import get_model, load_known_faces, cosine_match
from attendance.attendance_manager import mark_attendance
from services.lecture_service import get_active_lecture, get_lecture_detail, start_lecture
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
    except Exception:
        return False

SHOW_WINDOW = _has_gui()
WINDOW_NAME = ""
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

ERROR_LOG_PATH = Path(__file__).resolve().parent.parent / "instance" / "recognition_last_error.log"


loaded_course: str | None = None


async def reload_faces_if_needed(course_id: str | None = None, force: bool = False) -> None:
    """
    Keep the in-memory gallery to students enrolled in the running course, so
    a registered student from another class can never be marked here.
    """
    global known_matrix, known_names, known_ids, last_reload, loaded_course
    if not force and course_id == loaded_course and time.time() - last_reload < RELOAD_INTERVAL_SECS:
        return
    known_matrix, known_names, known_ids = await load_known_faces(course_id)
    last_reload = time.time()
    loaded_course = course_id
    logger.info("Face gallery loaded — %d enrolled students%s",
                len(known_ids), f" for {course_id}" if course_id else "")


async def _lecture_course(lecture_id: int | None) -> str | None:
    if not lecture_id:
        return None
    detail = await get_lecture_detail(lecture_id)
    return detail["course_id"] if detail else None


def on_cooldown(student_id: str) -> bool:
    return (time.time() - last_seen.get(student_id, 0)) < cfg.cooldown_seconds


def _disable_gui(reason: str) -> None:
    global SHOW_WINDOW, WINDOW_NAME
    if not SHOW_WINDOW:
        return
    SHOW_WINDOW = False
    try:
        cv2.destroyAllWindows()
    except Exception:
        pass
    WINDOW_NAME = ""
    logger.warning("Disabling camera preview and continuing headless: %s", reason)


def _persist_exception(exc: Exception) -> None:
    try:
        ERROR_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        ERROR_LOG_PATH.write_text(
            f"{time.strftime('%Y-%m-%d %H:%M:%S')}\n{traceback.format_exc()}",
            encoding="utf-8",
        )
    except Exception:
        pass
    logger.exception("Recognition engine error: %s", exc)


def _print_status(classroom_id, lecture_id, present_count, enrolled):
    bar = chr(9608) * present_count + chr(9617) * max(0, enrolled - present_count)
    sys.stdout.write(
        f"\r  [{classroom_id}] Lecture #{lecture_id}  "
        f"Present: {present_count}/{enrolled}  [{bar}]   "
    )
    sys.stdout.flush()


def _bbox_center(face) -> tuple[float, float]:
    x1, y1, x2, y2 = [float(v) for v in face.bbox]
    return (x1 + x2) / 2.0, (y1 + y2) / 2.0


def _bbox_area(face) -> float:
    x1, y1, x2, y2 = [float(v) for v in face.bbox]
    return max((x2 - x1) * (y2 - y1), 1.0)


def _landmark_signature(face) -> np.ndarray | None:
    """
    Return a scale-normalized facial shape signature from 5-point landmarks.
    If landmarks are unavailable, returns None.
    """
    kps = getattr(face, "kps", None)
    if kps is None:
        return None

    points = np.asarray(kps, dtype=np.float32)
    if points.shape[0] < 5:
        return None

    left_eye = points[0]
    right_eye = points[1]
    nose = points[2]
    left_mouth = points[3]
    right_mouth = points[4]

    eye_dist = float(np.linalg.norm(left_eye - right_eye))
    if eye_dist < 1e-6:
        return None

    eye_mid = (left_eye + right_eye) / 2.0
    mouth_mid = (left_mouth + right_mouth) / 2.0

    return np.array(
        [
            float(np.linalg.norm(nose - eye_mid) / eye_dist),
            float(np.linalg.norm(mouth_mid - nose) / eye_dist),
            float(np.linalg.norm(left_mouth - right_mouth) / eye_dist),
            float(np.linalg.norm(left_eye - nose) / eye_dist),
            float(np.linalg.norm(right_eye - nose) / eye_dist),
        ],
        dtype=np.float32,
    )


def _face_attr(face, key: str):
    value = getattr(face, key, None)
    if value is not None:
        return value
    if hasattr(face, "get"):
        try:
            return face.get(key)
        except Exception:
            return None
    return None


def _ear_from_eye(eye_pts: np.ndarray) -> float:
    """Compute Eye Aspect Ratio from 6 eye landmarks."""
    if eye_pts.shape[0] != 6:
        return 0.0
    a = float(np.linalg.norm(eye_pts[1] - eye_pts[5]))
    b = float(np.linalg.norm(eye_pts[2] - eye_pts[4]))
    c = float(np.linalg.norm(eye_pts[0] - eye_pts[3]))
    if c < 1e-6:
        return 0.0
    return (a + b) / (2.0 * c)


def _current_ear(face) -> float | None:
    """
    Return average EAR from 68 landmarks.
    Uses standard dlib-compatible eye indices:
      left eye: 36..41, right eye: 42..47.
    """
    lm = _face_attr(face, "landmark_3d_68")
    if lm is None:
        return None

    pts = np.asarray(lm, dtype=np.float32)
    if pts.ndim != 2 or pts.shape[0] < 68:
        return None
    pts2 = pts[:, :2]

    left_eye = pts2[36:42]
    right_eye = pts2[42:48]
    left_ear = _ear_from_eye(left_eye)
    right_ear = _ear_from_eye(right_eye)
    if left_ear <= 0.0 or right_ear <= 0.0:
        return None
    return (left_ear + right_ear) / 2.0


def _update_blink_state(face, state: dict) -> bool:
    """
    Update blink FSM for one frame.
    Returns True if blink features are available for this face/frame.
    """
    ear = _current_ear(face)
    if ear is None:
        return False

    open_ref = state.get("ear_open_ref")
    if open_ref is None:
        open_ref = ear
    else:
        # Slowly adapt open-eye reference while keeping it resistant to sudden drops.
        open_ref = max(open_ref * 0.995, ear)
    state["ear_open_ref"] = open_ref

    closed_thr = max(cfg.blink_closed_min_ear, open_ref * cfg.blink_closed_ratio)
    open_thr = max(cfg.blink_open_min_ear, open_ref * cfg.blink_open_ratio)
    if open_thr <= closed_thr:
        open_thr = closed_thr + 0.02

    if state["blink_is_closed"]:
        if ear >= open_thr:
            state["blink_count"] += 1
            state["blink_is_closed"] = False
            state["blink_closed_frames"] = 0
    else:
        if ear <= closed_thr:
            state["blink_closed_frames"] += 1
            if state["blink_closed_frames"] >= cfg.blink_min_closed_frames:
                state["blink_is_closed"] = True
        else:
            state["blink_closed_frames"] = 0

    state["last_ear"] = ear
    return True


def _liveness_passed(sid: str, face, state_map: dict[str, dict]) -> tuple[bool, str]:
    """
    Multi-signal liveness:
    - short temporal observation window
    - accumulated center motion
    - plus either face scale change or landmark shape variation
    """
    center = _bbox_center(face)
    area = _bbox_area(face)
    signature = _landmark_signature(face)

    prev = state_map.get(sid)
    if prev is None:
        state_map[sid] = {
            "center": center,
            "area": area,
            "signature": signature,
            "frames": 1,
            "motion_sum": 0.0,
            "scale_sum": 0.0,
            "signature_sum": 0.0,
            "blink_count": 0,
            "blink_is_closed": False,
            "blink_closed_frames": 0,
            "ear_open_ref": None,
            "last_ear": None,
        }
        return False, "Liveness..."

    motion = (
        (center[0] - prev["center"][0]) ** 2
        + (center[1] - prev["center"][1]) ** 2
    ) ** 0.5
    scale_delta = abs(area - prev["area"]) / max(prev["area"], 1.0)
    signature_delta = 0.0
    if signature is not None and prev["signature"] is not None:
        signature_delta = float(np.linalg.norm(signature - prev["signature"]))

    prev["frames"] += 1
    prev["motion_sum"] += motion
    prev["scale_sum"] += scale_delta
    prev["signature_sum"] += signature_delta
    prev["center"] = center
    prev["area"] = area
    prev["signature"] = signature

    blink_supported = _update_blink_state(face, prev)

    if prev["frames"] < cfg.liveness_required_frames:
        return False, "Liveness..."

    if prev["motion_sum"] < cfg.liveness_motion_accum_px:
        return False, "Liveness"

    has_depth_or_shape_change = (
        prev["scale_sum"] >= cfg.liveness_scale_delta
        or prev["signature_sum"] >= cfg.liveness_signature_delta
    )
    if not has_depth_or_shape_change:
        return False, "Liveness"

    if cfg.require_blink_liveness:
        if not blink_supported:
            return False, "Blink..."
        if prev["blink_count"] < cfg.min_blink_count:
            return False, f"Blink {prev['blink_count']}/{cfg.min_blink_count}"

    return True, "Live"


def _draw_frame(frame, faces, face_results, classroom_id, lecture_id, present_count, enrolled):
    display = frame.copy()
    _, w = display.shape[:2]

    for i, face in enumerate(faces):
        x1, y1, x2, y2 = [int(v) for v in face.bbox]
        if i < len(face_results) and face_results[i] is not None:
            name, status, color = face_results[i]
            label = f"{name}({status})"
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
    cv2.putText(display, f"Room: {classroom_id}", (10, 26),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (180, 180, 180), 1, cv2.LINE_AA)
    lect_txt = f"Lecture #{lecture_id}" if lecture_id else "No active lecture"
    cv2.putText(display, lect_txt, (w // 2 - 65, 26),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (100, 220, 255), 1, cv2.LINE_AA)
    cv2.putText(display, f"Present: {present_count}/{enrolled}", (w - 190, 26),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (80, 255, 120), 1, cv2.LINE_AA)

    if not lecture_id:
        cv2.putText(display, "Waiting for lecture to start ...", (w // 2 - 190, 240),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.9, (80, 180, 255), 2, cv2.LINE_AA)
    return display


async def run_recognition(classroom_id: str) -> None:
    global last_reload, WINDOW_NAME

    last_reload = 0.0
    await reload_faces_if_needed(None, force=True)

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
        try:
            WINDOW_NAME = f"AttendX — {classroom_id}"
            cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL)
            cv2.resizeWindow(WINDOW_NAME, 800, 520)
        except Exception as exc:
            _disable_gui(f"failed to open preview window: {exc}")

    lecture_id    = None
    last_lecture_id = None
    current_course: str | None = None
    present_today = set()
    liveness_passed = set()
    liveness_state = {}

    try:
        while True:
            try:
                lecture_id = await get_active_lecture(classroom_id)
                if not lecture_id and AUTO_START:
                    session = await start_lecture(classroom_id)
                    if session:
                        lecture_id = session["lecture_id"]
                        present_today.clear()
                        frame_buffer.clear()
                        liveness_passed.clear()
                        liveness_state.clear()
                        if session["status"] == "resumed_today":
                            logger.info("Auto-resumed lecture #%d in %s", lecture_id, classroom_id)
                        else:
                            logger.info("Auto-started lecture #%d in %s", lecture_id, classroom_id)

                if lecture_id != last_lecture_id:
                    frame_buffer.clear()
                    liveness_passed.clear()
                    liveness_state.clear()
                    if lecture_id is not None:
                        present_today.clear()
                    last_lecture_id = lecture_id
                    current_course = await _lecture_course(lecture_id)
                    await reload_faces_if_needed(current_course, force=True)
                else:
                    await reload_faces_if_needed(current_course)

                ret, frame = cap.read()
                if not ret:
                    logger.warning("Camera read failed — retrying ...")
                    await asyncio.sleep(1)
                    continue

                faces        = []
                face_results = []

                if lecture_id:
                    matched_this_frame = set()
                    raw_faces = model.get(frame)
                    if raw_faces:
                        faces = sorted(
                            raw_faces,
                            key=lambda f: (f.bbox[2]-f.bbox[0]) * (f.bbox[3]-f.bbox[1]),
                            reverse=True
                        )[:cfg.max_faces_per_frame]

                        for face in faces:
                            if float(getattr(face, "det_score", 0.0)) < cfg.min_detection_score:
                                face_results.append(None)
                                continue

                            match = cosine_match(face.embedding, known_matrix)
                            if match.index is None or not match.accepted:
                                face_results.append(None)
                                continue

                            sid  = known_ids[match.index]
                            name = known_names[match.index]
                            matched_this_frame.add(sid)

                            if cfg.enable_liveness_check and sid not in liveness_passed:
                                live_ok, live_status = _liveness_passed(sid, face, liveness_state)
                                if not live_ok:
                                    frame_buffer[sid] = 0
                                    face_results.append((name, live_status, (255, 170, 0)))
                                    continue

                                liveness_passed.add(sid)

                            if on_cooldown(sid) or sid in present_today:
                                frame_buffer[sid] = 0
                                face_results.append((name, "Present", (0, 190, 0)))
                                continue

                            frame_buffer[sid] += 1
                            if frame_buffer[sid] >= RECOGNITION_BUFFER:
                                marked = await mark_attendance(sid, lecture_id)
                                last_seen[sid] = time.time()
                                present_today.add(sid)
                                frame_buffer[sid] = 0
                                sys.stdout.write("\n")
                                if marked:
                                    logger.info(
                                        "MARKED  %-20s  %-12s  score=%.3f  margin=%.3f",
                                        name,
                                        sid,
                                        match.score,
                                        match.margin,
                                    )
                                    face_results.append((name, "Marked", (0, 255, 80)))
                                else:
                                    logger.info(
                                        "ALREADY PRESENT  %-20s  %-12s  score=%.3f  margin=%.3f",
                                        name,
                                        sid,
                                        match.score,
                                        match.margin,
                                    )
                                    face_results.append((name, "Present", (0, 190, 0)))
                            else:
                                face_results.append((name, "Verifying", (0, 210, 255)))

                    for sid in list(frame_buffer.keys()):
                        if sid not in matched_this_frame:
                            del frame_buffer[sid]
                            liveness_state.pop(sid, None)

                if SHOW_WINDOW:
                    try:
                        display = _draw_frame(frame, faces, face_results,
                                              classroom_id, lecture_id,
                                              len(present_today), len(known_ids))
                        cv2.imshow(WINDOW_NAME, display)
                        key = cv2.waitKey(1) & 0xFF
                        if key in (ord('q'), 27):
                            logger.info("User quit — stopping.")
                            break
                    except Exception as exc:
                        _disable_gui(str(exc))

                _print_status(classroom_id, lecture_id, len(present_today), len(known_ids))
                await asyncio.sleep(0.04)
            except Exception as exc:
                _persist_exception(exc)
                await asyncio.sleep(1)

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
    try:
        asyncio.run(main(args.classroom))
    except Exception as exc:
        _persist_exception(exc)
        raise
