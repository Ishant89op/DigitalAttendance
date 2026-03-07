from database.database import get_connection

conn = get_connection()
try:
    conn.execute(
        "INSERT INTO users (id, name, role, password) VALUES (?, ?, ?, ?)",
        ("admin1", "Admin", "admin", "1234")
    )
    conn.commit()
    print("Admin user created — ID: admin1, Password: 1234")
except Exception as e:
    print(f"Error (user may already exist): {e}")
finally:
    conn.close()
