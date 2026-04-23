#!/usr/bin/env python
import sqlite3
from pathlib import Path


def main():
    db_path = Path(__file__).resolve().parent / "backend" / "instance" / "fitness.db"
    if not db_path.exists():
        print(f"БД не найдена: {db_path}")
        return

    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute("SELECT id, username, email, goal FROM user ORDER BY id").fetchall()
    finally:
        conn.close()

    if not rows:
        print("В таблице users нет записей.")
        return

    print("Содержимое users:")
    for row in rows:
        print(f"- id={row[0]}, username={row[1]}, email={row[2]}, goal={row[3]}")


if __name__ == "__main__":
    main()
