import requests
import json
import uuid
from datetime import datetime
import sqlite3
from connect import GigaChatAuth
import urllib3
import os

urllib3.disable_warnings()

_BACKEND_DIR = os.path.dirname(__file__)
_PROJECT_ROOT = os.path.dirname(_BACKEND_DIR)
DB_PATH = os.path.join(_PROJECT_ROOT, "data", "fitness.db")

DEFAULT_GIGACHAT_AUTH_KEY = (os.getenv("GIGACHAT_AUTH_KEY") or "").strip() or "MDE5ZDAwYWMtMGQ3Yi03MGY1LWI3ZDUtNzc2NmY0ZTQxMGI0OmU4ZTczNTcxLTNjNTItNDkwNS1hZjdlLTFlOWYxMDZiYWRhYQ=="
DEFAULT_SYSTEM_PROMPT = """
Ты – персональный фитнес-тренер.
Подбирай упражнения для пользователя с учетом пола, уровня сложности и цели.
Выводи только JSON с id упражнений на 30 дней.
""".strip()


def ensure_user_program_column(conn: sqlite3.Connection) -> None:
    try:
        cursor = conn.cursor()
        cursor.execute('PRAGMA table_info("user")')
        columns = {row[1] for row in cursor.fetchall()}
        if "program" not in columns:
            cursor.execute('ALTER TABLE "user" ADD COLUMN program TEXT')
            conn.commit()
    except sqlite3.Error as e:
        print(f"Ошибка обновления схемы БД: {e}")


def get_user_data_by_email(email: str) -> dict | None:

    if not os.path.exists(DB_PATH):
        print(f"База данных не найдена по пути {DB_PATH}")
        return None

    try:
        conn = sqlite3.connect(DB_PATH)
        ensure_user_program_column(conn)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, username, gender, weight, height, age, fitness_level, program, goal
            FROM user WHERE email = ?
        """, (email,))
        row = cursor.fetchone()
        conn.close()

        if row:
            columns = ["id", "username", "gender", "weight", "height", "age",
                       "fitness_level", "program", "goal"]
            return dict(zip(columns, row))
        else:
            return None

    except sqlite3.Error as e:
        print(f"Ошибка подключения к базе данных: {e}")
        return None
    
def get_user_data_by_id(id: int) -> dict | None:

    if not os.path.exists(DB_PATH):
        print(f"База данных не найдена по пути {DB_PATH}")
        return None

    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, username, gender, weight, height, age, fitness_level, program, goal
            FROM user WHERE id = ?
        """, (id,))
        row = cursor.fetchone()
        conn.close()

        if row:
            columns = ["id", "username", "gender", "weight", "height", "age",
                       "fitness_level", "program", "goal"]
            return dict(zip(columns, row))
        else:
            return None

    except sqlite3.Error as e:
        print(f"Ошибка подключения к базе данных: {e}")
        return None


def get_exercises() -> list[dict]:

    if not os.path.exists(DB_PATH):
        print(f"База данных не найдена по пути {DB_PATH}")
        return []

    try:
        conn = sqlite3.connect(DB_PATH)
        ensure_user_program_column(conn)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, title, description, category, difficulty, duration_minutes, calories, image_url, video_url, detailed_description, sex
            FROM exercises
        """)
        rows = cursor.fetchall()
        conn.close()

        columns = ["id", "title", "description", "category", "difficulty",
                   "duration_minutes", "calories", "image_url", "video_url",
                   "detailed_description", "sex"]

        exercises_list = [dict(zip(columns, row)) for row in rows]
        return exercises_list

    except sqlite3.Error as e:
        print(f"Ошибка подключения к базе данных: {e}")
        return []


class GigaChatClient:
    def __init__(self, auth: GigaChatAuth, system_prompt: str = ""):
        self.auth = auth
        self.system_prompt = system_prompt

    def generate_training_program(self, user_data: dict, exercises_list: list[dict]) -> dict:

        if not self.auth.access_token:
            return {"error": "Нет токена"}

        url = "https://gigachat.devices.sberbank.ru/api/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.auth.access_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-Session-ID": str(uuid.uuid4())
        }

        prompt = f"""
На основе данных пользователя:
{json.dumps(user_data, ensure_ascii=False)}

И базы упражнений:
{json.dumps(exercises_list, ensure_ascii=False)}

