from database.database import init_db
from recognition.recognizer_v2 import start_recognition


def main():

    while True:

        print("\n===== FACE ATTENDANCE SYSTEM =====")
        print("1. Initialize Database")
        print("2. Start Recognition")
        print("3. Exit")

        choice = input("Enter choice: ")

        if choice == "1":
            init_db()

        elif choice == "2":
            start_recognition()

        elif choice == "3":
            break

        else:
            print("Invalid choice")


if __name__ == "__main__":
    main()