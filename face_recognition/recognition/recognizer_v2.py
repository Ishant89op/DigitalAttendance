import cv2
import numpy as np
import time

from insightface.app import FaceAnalysis

from utils.face_loader import load_known_faces
from attendance.attendance_manager import mark_attendance
from services.lecture_service import get_active_lecture


# ==============================
# CONFIG
# ==============================
CLASSROOM_ID = "CR101"
DEVICE_ID = "CR101_CAM1"

SIMILARITY_THRESHOLD = 0.5
COOLDOWN_SECONDS = 10
MAX_FACES = 4


# ==============================
# LOAD MODEL
# ==============================
print("Loading InsightFace model...")
app = FaceAnalysis()
app.prepare(ctx_id=-1, det_size=(640, 640))  # CPU mode


# ==============================
# LOAD KNOWN FACES
# ==============================
print("Loading known student faces...")
known_encodings, known_names, known_ids = load_known_faces()

if len(known_encodings) > 0:
    known_encodings = np.array(known_encodings)
else:
    known_encodings = np.array([])


# ==============================
# FACE MATCH FUNCTION
# ==============================
def recognize_face(face_embedding):
    if len(known_encodings) == 0:
        return None, None

    similarities = np.dot(known_encodings, face_embedding)

    best_index = np.argmax(similarities)
    best_score = similarities[best_index]

    if best_score > SIMILARITY_THRESHOLD:
        return known_ids[best_index], known_names[best_index]

    return None, None


# ==============================
# MAIN FUNCTION
# ==============================
def start_recognition():

    cap = cv2.VideoCapture(0)

    last_seen = {}

    print("Recognition system started...")

    while True:

        ret, frame = cap.read()
        if not ret:
            break

        lecture_id = get_active_lecture(CLASSROOM_ID)

        # ==============================
        # WAIT MODE (NO ACTIVE LECTURE)
        # ==============================
        if not lecture_id:

            cv2.putText(frame, "Waiting for attendance...",
                        (50, 50),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        1,
                        (0, 0, 255),
                        2)

            cv2.imshow("Attendance System", frame)

            if cv2.waitKey(1) & 0xFF == ord('q'):
                break

            continue

        # ==============================
        # DETECT FACES
        # ==============================
        faces = app.get(frame)

        # Limit number of faces
        faces = sorted(faces, key=lambda x: (x.bbox[2] - x.bbox[0]), reverse=True)
        faces = faces[:MAX_FACES]

        for face in faces:

            bbox = face.bbox.astype(int)
            embedding = face.embedding

            student_id, name = recognize_face(embedding)

            if student_id:

                # cooldown check
                if student_id not in last_seen or \
                   time.time() - last_seen[student_id] > COOLDOWN_SECONDS:

                    mark_attendance(student_id, lecture_id)
                    last_seen[student_id] = time.time()

                label = f"{name}"
                color = (0, 255, 0)

            else:
                label = "Unknown"
                color = (0, 0, 255)

            # Draw bounding box
            x1, y1, x2, y2 = bbox
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)

            cv2.putText(frame,
                        label,
                        (x1, y1 - 10),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.7,
                        color,
                        2)

        # ==============================
        # DISPLAY
        # ==============================
        cv2.imshow("Face Attendance System", frame)

        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()