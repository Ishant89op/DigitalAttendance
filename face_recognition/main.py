from database.database import init_db, get_connection
from registration.register_student_v2 import register_student
from recognition.recognizer_v2 import start_recognition


def create_default_teacher():

    conn = get_connection()
    cur = conn.cursor()

    try:

        cur.execute("""
        INSERT INTO users (id,name,role,password)
        VALUES ('teacher1','Default Teacher','teacher','1234')
        """)

        conn.commit()

        print("Default teacher created")
        print("Login ID: teacher1 | Password: 1234")

    except:
        print("Teacher already exists")

    finally:
        conn.close()


def main():

    while True:

        print("\n===== FACE ATTENDANCE SYSTEM =====\n")

        print("1. Initialize Database")
        print("2. Create Default Teacher")
        print("3. Register Student")
        print("4. Start Face Recognition")
        print("5. Exit")

        choice = input("\nEnter choice: ")

        if choice == "1":

            init_db()

        elif choice == "2":

            create_default_teacher()

        elif choice == "3":

            register_student()

        elif choice == "4":

            start_recognition()

        elif choice == "5":

            print("Exiting system...")
            break

        else:

            print("Invalid option")


if __name__ == "__main__":
    main()