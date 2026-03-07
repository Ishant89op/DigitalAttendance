import cv2
import mediapipe as mp
import face_recognition
import numpy as np
from database.database import get_connection

# Mediapipe Face Detector
mp_face_detection = mp.solutions.face_detection
face_detector = mp_face_detection.FaceDetection(
    model_selection=0,
    min_detection_confidence=0.7
)

def register_student():

    student_id = input("Enter Student ID: ")
    student_name = input("Enter Student Name: ")
    password = input("Enter Password: ")
    department = input("Enter Department: ")
    semester = input("Enter Semester: ")

    cap = cv2.VideoCapture(0)

    encodings_list = []
    samples_required = 20

    print("\nLook at the camera.")
    print("Capturing face samples...\n")

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        results = face_detector.process(rgb_frame)

        if results.detections:

            for detection in results.detections:

                bbox = detection.location_data.relative_bounding_box

                ih, iw, _ = frame.shape

                x = int(bbox.xmin * iw)
                y = int(bbox.ymin * ih)
                w = int(bbox.width * iw)
                h = int(bbox.height * ih)

                top = y
                right = x + w
                bottom = y + h
                left = x

                cv2.rectangle(frame, (x,y), (x+w,y+h), (0,255,0), 2)

                encodings = face_recognition.face_encodings(
                    rgb_frame,
                    [(top, right, bottom, left)]
                )

                if encodings:

                    encodings_list.append(encodings[0])

                    print(f"Captured sample {len(encodings_list)}/{samples_required}")

        cv2.putText(
            frame,
            f"Samples: {len(encodings_list)}/{samples_required}",
            (10,40),
            cv2.FONT_HERSHEY_SIMPLEX,
            1,
            (0,255,0),
            2
        )

        cv2.imshow("Student Registration", frame)

        if len(encodings_list) >= samples_required:
            break

        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()

    if len(encodings_list) == 0:
        print("No face captured.")
        return

    print("\nProcessing encodings...")

    avg_encoding = np.mean(encodings_list, axis=0).astype(np.float32)

    encoding_bytes = avg_encoding.tobytes()

    conn = get_connection()
    cur = conn.cursor()

    try:

        # Create user account
        cur.execute("""
            INSERT INTO users (id, name, role, password)
            VALUES (?, ?, ?, ?)
        """, (student_id, student_name, "student", password))


        # Create student profile
        cur.execute("""
            INSERT INTO students
            (student_id, user_id, face_encoding, department, semester)
            VALUES (?, ?, ?, ?, ?)
        """, (
            student_id,
            student_id,
            encoding_bytes,
            department,
            semester
        ))

        conn.commit()

        print("\nStudent Registered Successfully.")

    except Exception as e:

        print("\nRegistration failed:", e)

    finally:

        conn.close()


if __name__ == "__main__":
    register_student()