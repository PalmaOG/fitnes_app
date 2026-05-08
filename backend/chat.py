import requests
import json
import uuid
from datetime import datetime, timedelta
import sqlite3
from connect import GigaChatAuth
import urllib3
import os

urllib3.disable_warnings()

_BACKEND_DIR = os.path.dirname(__file__)
_PROJECT_ROOT = os.path.dirname(_BACKEND_DIR)
DB_PATH = os.path.join(_BACKEND_DIR, "instance", "fitness.db")

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

        days = user_data.get("days", 30)

        prompt = f"""
На основе данных пользователя:
{json.dumps(user_data, ensure_ascii=False)}

И базы упражнений:
{json.dumps(exercises_list, ensure_ascii=False)}

Составь программу тренировок на {days} дней. Выводи **только id упражнений для каждого дня** в формате JSON, например:
{{
    "Day 1": [id1, id2, id3],
    "Day 2": [id1, id2, id3],
    ...
    "Day {days}": [id1, id2, id3]
}}

Важные требования:
1. Создай ровно {days} дней в программе
2. Если пользователь указывал пол (gender) - учитывай его при выборе упражнений
3. Учитывай возраст, вес, рост пользователя
4. Учитывай уровень подготовки (fitness_level)
5. Учитывай цель тренировок (goal)
6. На каждый день нужно 1-5 упражнений
7. Чередуй дни тренировок с днями отдыха (не более 4-5 тренировок в неделю)
8. Дни отдыха обозначай как: "Day 3": []

Ответь ТОЛЬКО JSON, без пояснений.
"""

        payload = {
            "model": "GigaChat-2",
            "messages": [{"role": "system", "content": self.system_prompt},
                         {"role": "user", "content": prompt}],
            "temperature": 0.1
        }

        try:
            response = requests.post(url, headers=headers, data=json.dumps(payload), verify=False, timeout=60)
            if response.status_code != 200:
                return {"error": response.status_code}

            result = response.json()
            content = result["choices"][0]["message"]["content"]

             # Очищаем ответ от возможных маркеров кода
            content = content.strip()
            if content.startswith('```json'):
                content = content[7:]
            if content.startswith('```'):
                content = content[3:]
            if content.endswith('```'):
                content = content[:-3]
            content = content.strip()

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


# ========== НОВАЯ ФУНКЦИЯ: Преобразование Day N в реальные даты ==========
def convert_days_to_dates(program_dict: dict, start_date: datetime = None) -> dict:
    """
    Преобразует ключи "Day 1", "Day 2" и т.д. в реальные даты
    """
    if start_date is None:
        start_date = datetime.now().date()
    
    converted_program = {}
    
    for day_key, exercises in program_dict.items():
        # Извлекаем номер дня из строки типа "Day 1"
        day_number = None
        try:
            # Пытаемся извлечь число из строки
            import re
            numbers = re.findall(r'\d+', day_key)
            if numbers:
                day_number = int(numbers[0])
        except:
            day_number = None
        
        if day_number:
            # Вычисляем реальную дату
            actual_date = start_date + timedelta(days=day_number - 1)
            date_key = actual_date.strftime("%Y-%m-%d")  # Формат: 2024-01-15
            # Альтернативный формат с названием дня недели:
            # date_key = actual_date.strftime("%A, %d.%m.%Y")  # "Monday, 15.01.2024"
        else:
            # Если не удалось извлечь номер, оставляем как есть
            date_key = day_key
        
        converted_program[date_key] = exercises
    
    return converted_program


# ========== НОВАЯ ФУНКЦИЯ: Добавление статуса выполнения к каждому упражнению ==========
def add_status_to_exercises(program_dict: dict) -> dict:
    """
    Добавляет статус выполнения к каждому упражнению
    Формат: {"Day 1": [{"id": 1, "status": "pending"}, {"id": 2, "status": "pending"}]}
    """
    program_with_status = {}
    
    for day_key, exercises in program_dict.items():
        exercises_with_status = []
        
        for exercise in exercises:
            # Если упражнение - это число (ID), преобразуем в словарь с статусом
            if isinstance(exercise, int):
                exercises_with_status.append({
                    "id": exercise,
                    "status": "pending",  # pending - не выполнено, completed - выполнено
                    "completed_at": None
                })
            # Если уже словарь, добавляем статус если его нет
            elif isinstance(exercise, dict):
                if "status" not in exercise:
                    exercise["status"] = "pending"
                if "completed_at" not in exercise:
                    exercise["completed_at"] = None
                exercises_with_status.append(exercise)
            else:
                exercises_with_status.append(exercise)
        
        program_with_status[day_key] = exercises_with_status
    
    return program_with_status


