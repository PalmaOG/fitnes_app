from functools import wraps
import logging
import secrets
import json
from types import SimpleNamespace
from flask import Flask, flash, jsonify, redirect,render_template, request, url_for, session
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import inspect, select
from werkzeug.security import generate_password_hash,check_password_hash
from werkzeug.utils import secure_filename
from datetime import datetime, timedelta, UTC
import os
from chat import get_exercises, prepare_program_for_save  # Импортируем функцию из chat.py
import json


from connect import GigaChatAuth
from chat import GigaChatClient

app = Flask(__name__, template_folder='../frontend', static_folder='../frontend/static')


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s',
)
app.logger.setLevel(logging.INFO)

_BACKEND_DIR = os.path.dirname(__file__)
_PROJECT_ROOT = os.path.dirname(_BACKEND_DIR)
_DB_PATH = os.path.join(_BACKEND_DIR, "instance", "fitness.db")
os.makedirs(os.path.dirname(_DB_PATH), exist_ok=True)
_DB_URI_PATH = _DB_PATH.replace(os.sep, "/")
app.config['SQLALCHEMY_DATABASE_URI'] = f"sqlite:///{_DB_URI_PATH}"
app.secret_key = secrets.token_hex(16)  
app.config['UPLOAD_FOLDER_IMAGES'] = '../frontend/static/images/workout'
app.config['UPLOAD_FOLDER_VIDEOS'] = '../frontend/static/videos'
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024
app.config['ALLOWED_EXTENSIONS_IMAGES'] = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
app.config['ALLOWED_EXTENSIONS_VIDEOS'] = {'mp4', 'webm', 'ogg', 'mov'}


os.makedirs(app.config['UPLOAD_FOLDER_IMAGES'], exist_ok=True)
os.makedirs(app.config['UPLOAD_FOLDER_VIDEOS'], exist_ok=True)

def allowed_file(filename, allowed_extensions):
    """Проверка разрешенного расширения файла"""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in allowed_extensions


db = SQLAlchemy(app)

GOAL_CANONICAL_MAP = {
    'lose_weight': 'lose_weight',
    'maintain_weight': 'maintain_weight',
    'gain_mass': 'gain_mass',
    'похудение': 'lose_weight',
    'похудеть': 'lose_weight',
    'поддержание': 'maintain_weight',
    'поддержание веса': 'maintain_weight',
    'набор': 'gain_mass',
    'набор массы': 'gain_mass',
    'набор мышечной массы': 'gain_mass',
    'набрать массу': 'gain_mass',
}
CANONICAL_GOALS = {'lose_weight', 'maintain_weight', 'gain_mass'}


def normalize_goal(goal_value):
    if not goal_value:
        return None

    normalized = goal_value.strip().lower()
    spaced = ' '.join(normalized.replace('-', ' ').replace('_', ' ').split())
    underscored = spaced.replace(' ', '_')

    if underscored in CANONICAL_GOALS:
        return underscored

    return (
            GOAL_CANONICAL_MAP.get(spaced)
            or GOAL_CANONICAL_MAP.get(underscored)
            or None
    )


def log_user_db_action(user, action, *, details=None):
    if not user:
        return
    extra = f"; {details}" if details else ""
    app.logger.info(
        "%s user %s (id=%s); goal=%s; weight=%s; height=%s; age=%s%s",
        action,
        user.username,
        user.id,
        user.goal,
        user.weight,
        user.height,
        user.age,
        extra,
    )

# Модель пользователя 
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.today)
    gender = db.Column(db.String(20), nullable=True)
    weight = db.Column(db.Float, nullable=True)  
    height = db.Column(db.Float, nullable=True)  
    age = db.Column(db.Integer, nullable=True)
    fitness_level = db.Column(db.String(30), nullable=True)
    goal = db.Column(db.String(40), nullable=True)
    program = db.Column(db.Text, nullable=True)
    first_login = db.Column(db.Boolean, default=True)  
    program = db.Column(db.Text, nullable=True)
    goal = db.Column(db.String(30), nullable=True)
    adm = db.Column(db.Boolean, default=False)

    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)
    
    def is_admin(self):
        return self.adm == True

#Модель упражнений
class Exercise(db.Model):
    __tablename__ = 'exercises'
    
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)  
    description = db.Column(db.Text, nullable=True)    
    category = db.Column(db.String(50), nullable=False)  
    difficulty = db.Column(db.String(20), default='beginner')  
    
    duration_minutes = db.Column(db.Integer, nullable=False)  
    calories = db.Column(db.Integer, nullable=False)  
    
    image_url = db.Column(db.String(500), nullable=False)  
    video_url = db.Column(db.String(500), nullable=True)   
    
    detailed_description = db.Column(db.Text, nullable=True)  

    sex = db.Column(db.String(10), nullable=False)
    
    
    def __repr__(self):
        return f'<Exercise {self.title}>'

# Модель статистики
class Statistics(db.Model):
    __tablename__ = 'statistics'    
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    exercise_id = db.Column(db.Integer, db.ForeignKey('exercises.id'), nullable=False)
    
    duration_seconds = db.Column(db.Integer, nullable=False)  
    calories_burned = db.Column(db.Integer, nullable=False)  
    
    completed = db.Column(db.Boolean, default=True) 

    completed_at = db.Column(db.DateTime, default=datetime.now(UTC))
    
    user = db.relationship('User', backref='statistics')
    exercise = db.relationship('Exercise', backref='statistics')
    
    def __repr__(self):
        return f'<Statistics {self.user_id} - {self.exercise_id}>'
    

