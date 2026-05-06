import sqlite3

# путь к твоей базе
DB_PATH = "instance/fitness.db"

# файл дампа
DUMP_FILE = "dump.sql"

def dump_sqlite(db_path, dump_file):
    conn = sqlite3.connect(db_path)

    with open(dump_file, "w", encoding="utf-8") as f:
        for line in conn.iterdump():
            f.write(f"{line}\n")

    conn.close()
    print(f"✅ Дамп сохранён в {dump_file}")

if __name__ == "__main__":
    dump_sqlite(DB_PATH, DUMP_FILE)