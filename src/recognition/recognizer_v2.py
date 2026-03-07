import cv2
import face_recognition
import numpy as np
import time

from utils.face_loader import load_known_faces
from attendance.attendance_manager import mark_attendance


COURSE_ID = "CS101"


def start_recognition():

    print("Loading known faces...")

    known_encodings, known_names, known_ids = load_known_faces()

    if len(known_encodings) == 0:
        print("No registered students found")
        return

    cap = cv2.VideoCapture(0)

    last_seen = {}
    recognition_buffer = {}

    while True:

        ret, frame = cap.read()
        if not ret:
            break

        # Resize for faster processing
        small_frame = cv2.resize(frame, (0,0), fx=0.25, fy=0.25)

        rgb_small = cv2.cvtColor(small_frame, cv2.COLOR_BGR2RGB)

        face_locations = face_recognition.face_locations(rgb_small)

        face_encodings = face_recognition.face_encodings(rgb_small, face_locations)

        face_names = []
        face_ids = []
        confidences = []

        for face_encoding in face_encodings:

            distances = face_recognition.face_distance(
                known_encodings,
                face_encoding
            )

            best_match = np.argmin(distances)

            distance = distances[best_match]

            confidence = round((1 - distance) * 100, 2)

            if distance < 0.45:

                name = known_names[best_match]
                student_id = known_ids[best_match]

                recognition_buffer[name] = recognition_buffer.get(name,0) + 1

                if recognition_buffer[name] >= 3:

                    face_names.append(name)
                    face_ids.append(student_id)
                    confidences.append(confidence)

                else:

                    face_names.append("Scanning")
                    face_ids.append(None)
                    confidences.append(0)

            else:

                face_names.append("Unknown")
                face_ids.append(None)
                confidences.append(0)

        for (top,right,bottom,left), name, student_id, conf in zip(
            face_locations,
            face_names,
            face_ids,
            confidences
        ):

            top *= 4
            right *= 4
            bottom *= 4
            left *= 4

            if name not in ["Unknown","Scanning"]:

                color = (0,255,0)

                label = f"{name} ({conf}%)"

                if student_id not in last_seen or \
                   time.time() - last_seen[student_id] > 10:

                    mark_attendance(
                        student_id,
                        COURSE_ID,
                        "present",
                        "AI"
                    )

                    last_seen[student_id] = time.time()

            elif name == "Scanning":

                color = (255,255,0)

                label = "Scanning..."

            else:

                color = (0,0,255)

                label = "Unknown"

            cv2.rectangle(frame,(left,top),(right,bottom),color,2)

            cv2.rectangle(frame,(left,bottom-35),(right,bottom),color,cv2.FILLED)

            cv2.putText(
                frame,
                label,
                (left+6,bottom-6),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (255,255,255),
                2
            )

        cv2.imshow("Face Attendance System", frame)

        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    start_recognition()