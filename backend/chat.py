import requests
import json
import uuid
from datetime import datetime
import sqlite3
from connect import GigaChatAuth
import urllib3
import os

urllib3.disable_warnings()

DB_PATH = "instance/fitness.db"

def get_user_data_by_email(email: str) -> dict | None:

    if not os.path.exists(DB_PATH):
        print(f"База данных не найдена по пути {DB_PATH}")
        return None

    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT username, gender, weight, height, age, fitness_level, program, goal
            FROM user WHERE email = ?
        """, (email,))
        row = cursor.fetchone()
        conn.close()

        if row:
            columns = ["username", "gender", "weight", "height", "age",
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
            print("Токен недействителен.")
            return {"error": "Нет токена"}

        url = "https://gigachat.devices.sberbank.ru/api/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.auth.access_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-Session-ID": str(uuid.uuid4())
        }

        exercises_text = json.dumps(exercises_list, ensure_ascii=False)

        prompt = f"""
На основе данных пользователя:
{json.dumps(user_data, ensure_ascii=False)}

И базы упражнений:
{exercises_text}

Составь программу тренировок на 30 дней. Выводи **только id упражнений для каждого дня**, в формате:
Day 1: [1, 5, 10]
Day 2: [3, 7, 12]
...
В конце укажи: "Total tokens used: X".
"""

        payload = {
            "model": "GigaChat-2",
            "messages": [{"role": "system", "content": self.system_prompt},
                         {"role": "user", "content": prompt}],
            "temperature": 0.7
        }

        try:
            response = requests.post(url, headers=headers, data=json.dumps(payload), verify=False)

            if response.status_code != 200:
                return {"error": response.status_code}

            result = response.json()
            content = result["choices"][0]["message"]["content"]
            usage = result.get("usage", {})

            return {
                "assistant_response": content,
                "tokens": {
                    "prompt": usage.get("prompt_tokens", 0),
                    "completion": usage.get("completion_tokens", 0),
                    "total": usage.get("total_tokens", 0)
                }
            }

        except requests.RequestException as e:
            return {"error": str(e)}

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
Твоя задача: на основе данных пользователя (username, gender, weight, height, age, fitness_level, program, goal) 
и базы упражнений (id, title, category, difficulty, duration_minutes, calories, sex) составить программу тренировок на 30 дней. 
Выводи только список id упражнений для каждого дня, без описаний, текста или комментариев. 
Подбирай упражнения, подходящие по полу (sex), уровню сложности (difficulty) и цели (goal). 
Оптимизируй нагрузку на каждый день, чередуя категории. 
В конце сообщения укажи: "Total tokens used: X".
"""

    auth = GigaChatAuth(AUTH_KEY)
    if not auth.get_new_token():
        print("Не удалось получить токен")
        return

    client = GigaChatClient(auth, SYSTEM_PROMPT)
    result = client.generate_training_program(user_data, exercises_list)

    if "error" in result:
        print(f"Ошибка: {result['error']}")
    else:
        print("\nПрограмма тренировок на 30 дней:\n")
        print(result["assistant_response"])
        print(f"\nВсего токенов потрачено: {result['tokens']['total']}")

if __name__ == "__main__":
    main()