class FavoriteExercise(db.Model):
    __tablename__ = 'favorite_exercises'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    exercise_id = db.Column(db.Integer, db.ForeignKey('exercises.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now(UTC))
    
    # Связи
    user = db.relationship('User', backref='favorites')
    exercise = db.relationship('Exercise', backref='favorited_by')
    
    __table_args__ = (db.UniqueConstraint('user_id', 'exercise_id', name='unique_user_exercise_favorite'),)
    
    def __repr__(self):
        return f'<FavoriteExercise user={self.user_id} exercise={self.exercise_id}>'


def calculate_achievements(user_id):
    """Расчет достижений пользователя"""
    from datetime import datetime, timedelta
    
    # Получаем всю статистику пользователя
    stats = Statistics.query.filter_by(user_id=user_id).all()
    total_workouts = len(stats)
    total_calories = sum(stat.calories_burned for stat in stats)
    
    # Уникальные дни тренировок для серии
    workout_dates = set()
    for stat in stats:
        if stat.completed_at:
            workout_dates.add(stat.completed_at.date())
    workout_dates = sorted(workout_dates)
    
    # Расчет лучшей серии
    current_streak = 0
    best_streak = 0
    last_date = None
    current_streak_days = 0
    
    for date in workout_dates:
        if last_date and (date - last_date).days == 1:
            current_streak_days += 1
        else:
            current_streak_days = 1
        best_streak = max(best_streak, current_streak_days)
        last_date = date
    
    # Текущая серия (последние дни)
    current_streak = 0
    if workout_dates:
        today = datetime.now(UTC).date()
        date = today
        while date in workout_dates:
            current_streak += 1
            date -= timedelta(days=1)
    
    # Достижения
    achievements = {
        'total_count': 8,  # Всего достижений
        'achieved_count': 0,
        'progress_percent': 0,
        'first_workout': {'achieved': False, 'current': total_workouts, 'target': 1},
        'five_workouts': {'achieved': False, 'current': total_workouts, 'target': 5},
        'thirty_workouts': {'achieved': False, 'current': total_workouts, 'target': 30},
        'hundred_workouts': {'achieved': False, 'current': total_workouts, 'target': 100},
        'five_k_calories': {'achieved': False, 'current': total_calories, 'target': 5000},
        'ten_k_calories': {'achieved': False, 'current': total_calories, 'target': 10000},
        'streak_7': {'achieved': False, 'current': current_streak, 'target': 7},
        'streak_30': {'achieved': False, 'current': current_streak, 'target': 30}
    }
    
    # Проверяем выполненные достижения
    if total_workouts >= 1:
        achievements['first_workout']['achieved'] = True
        achievements['achieved_count'] += 1
    if total_workouts >= 5:
        achievements['five_workouts']['achieved'] = True
        achievements['achieved_count'] += 1
    if total_workouts >= 30:
        achievements['thirty_workouts']['achieved'] = True
        achievements['achieved_count'] += 1
    if total_workouts >= 100:
        achievements['hundred_workouts']['achieved'] = True
        achievements['achieved_count'] += 1
    if total_calories >= 5000:
        achievements['five_k_calories']['achieved'] = True
        achievements['achieved_count'] += 1
    if total_calories >= 10000:
        achievements['ten_k_calories']['achieved'] = True
        achievements['achieved_count'] += 1
    if current_streak >= 7:
        achievements['streak_7']['achieved'] = True
        achievements['achieved_count'] += 1
    if current_streak >= 30:
        achievements['streak_30']['achieved'] = True
        achievements['achieved_count'] += 1
    
    # Процент выполнения
    achievements['progress_percent'] = int((achievements['achieved_count'] / achievements['total_count']) * 100)
    
    return achievements


def parse_program(program_dict: dict):
    full_program = {}

    for day, exercise_ids in program_dict.items():
        full_exercises = []
        
        for exercise_id in exercise_ids:
            # Получаем упражнение из БД
            exercise = db.session.get(Exercise, exercise_id)
            
            if exercise:
                # Преобразуем объект Exercise в словарь
                exercise_dict = {
                    'id': exercise.id,
                    'title': exercise.title,
                    'description': exercise.description or '',
                    'category': exercise.category,
                    'difficulty': exercise.difficulty,
                    'duration_minutes': exercise.duration_minutes,
                    'calories': exercise.calories,
                    'image_url': exercise.image_url,
                    'video_url': exercise.video_url,
                    'detailed_description': exercise.detailed_description or '',
                    'sex': exercise.sex
                }
                full_exercises.append(exercise_dict)
            else:
                # Если упражнение не найдено, добавляем заглушку
                full_exercises.append({
                    'id': exercise_id,
                    'title': 'Упражнение не найдено',
                    'description': 'Данное упражнение больше недоступно',
                    'category': 'unknown',
                    'difficulty': 'beginner',
                    'duration_minutes': 0,
                    'calories': 0,
                    'image_url': '/static/images/default.jpg',
                    'video_url': None,
                    'detailed_description': '',
                    'sex': 'unisex'
                })
        
        full_program[day] = full_exercises
    
    return full_program


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Пожалуйста, войдите в систему', 'warning')
            return redirect(url_for('auth'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if 'user_id' not in session:
            flash('Пожалуйста, войдите в систему', 'warning')
            return redirect(url_for('auth'))
        user = db.session.get(User, session['user_id'])
        if not user or not user.is_admin():
            flash('У вас нет прав доступа к этой странице', 'error')
            return redirect(url_for('main'))
        
        return f(*args, **kwargs)
    return wrapper


def ensure_user_program_column() -> None:
    try:
        inspector = inspect(db.engine)
        columns = {col["name"] for col in inspector.get_columns("user")}
        if "program" not in columns:
            with db.engine.begin() as conn:
                conn.exec_driver_sql('ALTER TABLE "user" ADD COLUMN program TEXT')
    except Exception as e:
        app.logger.warning("Не удалось проверить/обновить схему БД для program: %s", e)


_schema_checked = False


@app.before_request
def _ensure_schema_once():
    global _schema_checked
    if _schema_checked:
        return

    ensure_user_program_column()
    _schema_checked = True

# Маршруты страниц
@app.route('/')
def welcome():
    if 'user_id' in session:
        return redirect(url_for('main'))
    else:
        return redirect(url_for('auth'))

@app.route('/auth')
def auth():
    if 'user_id' in session:
        return redirect(url_for('main'))
    else:
        return render_template("reg_log.html")

@app.route('/main')
@login_required
def main():
    user = db.session.get(User, session['user_id'])
    is_admin = user.is_admin() if user else False

    # Получаем сегодняшнюю дату
    from datetime import datetime, timedelta
    today = datetime.now(UTC).date()
    today_str = today.strftime("%Y-%m-%d")

    # Получаем сегодняшние упражнения из программы пользователя
    today_exercises = []
    
    if user and user.program:
        try:
            program = json.loads(user.program) if isinstance(user.program, str) else user.program
            
            # Проверяем, есть ли тренировка на сегодня
            if today_str in program:
                day_exercises = program[today_str]
                
                # Извлекаем ID упражнений
                exercise_ids = []
                exercise_statuses = {}
                
                for item in day_exercises:
                    if isinstance(item, dict):
                        exercise_id = item.get('id')
                        if exercise_id:
                            exercise_ids.append(exercise_id)
                            exercise_statuses[exercise_id] = item.get('status', 'pending')
                    elif isinstance(item, int):
                        exercise_ids.append(item)
                        exercise_statuses[item] = 'pending'
                
                if exercise_ids:
                    # Получаем полные данные упражнений из БД
                    exercises = Exercise.query.filter(Exercise.id.in_(exercise_ids)).all()
                    exercise_map = {ex.id: ex for ex in exercises}
                    
                    # Сохраняем порядок из программы
                    for ex_id in exercise_ids:
                        if ex_id in exercise_map:
                            exercise = exercise_map[ex_id]
                            today_exercises.append({
                                'id': exercise.id,
                                'title': exercise.title,
                                'description': exercise.description,
                                'category': exercise.category,
                                'difficulty': exercise.difficulty,
                                'duration_minutes': exercise.duration_minutes,
                                'calories': exercise.calories,
                                'image_url': exercise.image_url,
                                'video_url': exercise.video_url,
                                'status': exercise_statuses.get(ex_id, 'pending')
                            })
        except Exception as e:
            app.logger.error(f"Ошибка загрузки программы: {e}")

    # Получаем прогресс программы
    program_progress = 0
    total_exercises_all = 0
    if user and user.program:
        try:
            program = json.loads(user.program) if isinstance(user.program, str) else user.program
            total_planned = 0
            completed = 0
            
            

            for date, exercises in program.items():
                for ex in exercises:
                    total_planned += 1
                    if isinstance(ex, dict):
                        # Новый формат с статусом
                        if ex.get('status') == 'completed':
                            completed += 1
                    elif isinstance(ex, int):
                        # Старый формат (не выполнено)
                        pass
            if total_planned > 0:
                program_progress = round((completed / total_planned) * 100)
                if program_progress > 100:
                    program_progress = 100

            total_exercises_all = completed
        except Exception:
            pass

    # Статистика
    today_start = datetime(today.year, today.month, today.day)
    today_stats = Statistics.query.filter(
        Statistics.user_id == user.id,
        Statistics.completed_at >= today_start
    ).all() if user else []
    
    all_stats = Statistics.query.filter_by(user_id=user.id).all() if user else []
    
    total_calories_today = sum(stat.calories_burned for stat in today_stats)
    total_duration_today = sum(stat.duration_seconds for stat in today_stats) // 60
    total_exercises_today = len(today_stats)
    
    total_calories_all = sum(stat.calories_burned for stat in all_stats)
    total_duration_all = sum(stat.duration_seconds for stat in all_stats) // 60
    
    # Сравнение с предыдущим днем
    yesterday_start = today_start - timedelta(days=1)
    yesterday_stats = Statistics.query.filter(
        Statistics.user_id == user.id,
        Statistics.completed_at >= yesterday_start,
        Statistics.completed_at < today_start
    ).all() if user else []
    
    yesterday_calories = sum(stat.calories_burned for stat in yesterday_stats)
    
    progress_percent_change = 0
    if yesterday_calories > 0:
        progress_percent_change = round(((total_calories_today - yesterday_calories) / yesterday_calories) * 100)
    
    current_stat = {
        "total_calories_today": total_calories_today,
        "total_duration_today": total_duration_today,
        "total_exercises_today": total_exercises_today,
        "total_calories_all": total_calories_all,
        "total_duration_all": total_duration_all,
        "total_exercises_all": total_exercises_all,
        "program_progress": program_progress,
        "progress_percent_change": progress_percent_change
    }

    if program_progress == 100 and user.goal != "maintain_weight":
        program_completed = True
    else:
        program_completed = False

    return render_template('index.html', 
                         username=session.get('username'), 
                         first_login=session.get('first_login'),
                         is_admin=is_admin,
                         today_exercises=today_exercises,
                         current_stat=current_stat,
                         program_completed=program_completed,
                         user_data = user)


@app.route('/admin')
@login_required
@admin_required
def admin_panel():
    users = User.query.all()
    exercises = Exercise.query.all()
    return render_template('admin.html', 
                         username=session.get('username'), 
                         users=users, 
                         exercises=exercises)

@app.route('/programs')
@login_required
def workouts():
    exercises = Exercise.query.all()
    # Преобразуем объекты Exercise в словари для JSON сериализации
    user = db.session.get(User, session['user_id'])
    if not user:
        flash('Пользователь не найден', 'error')
        return redirect(url_for('workouts'))
    
    exercises_list = []
    for exercise in exercises:
        if exercise.sex == user.gender:
            exercise_dict = {
                'id': exercise.id,
                'title': exercise.title,
                'description': exercise.description,
                'category': exercise.category,
                'difficulty': exercise.difficulty,
                'duration_minutes': exercise.duration_minutes,
                'calories': exercise.calories,
                'image_url': exercise.image_url,
                'video_url': exercise.video_url,
                'detailed_description': exercise.detailed_description
            }
            exercises_list.append(exercise_dict)

    return render_template('programs.html', username=session.get('username'), exercises=exercises_list, is_admin = user.adm)


@app.route('/my-training')
@login_required
def my_training():
    ensure_user_program_column()
    user = db.session.get(User, session['user_id'])

    rendered_program = None
    if user and user.program:
        try:
            program = json.loads(user.program)
        except Exception:
            program = None

        if isinstance(program, dict):
            # Получаем все ID упражнений из программы
            all_exercise_ids = set()
            day_items: list[tuple[str, list]] = []

            for date_key, exercises_data in program.items():
                ids = []
                # exercises_data может быть списком чисел или списком словарей
                for item in exercises_data:
                    if isinstance(item, dict):
                        # Новый формат: {"id": 1, "status": "pending"}
                        exercise_id = item.get('id')
                        if exercise_id:
                            ids.append(exercise_id)
                            all_exercise_ids.add(exercise_id)
                    elif isinstance(item, int):
                        # Старый формат: просто число
                        ids.append(item)
                        all_exercise_ids.add(item)
                
                day_items.append((date_key, ids, exercises_data))  # Сохраняем оригинальные данные для статусов

            # Получаем названия упражнений из БД
            title_map: dict[int, str] = {}
            exercises_map: dict[int, dict] = {}  # Для полных данных упражнений
            if all_exercise_ids:
                exercises = Exercise.query.filter(Exercise.id.in_(list(all_exercise_ids))).all()
                for exercise in exercises:
                    title_map[exercise.id] = exercise.title
                    exercises_map[exercise.id] = {
                        'id': exercise.id,
                        'title': exercise.title,
                        'category': exercise.category,
                        'difficulty': exercise.difficulty,
                        'duration_minutes': exercise.duration_minutes,
                        'calories': exercise.calories,
                        'image_url': exercise.image_url
                    }

            def format_date(date_str: str) -> str:
                """Форматирует дату из YYYY-MM-DD в читаемый формат"""
                try:
                    from datetime import datetime
                    date_obj = datetime.strptime(date_str, "%Y-%m-%d")
                    # Формат: "15 января, Понедельник"
                    months = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня',
                             'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря']
                    weekdays = ['Понедельник', 'Вторник', 'Среда', 'Четверг', 'Пятница', 'Суббота', 'Воскресенье']
                    return f"{date_obj.day} {months[date_obj.month - 1]}, {weekdays[date_obj.weekday()]}"
                except:
                    return date_str

            def get_exercise_status(exercises_data, exercise_id) -> str:
                """Получает статус выполнения упражнения"""
                for item in exercises_data:
                    if isinstance(item, dict) and item.get('id') == exercise_id:
                        return item.get('status', 'pending')
                return 'pending'

            rendered_program = []
            for date_key, ids, exercises_data in day_items:
                # Сортируем ID для сохранения порядка (опционально)
                # ids уже в том порядке, в котором они были в JSON
                
                # Формируем список упражнений с полными данными
                exercises_list = []
                for ex_id in ids:
                    exercises_list.append({
                        'id': ex_id,
                        'title': title_map.get(ex_id, f"Упражнение #{ex_id}"),
                        'status': get_exercise_status(exercises_data, ex_id),
                        **exercises_map.get(ex_id, {})  # Добавляем остальные данные если есть
                    })
                
                rendered_program.append({
                    "date": date_key,
                    "day": format_date(date_key),
                    "exercises": exercises_list,
                    "has_exercises": len(ids) > 0
                })

    return render_template('my_training.html', 
                         username=session.get('username'), 
                         program=rendered_program,
                         is_admin = user.adm)


@app.route('/my-training/day/<date>')
@login_required
def my_training_day(date):
    ensure_user_program_column()
    user = db.session.get(User, session['user_id'])

    if not user or not user.program:
        flash('Программа тренировок не найдена. Сначала сгенерируйте тренировку.', 'warning')
        return redirect(url_for('my_training'))

    try:
        program = json.loads(user.program) if isinstance(user.program, str) else user.program
    except Exception:
        flash('Не удалось прочитать программу тренировок.', 'error')
        return redirect(url_for('my_training'))

    if not isinstance(program, dict):
        flash('Неверный формат программы тренировок.', 'error')
        return redirect(url_for('my_training'))

    if date not in program:
        flash('Тренировка для этого дня не найдена.', 'warning')
        return redirect(url_for('my_training'))

    day_exercises = program[date]
    
    # Извлекаем ID упражнений и их статусы
    exercise_ids = []
    exercise_statuses = {}
    all_completed = True
    
    for item in day_exercises:
        if isinstance(item, dict):
            exercise_id = item.get('id')
            status = item.get('status', 'pending')
            if exercise_id:
                exercise_ids.append(exercise_id)
                exercise_statuses[exercise_id] = status
                if status != 'completed':
                    all_completed = False
        elif isinstance(item, int):
            exercise_ids.append(item)
            exercise_statuses[item] = 'pending'
            all_completed = False

    # Получаем упражнения из БД
    exercises = Exercise.query.filter(Exercise.id.in_(exercise_ids)).all() if exercise_ids else []
    exercise_map = {exercise.id: exercise for exercise in exercises}
    
    # Сохраняем порядок из программы
    ordered_exercises = []
    for ex_id in exercise_ids:
        if ex_id in exercise_map:
            exercise = exercise_map[ex_id]
            exercise.status = exercise_statuses.get(ex_id, 'pending')
            ordered_exercises.append(exercise)

    # Форматируем дату для отображения
    from datetime import datetime
    try:
        date_obj = datetime.strptime(date, "%Y-%m-%d")
        months = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня',
                  'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря']
        weekdays = ['Понедельник', 'Вторник', 'Среда', 'Четверг', 'Пятница', 'Суббота', 'Воскресенье']
        day_label = f"{date_obj.day} {months[date_obj.month - 1]}, {weekdays[date_obj.weekday()]}"
    except:
        day_label = date

    # Передаем флаг all_completed в шаблон
    return render_template(
        'my_training_day.html',
        username=session.get('username'),
        day_label=day_label,
        exercises=ordered_exercises,
        date=date,
        all_completed=all_completed  # Добавляем флаг
    )


@app.route('/api/regenerate-program', methods=['POST'])
@login_required
def regenerate_program():
    try:
        user_id = session.get('user_id')
        
        if not user_id:
            flash('Пользователь не авторизован', 'error')
            return redirect(url_for('auth'))
        
        user = db.session.get(User, user_id)
        
        if not user:
            flash('Пользователь не найден', 'error')
            return redirect(url_for('profile'))
        
        # Получаем данные из формы
        age = request.form.get('age')
        height = request.form.get('height')
        weight = request.form.get('weight')
        fitness_level = request.form.get('fitness_level')
        goal = request.form.get('goal', 'maintain_weight')
        
        # Преобразование типов
        try:
            age = int(age) if age else None
            height = float(height) if height else None
            weight = float(weight) if weight else None
        except ValueError:
            flash('Пожалуйста, введите корректные числовые значения', 'error')
            return redirect(url_for('profile'))
        
        # Обновляем данные пользователя
        user.age = age
        user.height = height
        user.weight = weight
        user.fitness_level = fitness_level
        user.goal = goal
        
        db.session.commit()
        
        # Проверяем, что все необходимые поля заполнены
        if not all([user.age, user.height, user.weight, user.fitness_level, user.goal]):
            flash('Пожалуйста, заполните все поля', 'error')
            return redirect(url_for('profile'))
        
        # Импортируем необходимые модули для генерации
        from chat import DEFAULT_GIGACHAT_AUTH_KEY, DEFAULT_SYSTEM_PROMPT, GigaChatAuth, GigaChatClient
        
        if not DEFAULT_GIGACHAT_AUTH_KEY:
            flash('Не настроен ключ доступа GigaChat', 'error')
            return redirect(url_for('profile'))
        
        # Получаем все упражнения из БД
        exercises = Exercise.query.all()
        exercises_list = []
        for exercise in exercises:
            # Фильтруем упражнения по полу пользователя
            if user.gender and exercise.sex not in [user.gender, 'unisex']:
                continue
            exercises_list.append({
                'id': exercise.id,
                'title': exercise.title,
                'description': exercise.description,
                'category': exercise.category,
                'difficulty': exercise.difficulty,
                'duration_minutes': exercise.duration_minutes,
                'calories': exercise.calories,
                'image_url': exercise.image_url,
                'video_url': exercise.video_url,
                'detailed_description': exercise.detailed_description,
                'sex': exercise.sex,
            })
        
        # Данные пользователя для генерации
        user_data = {
            "id": user.id,
            "username": user.username,
            "gender": user.gender,
            "weight": user.weight,
            "height": user.height,
            "age": user.age,
            "fitness_level": user.fitness_level,
            "program": None,
            "goal": user.goal,
            "days": 30  # Генерируем на 30 дней
        }
        
        # Получаем токен и генерируем программу
        auth = GigaChatAuth(DEFAULT_GIGACHAT_AUTH_KEY)
        if not auth.get_new_token():
            flash('Не удалось получить токен GigaChat', 'error')
            return redirect(url_for('profile'))
        
        client = GigaChatClient(auth, DEFAULT_SYSTEM_PROMPT)
        result = client.generate_training_program(user_data, exercises_list)
        
        if "error" in result:
            flash(f"Ошибка генерации: {result['error']}", 'error')
            return redirect(url_for('profile'))
        
        program_json = result.get("program")
        if isinstance(program_json, dict) and "error" in program_json:
            flash("Ошибка генерации: не удалось распарсить JSON из ответа", 'error')
            return redirect(url_for('profile'))
        
        # Преобразуем программу в формат с датами и статусами
        from datetime import datetime
        from chat import prepare_program_for_save
        
        prepared_program = prepare_program_for_save(program_json)
        
        # Сохраняем программу в БД
        user.program = json.dumps(prepared_program, ensure_ascii=False)
        db.session.commit()
        
        flash('Программа тренировок успешно cгенерирована!', 'success')
        return redirect(url_for('my_training'))
        
    except Exception as e:
        db.session.rollback()
        app.logger.exception("Ошибка перегенерации программы: %s", e)
        flash(f'Ошибка перегенерации: {str(e)}', 'error')
        return redirect(url_for('profile'))
    

@app.route('/api/check-day-completion/<date>', methods=['GET'])
@login_required
def check_day_completion(date):
    try:
        user_id = session.get('user_id')
        user = db.session.get(User, user_id)
        
        if not user or not user.program:
            return jsonify({'all_completed': False})
        
        program = json.loads(user.program) if isinstance(user.program, str) else user.program
        
        if date not in program:
            return jsonify({'all_completed': False})
        
        day_exercises = program[date]
        all_completed = True
        
        for item in day_exercises:
            if isinstance(item, dict):
                status = item.get('status', 'pending')
                if status != 'completed':
                    all_completed = False
                    break
            elif isinstance(item, int):
                all_completed = False
                break
        
        return jsonify({'all_completed': all_completed})
        
    except Exception as e:
        app.logger.error(f"Ошибка проверки дня: {e}")
        return jsonify({'all_completed': False})

@app.route('/api/update-exercise-status', methods=['POST'])
@login_required
def update_exercise_status():
    try:
        data = request.get_json()
        user_id = session.get('user_id')
        date = data.get('date')
        exercise_id = data.get('exercise_id')
        status = data.get('status', 'completed')
        
        if not date or not exercise_id:
            return jsonify({'success': False, 'error': 'Недостаточно данных'}), 400
        
        user = db.session.get(User, user_id)
        if not user:
            return jsonify({'success': False, 'error': 'Пользователь не найден'}), 404
        
        # Если программы нет, создаем пустую
        if not user.program:
            program = {}
        else:
            program = json.loads(user.program) if isinstance(user.program, str) else user.program
        
        # Обновляем статус упражнения в указанную дату
        if date not in program:
            program[date] = []
        
        updated = False
        for i, exercise in enumerate(program[date]):
            if isinstance(exercise, dict) and exercise.get('id') == exercise_id:
                program[date][i]['status'] = status
                if status == 'completed':
                    program[date][i]['completed_at'] = datetime.now(UTC).isoformat()
                updated = True
                break
            elif isinstance(exercise, int) and exercise == exercise_id:
                program[date][i] = {
                    'id': exercise_id,
                    'status': status,
                    'completed_at': datetime.now(UTC).isoformat() if status == 'completed' else None
                }
                updated = True
                break
        
        # Если упражнение не найдено, добавляем новое
        if not updated:
            program[date].append({
                'id': exercise_id,
                'status': status,
                'completed_at': datetime.now(UTC).isoformat() if status == 'completed' else None
            })
        
        user.program = json.dumps(program, ensure_ascii=False)
        db.session.commit()
        
        return jsonify({'success': True, 'message': 'Статус упражнения обновлен'})
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/generate-training', methods=['POST'])
@login_required
def generate_training():
    ensure_user_program_column()
    user = db.session.get(User, session['user_id'])
    if not user:
        flash('Пользователь не найден', 'error')
        return redirect(url_for('my_training'))
    
    if request.content_type == 'application/json':
        regen_data = request.get_json()
        regen_goal = regen_data.get('goal')
        if regen_data:
            user.goal = regen_goal

    required_fields = [user.gender, user.weight, user.height, user.age, user.fitness_level, user.goal]
    if not all(required_fields):
        flash('Для генерации тренировок нужно заполнить дополнительные сведения', 'error')
        return redirect(url_for('profile'))

    from chat import DEFAULT_GIGACHAT_AUTH_KEY, DEFAULT_SYSTEM_PROMPT

    if not DEFAULT_GIGACHAT_AUTH_KEY:
        flash('Не настроен ключ доступа GigaChat (GIGACHAT_AUTH_KEY)', 'error')
        return redirect(url_for('my_training'))
    
    days = request.form.get('days', 30)  
    try:
        days = int(days)
        if days < 1:
            days = 1
        if days > 30:
            days = 30
    except (ValueError, TypeError):
        days = 14

    try:
        exercises = Exercise.query.all()
        exercises_list = []
        for exercise in exercises:
            if user.gender and exercise.sex != user.gender:
                continue
            exercises_list.append({
                'id': exercise.id,
                'title': exercise.title,
                'description': exercise.description,
                'category': exercise.category,
                'difficulty': exercise.difficulty,
                'duration_minutes': exercise.duration_minutes,
                'calories': exercise.calories,
                'image_url': exercise.image_url,
                'video_url': exercise.video_url,
                'detailed_description': exercise.detailed_description,
                'sex': exercise.sex,
            })

       

        user_data = {
            "id": user.id,
            "username": user.username,
            "gender": user.gender,
            "weight": user.weight,
            "height": user.height,
            "age": user.age,
            "fitness_level": user.fitness_level,
            "program": None,
            "goal": user.goal,
            "days": days
        }

        auth = GigaChatAuth(DEFAULT_GIGACHAT_AUTH_KEY)
        if not auth.get_new_token():
            flash('Не удалось получить токен GigaChat', 'error')
            return redirect(url_for('my_training'))

        client = GigaChatClient(auth, DEFAULT_SYSTEM_PROMPT)
        result = client.generate_training_program(user_data, exercises_list)
        if "error" in result:
            flash(f"Ошибка генерации: {result['error']}", 'error')
            return redirect(url_for('my_training'))

        program_json = result.get("program")
        if isinstance(program_json, dict) and "error" in program_json:
            flash("Ошибка генерации: не удалось распарсить JSON из ответа", 'error')
            return redirect(url_for('my_training'))
        
        # Проверяем, что количество дней соответствует запрошенному
        actual_days = len(program_json)
        if actual_days != days:
            app.logger.warning(f"Запрошено {days} дней, получено {actual_days}")
        
        prepared_program = prepare_program_for_save(program_json)

        user.program = json.dumps(prepared_program, ensure_ascii=False)
        db.session.commit()

        flash('Тренировка сгенерирована', 'success')
        return redirect(url_for('my_training'))
    except Exception as e:
        app.logger.exception("Ошибка генерации тренировки: %s", e)
        flash(f'Ошибка генерации: {e}', 'error')
        return redirect(url_for('my_training'))


@app.route('/profile')
@login_required
def profile():
    user = db.session.get(User,session['user_id'])
    
    # Получаем избранные упражнения пользователя
    favorites = FavoriteExercise.query.filter_by(user_id=user.id).all()
    favorite_exercises = [fav.exercise for fav in favorites]
    
    # ========== СТАТИСТИКА ==========
    from datetime import datetime, timedelta
    
    # Общая статистика за все время
    all_stats = Statistics.query.filter_by(user_id=user.id).all()
    
    total_workouts = len(all_stats)
    total_calories = sum(stat.calories_burned for stat in all_stats)
    total_seconds = sum(stat.duration_seconds for stat in all_stats)
    total_minutes = total_seconds // 60
    
    # Уникальные дни тренировок (для серии)
    workout_dates = set()
    for stat in all_stats:
        date = stat.completed_at.date() if stat.completed_at else None
        if date:
            workout_dates.add(date)
    workout_dates = sorted(workout_dates)
    
    # Расчет лучшей серии
    best_streak = 0
    current_streak = 0
    last_date = None
    
    for date in workout_dates:
        if last_date and (date - last_date).days == 1:
            current_streak += 1
        else:
            current_streak = 1
        best_streak = max(best_streak, current_streak)
        last_date = date
    
    # Статистика за сегодня
    today = datetime.now(UTC).date()
    today_start = datetime(today.year, today.month, today.day)
    today_stats = Statistics.query.filter(
        Statistics.user_id == user.id,
        Statistics.completed_at >= today_start
    ).all()
    
    today_calories = sum(stat.calories_burned for stat in today_stats)
    today_minutes = sum(stat.duration_seconds for stat in today_stats) // 60
    today_workouts = len(today_stats)
    
    # Статистика за неделю
    week_ago = datetime.now(UTC) - timedelta(days=7)
    week_stats = Statistics.query.filter(
        Statistics.user_id == user.id,
        Statistics.completed_at >= week_ago
    ).all()
    
    week_calories = sum(stat.calories_burned for stat in week_stats)
    week_minutes = sum(stat.duration_seconds for stat in week_stats) // 60
    week_workouts = len(week_stats)
    
    # Статистика за месяц
    month_ago = datetime.now(UTC) - timedelta(days=30)
    month_stats = Statistics.query.filter(
        Statistics.user_id == user.id,
        Statistics.completed_at >= month_ago
    ).all()
    
    month_calories = sum(stat.calories_burned for stat in month_stats)
    month_minutes = sum(stat.duration_seconds for stat in month_stats) // 60
    month_workouts = len(month_stats)
    
    # ========== ДАННЫЕ ДЛЯ ГРАФИКОВ ==========
    # Данные для графика тренировок за последние 7 дней
    chart_labels = []
    chart_calories = []
    chart_minutes = []
    
    for i in range(6, -1, -1):
        date = today - timedelta(days=i)
        date_start = datetime(date.year, date.month, date.day)
        date_end = date_start + timedelta(days=1)
        
        day_stats = Statistics.query.filter(
            Statistics.user_id == user.id,
            Statistics.completed_at >= date_start,
            Statistics.completed_at < date_end
        ).all()
        
        day_calories = sum(stat.calories_burned for stat in day_stats)
        day_minutes = sum(stat.duration_seconds for stat in day_stats) // 60
        
        chart_labels.append(date.strftime('%d.%m'))
        chart_calories.append(day_calories)
        chart_minutes.append(day_minutes)
    
    # Данные для категорий упражнений
    category_names = ['cardio', 'strength', 'yoga', 'stretching']
    category_labels = ['Кардио', 'Силовые', 'Йога', 'Растяжка']
    category_counts = [0, 0, 0, 0]
    
    for stat in all_stats:
        exercise = db.session.get(Exercise,stat.exercise_id)
        if exercise and exercise.category in category_names:
            idx = category_names.index(exercise.category)
            category_counts[idx] += 1
    
    # Топ упражнений
    exercise_stats = {}
    for stat in all_stats:
        if stat.exercise_id not in exercise_stats:
            exercise_stats[stat.exercise_id] = {
                'count': 0,
                'total_duration': 0,
                'total_calories': 0
            }
        exercise_stats[stat.exercise_id]['count'] += 1
        exercise_stats[stat.exercise_id]['total_duration'] += stat.duration_seconds
        exercise_stats[stat.exercise_id]['total_calories'] += stat.calories_burned
    
    # Получаем топ-5 упражнений
    top_exercises = []
    for ex_id, stats in sorted(exercise_stats.items(), key=lambda x: x[1]['count'], reverse=True)[:5]:
        exercise = db.session.get(Exercise,ex_id)
        if exercise:
            top_exercises.append({
                'title': exercise.title,
                'count': stats['count'],
                'duration': stats['total_duration'] // 60,
                'calories': stats['total_calories']
            })

    
    return render_template('profile.html', 
                         username=session.get('username'),
                         user=user,
                         is_admin = user.adm,
                         favorite_exercises=favorite_exercises,
                         # Основная статистика
                         total_workouts=total_workouts,
                         total_calories=total_calories,
                         total_minutes=total_minutes,
                         best_streak=best_streak,
                         # Статистика за сегодня
                         today_calories=today_calories,
                         today_minutes=today_minutes,
                         today_workouts=today_workouts,
                         # Статистика за неделю
                         week_calories=week_calories,
                         week_minutes=week_minutes,
                         week_workouts=week_workouts,
                         # Статистика за месяц
                         month_calories=month_calories,
                         month_minutes=month_minutes,
                         month_workouts=month_workouts,
                         # Данные для графиков
                         chart_labels=chart_labels,
                         chart_calories=chart_calories,
                         chart_minutes=chart_minutes,
                         category_labels=category_labels,
                         category_counts=category_counts,
                         top_exercises=top_exercises)

#Маршруты сервера
@app.route('/api/admin/set-admin/<int:user_id>', methods=['POST'])
@login_required
@admin_required
def set_admin(user_id):
    try:
        user = db.session.get(User, user_id)
        if not user:
            return jsonify({'error': 'Пользователь не найден'}), 404
        
        # Нельзя снять права администратора с самого себя
        if user.id == session['user_id']:
            flash('Нельзя изменить права администратора у самого себя', 'error')
            return redirect(url_for('admin_panel'))
        
        user.adm = not user.adm  # Переключаем статус
        db.session.commit()
        
        status = 'назначены' if user.adm else 'сняты'
        flash(f'Права администратора {status} для пользователя {user.username}', 'success')
        return redirect(url_for('admin_panel'))
        
    except Exception as e:
        db.session.rollback()
        flash(f'Ошибка: {str(e)}', 'error')
        return redirect(url_for('admin_panel'))


@app.route('/api/admin/delete-user/<int:user_id>', methods=['POST'])
@login_required
@admin_required
def delete_user(user_id):
    try:
        user = db.session.get(User, user_id)
        if not user:
            flash('Пользователь не найден', 'error')
            return redirect(url_for('admin_panel'))
        
        # Нельзя удалить самого себя
        if user.id == session['user_id']:
            flash('Нельзя удалить самого себя', 'error')
            return redirect(url_for('admin_panel'))
        
        db.session.delete(user)
        db.session.commit()
        
        flash(f'Пользователь {user.username} успешно удален', 'success')
        return redirect(url_for('admin_panel'))
        
    except Exception as e:
        db.session.rollback()
        flash(f'Ошибка: {str(e)}', 'error')
        return redirect(url_for('admin_panel'))

@app.route('/api/admin/add-exercise', methods=['POST'])
@login_required
@admin_required
def add_exercise():
    try:
        # Получаем текстовые данные
        title = request.form.get('title')
        description = request.form.get('description')
        category = request.form.get('category')
        difficulty = request.form.get('difficulty')
        duration_minutes = request.form.get('duration_minutes')
        calories = request.form.get('calories')
        detailed_description = request.form.get('detailed_description')
        sex = request.form.get('sex')
        
        # Валидация обязательных полей
        if not all([title, category, duration_minutes, calories, sex]):
            flash('Пожалуйста, заполните все обязательные поля', 'error')
            return redirect(url_for('admin_panel'))
        # Обработка загрузки изображения
        image_url = None
        if 'image_file' in request.files:
            image_file = request.files['image_file']
            if image_file and image_file.filename and allowed_file(image_file.filename, app.config['ALLOWED_EXTENSIONS_IMAGES']):
                # Генерируем уникальное имя файла
                filename = secure_filename(image_file.filename)
                name, ext = os.path.splitext(filename)
                unique_filename = f"{name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}{ext}"
                
                # Сохраняем файл
                image_path = os.path.join(app.config['UPLOAD_FOLDER_IMAGES'], unique_filename)
                image_file.save(image_path)
                image_url = f"/static/images/workout/{unique_filename}"
            elif image_file and image_file.filename:
                flash('Неподдерживаемый формат изображения. Используйте: PNG, JPG, JPEG, GIF, WEBP', 'error')
                return redirect(url_for('admin_panel'))
        
        # Если изображение не загружено, проверяем URL
        if not image_url:
            image_url = request.form.get('image_url')
            if not image_url:
                flash('Пожалуйста, загрузите изображение или укажите URL', 'error')
                return redirect(url_for('admin_panel'))
        
        # Обработка загрузки видео
        video_url = None
        if 'video_file' in request.files:
            video_file = request.files['video_file']
            if video_file and video_file.filename and allowed_file(video_file.filename, app.config['ALLOWED_EXTENSIONS_VIDEOS']):
                # Генерируем уникальное имя файла
                filename = secure_filename(video_file.filename)
                name, ext = os.path.splitext(filename)
                unique_filename = f"{name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}{ext}"
                
                # Сохраняем файл
                video_path = os.path.join(app.config['UPLOAD_FOLDER_VIDEOS'], unique_filename)
                video_file.save(video_path)
                video_url = f"/static/videos/{unique_filename}"
            elif video_file and video_file.filename:
                flash('Неподдерживаемый формат видео. Используйте: MP4, WEBM, OGG, MOV', 'error')
                return redirect(url_for('admin_panel'))
        
        # Если видео не загружено, берем из URL
        if not video_url:
            video_url = request.form.get('video_url')
        
        # Создаем новое упражнение
        new_exercise = Exercise(
            title=title,
            description=description,
            category=category,
            difficulty=difficulty,
            duration_minutes=int(duration_minutes),
            calories=int(calories),
            image_url=image_url,
            video_url=video_url,
            detailed_description=detailed_description,
            sex=sex
        )
        
        db.session.add(new_exercise)
        db.session.commit()
        
        flash('Упражнение успешно добавлено!', 'success')
        return redirect(url_for('admin_panel'))
        
    except Exception as e:
        db.session.rollback()
        flash(f'Ошибка: {str(e)}', 'error')
        return redirect(url_for('admin_panel'))

# API для удаления упражнения (только для админа)
@app.route('/api/admin/delete-exercise/<int:exercise_id>', methods=['POST'])
@login_required
@admin_required
def delete_exercise(exercise_id):
    try:
        exercise = db.session.get(Exercise, exercise_id)
        if not exercise:
            flash('Упражнение не найдено', 'error')
            return redirect(url_for('admin_panel'))
        
        # Удаляем файл изображения если он существует и был загружен на сервер
        if exercise.image_url and '/static/images/workout/' in exercise.image_url:
            image_path = exercise.image_url.replace('/static/', '../frontend/static/')
            if os.path.exists(image_path):
                os.remove(image_path)
        
        # Удаляем файл видео если он существует и был загружен на сервер
        if exercise.video_url and '/static/videos/workout/' in exercise.video_url:
            video_path = exercise.video_url.replace('/static/', '../frontend/static/')
            if os.path.exists(video_path):
                os.remove(video_path)
        
        db.session.delete(exercise)
        db.session.commit()
        
        flash(f'Упражнение {exercise.title} успешно удалено', 'success')
        return redirect(url_for('admin_panel'))
        
    except Exception as e:
        db.session.rollback()
        flash(f'Ошибка: {str(e)}', 'error')
        return redirect(url_for('admin_panel'))

####################    

@app.route('/api/login', methods=['POST'])
def login():
    email = request.form['email']
    password = request.form['password']
    remember = request.form.get('remember')
    
    user = User.query.filter_by(email=email).first()
    if user and user.check_password(password):
        session['user_id'] = user.id
        session['username'] = user.username
        session['first_login'] = user.first_login
        session['is_admin'] = user.adm
        if remember:
            session.permanent = True
            app.permanent_session_lifetime = 30 * 24 * 60 * 60
        return redirect(url_for('main'))
    else:
        flash('Неверный email или пароль', 'error')
        return redirect(url_for('auth'))

@app.route('/api/register', methods=['POST'])
def register():
    username = request.form['username']
    email = request.form['email']
    password = request.form['password']
    passcheck = request.form['passcheck']
    
    if User.query.filter_by(email=email).first():
        flash('Пользователь уже существует', 'error')
        return redirect(url_for('auth'))
    
    if (password!=passcheck):
        flash('Пароли не совпадают', 'error')
        return redirect(url_for('auth'))

    new_user = User(username=username, email=email)
    new_user.set_password(password)
    
    db.session.add(new_user)
    db.session.commit()
    log_user_db_action(new_user, "INSERT (register)", details="new user created via registration")
    
    flash('Пользователь зарегистрирован!','success')
    return redirect(url_for('auth'))

@app.route('/api/logout', methods=['POST','GET'])
def logout():

    session.clear()
    flash('Вы вышли из системы', 'info')
    return redirect(url_for('auth'))


@app.route('/api/intro', methods=['POST'])
def introduction():
    try:
        user_id = session.get('user_id')

        if not user_id:
            flash('Пользователь не авторизован', 'error')
            return redirect(url_for('auth'))

        user = db.session.get(User, user_id)

        if not user:
            flash('Пользователь не найден', 'error')
            return redirect(url_for('auth'))

        # Получаем данные
        gender = request.form.get('gender')
        weight = request.form.get('weight')
        height = request.form.get('height')
        age = request.form.get('age')
        fitness_level = request.form.get('fitness_level')
        goal = request.form.get('goal')

        # ЛОГ (очень важно для отладки)
        app.logger.info(f"RAW GOAL: {goal}")

        # Преобразование типов
        try:
            weight = float(weight) if weight else None
            height = float(height) if height else None
            age = int(age) if age else None
        except ValueError:
            flash('Пожалуйста, введите корректные числовые значения', 'error')
            return redirect(url_for('main'))

        # Нормализация goal
        normalized_goal = normalize_goal(goal)

        app.logger.info(f"NORMALIZED GOAL: {normalized_goal}")

        # ❗ ВАЖНО: проверка
        if not normalized_goal:
            flash('Некорректная цель', 'error')
            return redirect(url_for('main'))

        # Обновление пользователя
        user.gender = gender
        user.weight = weight
        user.height = height
        user.age = age
        user.fitness_level = fitness_level
        user.goal = normalized_goal
        user.first_login = False

        db.session.commit()

        log_user_db_action(user, "UPDATE (intro)", details="intro form submission")

        session['first_login'] = False



        flash('Профиль успешно обновлен!', 'success')

        return redirect(url_for('my_training'))
        
    except Exception as e:
        db.session.rollback()
        flash(f'Ошибка: {str(e)}', 'error')
        return redirect(url_for('main'))




@app.route('/api/update-profile', methods=['POST'])
@login_required
def update_profile():
    try:
        user_id = session.get('user_id')
        user = db.session.get(User, user_id)

        if not user:
            flash('Пользователь не найден', 'error')
            return redirect(url_for('profile'))

        # Получаем данные из формы
        username = request.form.get('username')
        email = request.form.get('email')
        gender = request.form.get('gender')
        weight = request.form.get('weight')
        height = request.form.get('height')
        age = request.form.get('age')
        fitness_level = request.form.get('fitness_level')
        goal = request.form.get('goal')  

        app.logger.info(f"RAW GOAL (update): {goal}")

        # Проверяем уникальность email
        if email and email != user.email:
            existing_user = User.query.filter_by(email=email).first()
            if existing_user:
                flash('Пользователь с таким email уже существует', 'error')
                return redirect(url_for('profile'))

        # Проверяем уникальность username
        if username and username != user.username:
            existing_user = User.query.filter_by(username=username).first()
            if existing_user:
                flash('Пользователь с таким именем уже существует', 'error')
                return redirect(url_for('profile'))

        # Преобразование типов данных
        try:
            weight = float(weight) if weight else None
            height = float(height) if height else None
            age = int(age) if age else None
        except ValueError:
            flash('Пожалуйста, введите корректные числовые значения', 'error')
            return redirect(url_for('profile'))

        # Нормализация goal
        normalized_goal = normalize_goal(goal)
        app.logger.info(f"NORMALIZED GOAL (update): {normalized_goal}")

        # ❗ если goal передан — обновляем
        if goal:
            if not normalized_goal:
                flash('Некорректная цель', 'error')
                return redirect(url_for('profile'))
            user.goal = normalized_goal

        # Обновляем данные
        if username:
            user.username = username
            session['username'] = username
        if email:
            user.email = email

        user.gender = gender
        user.weight = weight
        user.height = height
        user.age = age
        user.fitness_level = fitness_level

        db.session.commit()

        log_user_db_action(user, "UPDATE (profile)", details="user profile edit")

        flash('Профиль успешно обновлен!', 'success')
        return redirect(url_for('profile'))

    except Exception as e:
        db.session.rollback()
        flash(f'Произошла ошибка: {str(e)}', 'error')
        return redirect(url_for('profile'))
    

@app.route('/api/change-password', methods=['POST'])
@login_required
def change_password():
    try:
        user_id = session.get('user_id')
        user = db.session.get(User, user_id)
        
        old_password = request.form.get('old_password')
        new_password = request.form.get('new_password')
        confirm_password = request.form.get('confirm_password')
        
        # Проверяем старый пароль
        if not user.check_password(old_password):
            flash('Неверный текущий пароль', 'error')
            return redirect(url_for('profile'))
        
        # Проверяем совпадение нового пароля
        if new_password != confirm_password:
            flash('Новые пароли не совпадают', 'error')
            return redirect(url_for('profile'))
        
        # Проверяем длину пароля
        if len(new_password) < 6:
            flash('Новый пароль должен содержать минимум 6 символов', 'error')
            return redirect(url_for('profile'))
        
        # Обновляем пароль
        user.set_password(new_password)
        db.session.commit()
        
        flash('Пароль успешно изменен!', 'success')
        return redirect(url_for('profile'))
        
    except Exception as e:
        db.session.rollback()
        flash(f'Произошла ошибка: {str(e)}', 'error')
        return redirect(url_for('profile'))
    

@app.route('/api/save-statistics', methods=['POST'])
@login_required
def save_statistics():
    try:
        data = request.get_json()
        
        user_id = session.get('user_id')
        exercise_id = data.get('exercise_id')
        duration_seconds = data.get('duration_seconds')
        calories_burned = data.get('calories_burned')
        date = data.get('date')  # Может быть None для обратной совместимости
        
        # Валидация
        if not all([exercise_id, duration_seconds]):
            return jsonify({'success': False, 'error': 'Недостаточно данных'}), 400
        
        # Создаем запись статистики
        stats = Statistics(
            user_id=user_id,
            exercise_id=exercise_id,
            duration_seconds=duration_seconds,
            calories_burned=calories_burned,
            completed=True,
            completed_at=datetime.now(UTC)
        )
        
        db.session.add(stats)
        db.session.commit()
        
        return jsonify({'success': True, 'message': 'Статистика сохранена'})
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500
    

@app.route('/api/favorite/toggle', methods=['POST'])
@login_required
def toggle_favorite():
    """Добавить или удалить упражнение из избранного"""
    try:
        data = request.get_json()
        exercise_id = data.get('exercise_id')
        
        if not exercise_id:
            return jsonify({'success': False, 'error': 'ID упражнения не указан'}), 400
        
        user_id = session.get('user_id')
        
        # Проверяем, есть ли уже в избранном
        favorite = FavoriteExercise.query.filter_by(
            user_id=user_id, 
            exercise_id=exercise_id
        ).first()
        
        if favorite:
            # Удаляем из избранного
            db.session.delete(favorite)
            db.session.commit()
            return jsonify({
                'success': True, 
                'action': 'removed',
                'message': 'Упражнение удалено из избранного'
            })
        else:
            # Добавляем в избранное
            new_favorite = FavoriteExercise(
                user_id=user_id,
                exercise_id=exercise_id
            )
            db.session.add(new_favorite)
            db.session.commit()
            return jsonify({
                'success': True, 
                'action': 'added',
                'message': 'Упражнение добавлено в избранное'
            })
            
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/favorites', methods=['GET'])
@login_required
def get_favorites():
    """Получить список избранных упражнений пользователя"""
    try:
        user_id = session.get('user_id')
        favorites = FavoriteExercise.query.filter_by(user_id=user_id).all()
        
        favorite_ids = [fav.exercise_id for fav in favorites]
        
        return jsonify({
            'success': True,
            'favorites': favorite_ids
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/favorite/status/<int:exercise_id>', methods=['GET'])
@login_required
def get_favorite_status(exercise_id):
    """Проверить, добавлено ли упражнение в избранное"""
    try:
        user_id = session.get('user_id')
        favorite = FavoriteExercise.query.filter_by(
            user_id=user_id, 
            exercise_id=exercise_id
        ).first()
        
        return jsonify({
            'success': True,
            'is_favorite': favorite is not None
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


def ensure_goal_column():
    """Добавляет колонку goal в таблицу User при необходимости."""
    inspector = inspect(db.engine)
    table_name = getattr(User, '__tablename__', User.__name__.lower())
    if table_name not in inspector.get_table_names():
        return

    column_names = [column['name'] for column in inspector.get_columns(table_name)]
    if 'goal' in column_names:
        return

    db.session.execute(f'ALTER TABLE {table_name} ADD COLUMN goal TEXT')
    db.session.commit()


with app.app_context():
    ensure_goal_column()


if __name__ == '__main__':
    app.run(host="0.0.0.0", port=80,debug=True)