Составь программу тренировок на 30 дней. Выводи **только id упражнений для каждого дня** в формате JSON, например:
{{
    "Day 1": [1, 5, 10],
    "Day 2": [3, 7, 12],
    ...
}}
"""

        payload = {
            "model": "GigaChat-2",
            "messages": [{"role": "system", "content": self.system_prompt},
                         {"role": "user", "content": prompt}],
            "temperature": 0.7
        }

        try:
            response = requests.post(url, headers=headers, data=json.dumps(payload), verify=False, timeout=60)
            if response.status_code != 200:
                return {"error": response.status_code}

            result = response.json()
            content = result["choices"][0]["message"]["content"]


            try:
                program_json = json.loads(content)
            except json.JSONDecodeError:
                program_json = {"error": "Не удалось распарсить JSON из ответа GigaChat", "raw": content}

            usage = result.get("usage", {})
            return {
                "program": program_json,
                "tokens": {
                    "prompt": usage.get("prompt_tokens", 0),
                    "completion": usage.get("completion_tokens", 0),
                    "total": usage.get("total_tokens", 0)
                }
            }

        except requests.RequestException as e:
            return {"error": str(e)}


def save_program_to_user(user_id: int, program_json: dict) -> bool:

    try:
        conn = sqlite3.connect(DB_PATH)
        ensure_user_program_column(conn)
        cursor = conn.cursor()
        cursor.execute("UPDATE user SET program = ? WHERE id = ?",
                       (json.dumps(program_json, ensure_ascii=False), user_id))
        conn.commit()
        conn.close()
        return True
    except sqlite3.Error as e:
        print(f"Ошибка записи программы в базу: {e}")
        return False


def main():
    email = input("Введите ваш email: ").strip()
    user_data = get_user_data_by_email(email)

    if not user_data:
        print("Пользователь не найден в базе. Программа завершена.")
        return

    exercises_list = get_exercises()
    if not exercises_list:
        print("Упражнения не найдены в базе.")
        return

    AUTH_KEY = "MDE5ZDAwYWMtMGQ3Yi03MGY1LWI3ZDUtNzc2NmY0ZTQxMGI0OmU4ZTczNTcxLTNjNTItNDkwNS1hZjdlLTFlOWYxMDZiYWRhYQ=="
    SYSTEM_PROMPT = """
Ты – персональный фитнес-тренер. 
Подбирай упражнения для пользователя с учетом пола, уровня сложности и цели.
Выводи только JSON с id упражнений на 30 дней.
"""

    auth = GigaChatAuth(DEFAULT_GIGACHAT_AUTH_KEY)
    if not auth.get_new_token():
        print("Не удалось получить токен")
        return

    client = GigaChatClient(auth, DEFAULT_SYSTEM_PROMPT)
    result = client.generate_training_program(user_data, exercises_list)

    if "error" in result:
        print(f"Ошибка: {result['error']}")
        return

    program_json = result["program"]



    if save_program_to_user(user_data["id"], program_json):
        pass
    else:
        print("\nНе удалось сохранить программу в базе.")


def get_program(id: int) -> dict | None:
    user_data = get_user_data_by_id(id)

    if not user_data:
        print("Пользователь не найден в базе. Программа завершена.")
        return

    exercises_list = get_exercises()
    if not exercises_list:
        print("Упражнения не найдены в базе.")
        return

    AUTH_KEY = "MDE5ZDAwYWMtMGQ3Yi03MGY1LWI3ZDUtNzc2NmY0ZTQxMGI0OmU4ZTczNTcxLTNjNTItNDkwNS1hZjdlLTFlOWYxMDZiYWRhYQ=="
    SYSTEM_PROMPT = """
Ты – персональный фитнес-тренер. 
Подбирай упражнения для пользователя с учетом пола, уровня сложности и цели.
Выводи только JSON с id упражнений на 30 дней.
"""
 
    auth = GigaChatAuth(AUTH_KEY)
    if not auth.get_new_token():
        print("Не удалось получить токен")
        return

    client = GigaChatClient(auth, SYSTEM_PROMPT)
    result = client.generate_training_program(user_data, exercises_list)

    if "error" in result:
        print(f"Ошибка: {result['error']}")
        return

    program_json = json.dumps(result["program"], ensure_ascii=False, indent=4)
    print("\nПрограмма тренировок на 30 дней (JSON):\n")
    print(program_json)


    tokens = result["tokens"]
    print("\nСтатистика использования токенов:")
    print(f"  - Токены запроса (prompt_tokens): {tokens['prompt']}")
    print(f"  - Токены ответа (completion_tokens): {tokens['completion']}")
    print(f"  - Всего токенов (total_tokens): {tokens['total']}")


    if save_program_to_user(user_data["id"], result["program"]):
        print("\nПрограмма успешно сохранена в базе!")
    else:
        print("\nНе удалось сохранить программу в базе.")

    return result["program"]


if __name__ == "__main__":
    main()
