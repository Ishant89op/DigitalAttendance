"""
Student registration — face capture with live camera preview (if available).

Falls back to headless mode automatically if OpenCV has no GUI support.

Run:
    python main.py register
"""

import asyncio
import logging
import sys
import time

import cv2
import numpy as np

from core.database import init_pool, close_pool, get_conn, transaction
from utils.face_utils import get_model, normalize
from config.settings import recog as cfg

logger = logging.getLogger(__name__)

# Detect if OpenCV GUI is available
def _has_gui():
    try:
        cv2.namedWindow("_test", cv2.WINDOW_NORMAL)
        cv2.destroyWindow("_test")
        return True
    except Exception:
        return False

GUI_AVAILABLE = _has_gui()
if not GUI_AVAILABLE:
    print("  [Note] OpenCV GUI not available — running in terminal-only mode.")
    print("  To enable camera preview, run:  pip uninstall opencv-python-headless -y")
    print("                                  pip install opencv-python\n")


async def student_exists(student_id: str) -> dict | None:
    async with get_conn() as conn:
        row = await conn.fetchrow(
            "SELECT student_id, name, department, semester, face_encoding "
            "FROM students WHERE student_id = $1",
            student_id,
        )
    return dict(row) if row else None


async def save_face_encoding(student_id: str, embedding: np.ndarray) -> None:
    embedding_bytes = embedding.astype(np.float32).tobytes()
    async with transaction() as conn:
        await conn.execute(
            """
            UPDATE students
            SET    face_encoding = $1,
                   registered_at = NOW()
            WHERE  student_id = $2
            """,
            embedding_bytes,
            student_id,
        )
        await conn.execute(
            """
            INSERT INTO audit_log (event_type, actor_id, target_id, detail)
            VALUES ('face_registered', 'system', $1,
                    jsonb_build_object('method', 'insightface'))
            """,
            student_id,
        )
    logger.info("Face encoding saved for student %s", student_id)


def _progress(current: int, total: int) -> None:
    filled = int(30 * current / total)
    bar    = chr(9608) * filled + chr(9617) * (30 - filled)
    sys.stdout.write(f"\r  [{bar}] {current}/{total} samples captured")
    sys.stdout.flush()
    if current == total:
        sys.stdout.write("\n")
        sys.stdout.flush()


def _draw_registration_frame(frame, faces, samples_done, total, student_name):
    display = frame.copy()
    h, w = display.shape[:2]

    for face in faces:
        x1, y1, x2, y2 = [int(v) for v in face.bbox]
        cv2.rectangle(display, (x1, y1), (x2, y2), (0, 220, 80), 2)

    overlay = display.copy()
    cv2.rectangle(overlay, (0, 0), (w, 42), (15, 15, 30), -1)
    cv2.addWeighted(overlay, 0.75, display, 0.25, 0, display)
    cv2.putText(display, f"Registering: {student_name}", (10, 28),
                cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 220, 80), 1, cv2.LINE_AA)

    pct   = samples_done / total
    bar_y = h - 40
    cv2.rectangle(display, (10, bar_y), (w - 10, bar_y + 20), (40, 40, 40), -1)
    cv2.rectangle(display, (10, bar_y), (10 + int((w - 20) * pct), bar_y + 20), (0, 200, 80), -1)
    cv2.putText(display, f"{samples_done}/{total} samples", (w // 2 - 55, bar_y + 15),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)

    if samples_done == 0 and not faces:
        cv2.putText(display, "Look directly at the camera", (w // 2 - 150, h // 2),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.85, (80, 180, 255), 2, cv2.LINE_AA)

    if samples_done == total:
        cv2.putText(display, "Done! Processing ...", (w // 2 - 130, h // 2),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 100), 2, cv2.LINE_AA)

    return display


async def register_student() -> None:
    student_id = input("Enter Student ID: ").strip()

    student = await student_exists(student_id)
    if not student:
        print(f"\n  Student ID '{student_id}' not found in database.")
        print("  Ask your admin to add the student record first.")
        return

    if student["face_encoding"] is not None:
        overwrite = input(
            f"\n  {student['name']} already has a face registered. "
            "Overwrite? [y/N]: "
        ).strip().lower()
        if overwrite != "y":
            print("Registration cancelled.")
            return

    print(f"\n  Found: {student['name']}  |  {student['department']}  "
          f"|  Semester {student['semester']}")
    print(f"\n  Look directly at the camera.")
    print(f"  Capturing {cfg.samples_required} samples ...\n")

    model = get_model()

    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        logger.warning("Camera 0 failed — trying index 1 ...")
        cap = cv2.VideoCapture(1)
    if not cap.isOpened():
        print("  Could not open camera. Check it is connected and not in use.")
        return

    cap.set(cv2.CAP_PROP_FRAME_WIDTH,  640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

    if GUI_AVAILABLE:
        win_name = "AttendX — Face Registration"
        cv2.namedWindow(win_name, cv2.WINDOW_NORMAL)
        cv2.resizeWindow(win_name, 800, 520)

    samples      = []
    empty_frames = 0
    MAX_EMPTY    = 300

    while len(samples) < cfg.samples_required:
        ret, frame = cap.read()
        if not ret:
            print("\n  Camera read failed.")
            break

        faces = model.get(frame)

        if faces:
            face = max(faces, key=lambda f: (f.bbox[2]-f.bbox[0]) * (f.bbox[3]-f.bbox[1]))
            samples.append(face.embedding)
            empty_frames = 0
            _progress(len(samples), cfg.samples_required)
            if GUI_AVAILABLE:
                display = _draw_registration_frame(frame, [face], len(samples), cfg.samples_required, student['name'])
        else:
            empty_frames += 1
            if empty_frames == 1:
                sys.stdout.write("  Waiting for face ...")
                sys.stdout.flush()
            if empty_frames > MAX_EMPTY:
                print("\n  No face detected for too long. Aborting.")
                break
            if GUI_AVAILABLE:
                display = _draw_registration_frame(frame, [], len(samples), cfg.samples_required, student['name'])

        if GUI_AVAILABLE:
            cv2.imshow(win_name, display)
            key = cv2.waitKey(1) & 0xFF
            if key in (ord('q'), 27):
                print("\n  Registration cancelled.")
                cap.release()
                cv2.destroyAllWindows()
                return

        time.sleep(0.03)

    if GUI_AVAILABLE and len(samples) >= cfg.samples_required:
        ret, frame = cap.read()
        if ret:
            cv2.imshow(win_name, _draw_registration_frame(
                frame, [], cfg.samples_required, cfg.samples_required, student['name']))
            cv2.waitKey(1200)

    cap.release()
    if GUI_AVAILABLE:
        cv2.destroyAllWindows()

    if len(samples) < cfg.samples_required:
        print(f"\n  Only {len(samples)} samples captured. Registration aborted.")
        return

    print("\n   Processing embeddings ...")
    avg = normalize(np.mean(samples, axis=0))
    await save_face_encoding(student_id, avg)
    print(f"\n  Registration complete for {student['name']}\n")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    async def main():
        await init_pool()
        await register_student()
        await close_pool()

    asyncio.run(main())
