import cv2
import numpy as np
from insightface.app import FaceAnalysis
from database.database import get_connection


# ==============================
# CONFIG
# ==============================
SAMPLES_REQUIRED = 20


# ==============================
# LOAD MODEL
# ==============================
print("Loading InsightFace model...")
app = FaceAnalysis()
app.prepare(ctx_id=-1, det_size=(640, 640))


# ==============================
# REGISTER FUNCTION
# ==============================
def register_student():

    student_id = input("Enter Student ID: ")
    student_name = input("Enter Student Name: ")
    department = input("Enter Department: ")
    semester = int(input("Enter Semester: "))

    cap = cv2.VideoCapture(0)

    encodings_list = []

    print("\nLook at the camera...")
    print("Capturing samples...\n")

    while True:

        ret, frame = cap.read()
        if not ret:
            break

        faces = app.get(frame)

        if faces:

            for face in faces:

                bbox = face.bbox.astype(int)
                embedding = face.embedding

                # Save embedding
                encodings_list.append(embedding)

                # Draw box
                x1, y1, x2, y2 = bbox
                cv2.rectangle(frame, (x1, y1), (x2, y2), (0,255,0), 2)

                print(f"Captured sample {len(encodings_list)}/{SAMPLES_REQUIRED}")

                break  # only one face per frame

        # Display count
        cv2.putText(
            frame,
            f"Samples: {len(encodings_list)}/{SAMPLES_REQUIRED}",
            (10, 40),
            cv2.FONT_HERSHEY_SIMPLEX,
            1,
            (0,255,0),
            2
        )

        cv2.imshow("Student Registration", frame)

        if len(encodings_list) >= SAMPLES_REQUIRED:
            break

        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()

    if len(encodings_list) == 0:
        print("No face captured.")
        return

    print("\nProcessing embeddings...")

    # ==============================
    # AVERAGE EMBEDDING
    # ==============================
    avg_embedding = np.mean(encodings_list, axis=0)

    # Normalize (VERY IMPORTANT)
    avg_embedding = avg_embedding / np.linalg.norm(avg_embedding)

    embedding_bytes = avg_embedding.astype(np.float32).tobytes()

    # ==============================
    # SAVE TO DATABASE
    # ==============================
    conn = get_connection()
    cur = conn.cursor()

    try:
        cur.execute("""
            INSERT INTO students
            (student_id, name, department, semester, face_encoding)
            VALUES (?, ?, ?, ?, ?)
        """, (
            student_id,
            student_name,
            department,
            semester,
            embedding_bytes
        ))

        conn.commit()
        print("\n✔ Registration Successful")

    except:
        print("\n❌ Student already exists")

    finally:
        conn.close()


# ==============================
# RUN
# ==============================
if __name__ == "__main__":
    register_student()