# ========== НОВАЯ ФУНКЦИЯ: Полное преобразование программы для сохранения ==========
def prepare_program_for_save(program_dict: dict, start_date: datetime = None) -> dict:
    """
    Полностью подготавливает программу для сохранения:
    1. Преобразует Day N в реальные даты
    2. Добавляет статус выполнения к упражнениям
    """
    # Сначала преобразуем даты
    program_with_dates = convert_days_to_dates(program_dict, start_date)
    # Затем добавляем статусы
    program_with_status = add_status_to_exercises(program_with_dates)
    
    return program_with_status


# ========== НОВАЯ ФУНКЦИЯ: Получение программы пользователя с датами ==========
def get_user_program_with_dates(user_id: int) -> dict | None:
    """
    Получает программу пользователя, уже преобразованную в даты
    """
    user_data = get_user_data_by_id(user_id)
    if not user_data or not user_data.get("program"):
        return None
    
    try:
        program_dict = json.loads(user_data["program"])
        return program_dict
    except:
        return None


# ========== НОВАЯ ФУНКЦИЯ: Обновление статуса упражнения ==========
def update_exercise_status(user_id: int, date_key: str, exercise_id: int, status: str = "completed"):
    """
    Обновляет статус выполнения конкретного упражнения
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT program FROM user WHERE id = ?", (user_id,))
        row = cursor.fetchone()
        
        if not row or not row[0]:
            return False
        
        program_dict = json.loads(row[0])
        
        # Обновляем статус нужного упражнения
        if date_key in program_dict:
            for exercise in program_dict[date_key]:
                if isinstance(exercise, dict) and exercise.get("id") == exercise_id:
                    exercise["status"] = status
                    exercise["completed_at"] = datetime.now().isoformat() if status == "completed" else None
                    break
        
        # Сохраняем обратно
        cursor.execute("UPDATE user SET program = ? WHERE id = ?", 
                       (json.dumps(program_dict, ensure_ascii=False), user_id))
        conn.commit()
        conn.close()
        return True
        
    except Exception as e:
        print(f"Ошибка обновления статуса: {e}")
        return False

def save_program_to_user(user_id: int, program_json: dict) -> bool:

    try:

        prepared_program = prepare_program_for_save(program_json)

        conn = sqlite3.connect(DB_PATH)
        ensure_user_program_column(conn)
        cursor = conn.cursor()
        cursor.execute("UPDATE user SET program = ? WHERE id = ?",
                       (json.dumps(prepared_program, ensure_ascii=False), user_id))
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

    tokens = result["tokens"]



    if save_program_to_user(user_data["id"], result["program"]):
        print("\nПрограмма успешно сохранена в базе!")
    else:
        print("\nНе удалось сохранить программу в базе.")

    return result["program"]

# ========== НОВАЯ ФУНКЦИЯ: Получение программы с датами для отображения ==========
def get_program_with_dates(user_id: int) -> dict | None:
    """
    Получает программу пользователя, уже преобразованную в даты
    (для использования в Flask маршрутах)
    """
    user_data = get_user_data_by_id(user_id)
    if not user_data or not user_data.get("program"):
        return None
    
    try:
        program_dict = json.loads(user_data["program"])
        return program_dict
    except:
        return None


# ========== НОВАЯ ФУНКЦИЯ: Форматирование для отображения в HTML ==========
def format_program_for_display(program_dict: dict) -> list:
    """
    Преобразует программу в формат, удобный для отображения в HTML
    Возвращает список дней с датами, упражнениями и статусами
    """
    if not program_dict:
        return []
    
    result = []
    # Сортируем по дате
    for date_key in sorted(program_dict.keys()):
        exercises = program_dict[date_key]
        
        # Проверяем, есть ли упражнения (день отдыха)
        has_exercises = False
        exercises_list = []
        
        for ex in exercises:
            if isinstance(ex, dict):
                has_exercises = True
                exercises_list.append(ex)
            elif isinstance(ex, int):
                has_exercises = True
                exercises_list.append({"id": ex, "status": "pending"})
        
        result.append({
            "date": date_key,
            "display_date": datetime.strptime(date_key, "%Y-%m-%d").strftime("%d.%m.%Y"),
            "weekday": datetime.strptime(date_key, "%Y-%m-%d").strftime("%A"),
            "has_exercises": has_exercises,
            "exercises": exercises_list
        })
    
    return result

if __name__ == "__main__":
    main()
