from functools import wraps
import logging
import json
import os
from datetime import datetime, timedelta, timezone
from datetime import time
from zoneinfo import ZoneInfo
from flask import Flask, flash, jsonify, redirect, render_template, request, url_for, session
from flask_sqlalchemy import SQLAlchemy
from flask_session import Session
from sqlalchemy import inspect, select
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from datetime import datetime, timedelta
import os
from chat import get_program
import json

# Google Calendar imports
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

from chat import get_program
from connect import GigaChatAuth
from chat import GigaChatClient
MOSCOW_TZ = ZoneInfo("Europe/Moscow")
app = Flask(__name__, template_folder='../frontend', static_folder='../frontend/static')

# ─────────────────────────── Логгирование ───────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s',
)
app.logger.setLevel(logging.INFO)

# ─────────────────────────── Конфигурация ───────────────────────────
_BACKEND_DIR = os.path.dirname(__file__)
_PROJECT_ROOT = os.path.dirname(_BACKEND_DIR)
os.makedirs(app.instance_path, exist_ok=True)

_DB_PATH = os.path.join(app.instance_path, "fitness.db")

app.config['SQLALCHEMY_DATABASE_URI'] = f"sqlite:///{_DB_PATH}"
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# ✅ Фиксированный SECRET_KEY
app.secret_key = os.environ.get('SECRET_KEY', 'fithub-secret-key-2024-change-in-prod')

# ✅ Flask-Session (filesystem)
app.config['SESSION_TYPE'] = 'filesystem'
app.config['SESSION_FILE_DIR'] = os.path.join(_PROJECT_ROOT, 'flask_session')
app.config['SESSION_PERMANENT'] = True
app.config['SESSION_USE_SIGNER'] = True
app.config['SESSION_KEY_PREFIX'] = 'fithub_'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7)
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = False
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_NAME'] = 'fithub_session'

os.makedirs(app.config['SESSION_FILE_DIR'], exist_ok=True)
Session(app)

# Загрузка файлов
app.config['UPLOAD_FOLDER_IMAGES'] = '../frontend/static/images/workout'
app.config['UPLOAD_FOLDER_VIDEOS'] = '../frontend/static/videos'
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024
app.config['ALLOWED_EXTENSIONS_IMAGES'] = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
app.config['ALLOWED_EXTENSIONS_VIDEOS'] = {'mp4', 'webm', 'ogg', 'mov'}

# Google OAuth
os.environ.setdefault('OAUTHLIB_INSECURE_TRANSPORT', '1')
GOOGLE_CREDENTIALS_FILE = os.path.join(_BACKEND_DIR, 'credentials.json')
GOOGLE_SCOPES = [
    'https://www.googleapis.com/auth/calendar.readonly',
    'https://www.googleapis.com/auth/calendar.events',
]
GOOGLE_REDIRECT_URI = 'http://localhost:80/api/calendar/callback'

os.makedirs(app.config['UPLOAD_FOLDER_IMAGES'], exist_ok=True)
os.makedirs(app.config['UPLOAD_FOLDER_VIDEOS'], exist_ok=True)

# ─────────────────────────── БД ───────────────────────────
db = SQLAlchemy(app)

# ─────────────────────────── Вспомогательные функции ───────────────────────────

def allowed_file(filename, allowed_extensions):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in allowed_extensions


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
        action, user.username, user.id,
        user.goal, user.weight, user.height, user.age, extra,
    )

# ─────────────────────────── Google Calendar helpers ───────────────────────────

def _create_google_flow():
    """Создаёт OAuth2 Flow из credentials.json."""
    flow = Flow.from_client_secrets_file(
        GOOGLE_CREDENTIALS_FILE,
        scopes=GOOGLE_SCOPES,
        redirect_uri=GOOGLE_REDIRECT_URI,
    )
    return flow


def _creds_from_db(token_record) -> Credentials:
    """Восстанавливает Credentials из записи БД."""
    creds = Credentials(
        token=token_record.token,
        refresh_token=token_record.refresh_token,
        token_uri=token_record.token_uri,
        client_id=token_record.client_id,
        client_secret=token_record.client_secret,
        scopes=json.loads(token_record.scopes) if token_record.scopes else GOOGLE_SCOPES,
    )
    # ВАЖНО: в SQLite expiry хранится naive. Оставляем naive.
    creds.expiry = token_record.expiry  # может быть None
    return creds


def _refresh_creds_if_needed(creds: Credentials) -> Credentials:
    """
    Делаем expiry НАИВНЫМ UTC, чтобы google-auth не падал на сравнении
    naive vs aware.
    """
    try:
        # Нормализуем expiry ДО проверки creds.expired
        if creds.expiry and creds.expiry.tzinfo is not None:
            creds.expiry = creds.expiry.astimezone(timezone.utc).replace(tzinfo=None)

        if creds.expired and creds.refresh_token:
            creds.refresh(Request())

            # После refresh expiry часто становится aware (UTC) — снова нормализуем
            if creds.expiry and creds.expiry.tzinfo is not None:
                creds.expiry = creds.expiry.astimezone(timezone.utc).replace(tzinfo=None)

    except Exception as e:
        app.logger.warning(f"⚠️ Ошибка обновления токена (не критично): {e}")
    return creds


def _save_creds_to_db(token_record, creds: Credentials):
    """Обновляет токены в записи БД (без commit)."""
    token_record.token = creds.token
    token_record.refresh_token = creds.refresh_token
    token_record.token_uri = creds.token_uri
    token_record.client_id = creds.client_id
    token_record.client_secret = creds.client_secret
    token_record.scopes = json.dumps(list(creds.scopes or GOOGLE_SCOPES))
    if creds.expiry:
        # ✅ Убираем timezone перед сохранением в БД (SQLite не хранит timezone)
        token_record.expiry = creds.expiry.replace(tzinfo=None)


def _get_calendar_service(creds: Credentials):
    return build('calendar', 'v3', credentials=creds)


def _fetch_events(service, year: int, month: int) -> list:
    from calendar import monthrange
    time_min = datetime(year, month, 1, tzinfo=timezone.utc).isoformat()
    last_day = monthrange(year, month)[1]
    time_max = datetime(year, month, last_day, 23, 59, 59, tzinfo=timezone.utc).isoformat()

    result = service.events().list(
        calendarId='primary',
        timeMin=time_min,
        timeMax=time_max,
        singleEvents=True,
        orderBy='startTime',
        maxResults=250,
    ).execute()

    events = []
    for ev in result.get('items', []):
        start = ev.get('start', {})
        end = ev.get('end', {})
        events.append({
            'id': ev.get('id'),
            'title': ev.get('summary', 'Без названия'),
            'description': ev.get('description', ''),
            'location': ev.get('location', ''),
            'start': start.get('dateTime') or start.get('date'),
            'end': end.get('dateTime') or end.get('date'),
            'all_day': 'dateTime' not in start,
            'color_id': ev.get('colorId', ''),
            'html_link': ev.get('htmlLink', ''),
        })
    return events


def _add_calendar_event(service, title: str, date_iso: str,
                        duration_minutes: int, description: str) -> dict:
    start_dt = datetime.fromisoformat(date_iso)

    # Если пришло без tzinfo — считаем, что это время по Москве
    if start_dt.tzinfo is None:
        start_dt = start_dt.replace(tzinfo=MOSCOW_TZ)

    end_dt = start_dt + timedelta(minutes=duration_minutes)

    body = {
        'summary': f'🏋️ {title}',
        'description': description,
        'start': {'dateTime': start_dt.isoformat(), 'timeZone': 'Europe/Moscow'},
        'end': {'dateTime': end_dt.isoformat(), 'timeZone': 'Europe/Moscow'},
        'colorId': '10',
        'reminders': {
            'useDefault': False,
            'overrides': [{'method': 'popup', 'minutes': 30}],
        },
    }

    created = service.events().insert(calendarId='primary', body=body).execute()
    return {
        'id': created.get('id'),
        'html_link': created.get('htmlLink'),
        'title': created.get('summary'),
    }
# ─────────────────────────── Модели ───────────────────────────

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
    adm = db.Column(db.Boolean, default=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def is_admin(self):
        return self.adm is True


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


class GoogleCalendarToken(db.Model):
    __tablename__ = 'google_calendar_tokens'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, unique=True)
    token = db.Column(db.Text, nullable=True)
    refresh_token = db.Column(db.Text, nullable=True)
    token_uri = db.Column(db.String(200), nullable=True)
    client_id = db.Column(db.String(200), nullable=True)
    client_secret = db.Column(db.String(200), nullable=True)
    scopes = db.Column(db.Text, nullable=True)
    expiry = db.Column(db.DateTime, nullable=True)

    user = db.relationship('User', backref=db.backref('google_token', uselist=False))


class OAuthState(db.Model):
    __tablename__ = 'oauth_states'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    state = db.Column(db.String(200), unique=True, nullable=False)
    code_verifier = db.Column(db.String(200), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    @staticmethod
    def cleanup_old():
        try:
            timeout = datetime.utcnow() - timedelta(minutes=10)
            OAuthState.query.filter(OAuthState.created_at < timeout).delete()
            db.session.commit()
        except Exception as e:
            app.logger.warning(f"cleanup_old error: {e}")
            db.session.rollback()


# ✅ НОВАЯ МОДЕЛЬ - Отметки о выполненных тренировках
class WorkoutCompletion(db.Model):
    __tablename__ = 'workout_completions'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    day_number = db.Column(db.Integer, nullable=False)
    completion_date = db.Column(db.Date, nullable=False)  # дата выполнения
    completed_at = db.Column(db.DateTime, default=datetime.utcnow)  # когда отметил

    user = db.relationship('User', backref=db.backref('workout_completions', cascade='all, delete-orphan'))

    __table_args__ = (db.UniqueConstraint('user_id', 'day_number', 'completion_date', name='unique_workout_completion'),)




# Модель статистики
class Statistics(db.Model):
    __tablename__ = 'statistics'    
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    exercise_id = db.Column(db.Integer, db.ForeignKey('exercises.id'), nullable=False)
    
    duration_seconds = db.Column(db.Integer, nullable=False)  
    calories_burned = db.Column(db.Integer, nullable=False)  
    
    completed = db.Column(db.Boolean, default=True) 

    completed_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    user = db.relationship('User', backref='statistics')
    exercise = db.relationship('Exercise', backref='statistics')
    
    def __repr__(self):
        return f'<Statistics {self.user_id} - {self.exercise_id}>'
    

class FavoriteExercise(db.Model):
    __tablename__ = 'favorite_exercises'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    exercise_id = db.Column(db.Integer, db.ForeignKey('exercises.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Связи
    user = db.relationship('User', backref='favorites')
    exercise = db.relationship('Exercise', backref='favorited_by')
    
    __table_args__ = (db.UniqueConstraint('user_id', 'exercise_id', name='unique_user_exercise_favorite'),)
    
    def __repr__(self):
        return f'<FavoriteExercise user={self.user_id} exercise={self.exercise_id}>'


def parse_program(program_dict: dict):
    full_program = {}
    for day, exercise_ids in program_dict.items():
        full_exercises = []
        for exercise_id in exercise_ids:
            exercise = db.session.get(Exercise, exercise_id)
            if exercise:
                full_exercises.append({
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
                    'sex': exercise.sex,
                })
            else:
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
                    'sex': 'unisex',
                })
        full_program[day] = full_exercises
    return full_program


def ensure_user_program_column() -> None:
    try:
        inspector = inspect(db.engine)
        columns = {col["name"] for col in inspector.get_columns("user")}
        if "program" not in columns:
            with db.engine.begin() as conn:
                conn.exec_driver_sql('ALTER TABLE "user" ADD COLUMN program TEXT')
    except Exception as e:
        app.logger.warning("Не удалось проверить/обновить схему БД для program: %s", e)


def ensure_goal_column():
    inspector = inspect(db.engine)
    table_name = getattr(User, '__tablename__', User.__name__.lower())
    if table_name not in inspector.get_table_names():
        return
    column_names = [c['name'] for c in inspector.get_columns(table_name)]
    if 'goal' not in column_names:
        with db.engine.begin() as conn:
            conn.exec_driver_sql(f'ALTER TABLE "{table_name}" ADD COLUMN goal TEXT')


def add_program_to_calendar(user, program_json):
    """Добавляет программу в Google Calendar"""
    token_record = GoogleCalendarToken.query.filter_by(user_id=user.id).first()
    if not token_record:
        app.logger.info("📅 Календарь не подключен — пропускаем")
        return

    try:
        creds = _creds_from_db(token_record)
        creds = _refresh_creds_if_needed(creds)
        service = _get_calendar_service(creds)

        # Старт программы = дата создания пользователя (как у тебя в календаре-виджете)
        program_start_date = user.created_at.date() if user.created_at else datetime.utcnow().date()

        for day_key, exercise_ids in program_json.items():
            day_str = str(day_key).replace("_", " ").strip()
            digits = "".join(ch for ch in day_str if ch.isdigit())
            if not digits:
                continue

            day_number = int(digits)
            workout_date = program_start_date + timedelta(days=day_number - 1)  # <-- это date

            exercises = Exercise.query.filter(Exercise.id.in_(exercise_ids)).all()
            if not exercises:
                continue

            total_duration = sum(ex.duration_minutes for ex in exercises if ex.duration_minutes) or 60
            description = "\n".join([f"• {ex.title}" for ex in exercises])

            # ВАЖНО: делаем datetime (10:00 по Москве)
            start_dt = datetime.combine(workout_date, time(10, 0), tzinfo=MOSCOW_TZ)

            _add_calendar_event(
                service,
                title=f"Тренировка (День {day_number})",
                date_iso=start_dt.isoformat(),
                duration_minutes=total_duration,
                description=description
            )

        _save_creds_to_db(token_record, creds)
        db.session.commit()
        app.logger.info("✅ Программа добавлена в Google Calendar")

    except Exception as e:
        app.logger.warning(f"⚠️ Ошибка добавления в календарь: {e}")

def add_completed_workout_to_calendar(user, day_number, completion_date, exercises):
    token_record = GoogleCalendarToken.query.filter_by(user_id=user.id).first()
    if not token_record:
        app.logger.info("📅 Календарь не подключен — тренировка не добавлена")
        return

    try:
        creds = _creds_from_db(token_record)
        creds = _refresh_creds_if_needed(creds)
        service = _get_calendar_service(creds)

        total_duration = sum(ex.get('duration_minutes', 0) for ex in exercises) or 60
        description = "\n".join([f"✅ {ex.get('title', 'Упражнение')}" for ex in exercises])

        # date -> datetime 20:00 по Москве
        start_dt = datetime.combine(completion_date, time(20, 0)).replace(tzinfo=MOSCOW_TZ)

        _add_calendar_event(
            service,
            title=f"✅ Тренировка выполнена (День {day_number})",
            date_iso=start_dt.isoformat(),
            duration_minutes=total_duration,
            description=description
        )

        _save_creds_to_db(token_record, creds)
        db.session.commit()

        app.logger.info(f"✅ Выполненная тренировка (День {day_number}) добавлена в Google Calendar")

    except Exception as e:
        app.logger.warning(f"⚠️ Ошибка добавления выполненной тренировки: {e}")
# ─────────────────────────── Декораторы ───────────────────────────

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

# ─────────────────────────── Before request ───────────────────────────

_schema_checked = False


@app.before_request
def _ensure_schema_once():
    global _schema_checked
    if _schema_checked:
        return
    ensure_user_program_column()
    _schema_checked = True

# ═══════════════════════════════════════════════════════════════════
#                         МАРШРУТЫ СТРАНИЦ
# ═══════════════════════════════════════════════════════════════════

@app.route('/')
def welcome():
    if 'user_id' in session:
        return redirect(url_for('main'))
    return redirect(url_for('auth'))


@app.route('/auth')
def auth():
    if 'user_id' in session:
        return redirect(url_for('main'))
    return render_template("reg_log.html")


@app.route('/main')
@login_required
def main():
    user = db.session.get(User, session['user_id'])
    is_admin = user.is_admin() if user else False

    current_exercises = []
    if user and user.program:
        program_dict = json.loads(user.program) if isinstance(user.program, str) else user.program
        day1_ids = program_dict.get("Day 1", [])
        if day1_ids:
            exercises = Exercise.query.filter(Exercise.id.in_(day1_ids)).all()
            for ex in exercises:
                current_exercises.append({
                    'id': ex.id,
                    'title': ex.title,
                    'description': ex.description,
                    'category': ex.category,
                    'difficulty': ex.difficulty,
                    'duration_minutes': ex.duration_minutes,
                    'calories': ex.calories,
                    'image_url': ex.image_url,
                    'video_url': ex.video_url,
                    'detailed_description': ex.detailed_description,
                    'sex': ex.sex,
                })

    if user.first_login == 1:
        first_login = True
        user.first_login = False
        db.session.commit()
        db.session.close()
    else:
        first_login = False

    # Получаем сегодняшнюю дату
    today = datetime.utcnow().date()
    today_start = datetime(today.year, today.month, today.day)
    
    # Статистика за сегодня
    today_stats = Statistics.query.filter(
        Statistics.user_id == user.id,
        Statistics.completed_at >= today_start
    ).all()
    
    # Общая статистика за все время
    all_stats = Statistics.query.filter_by(user_id=user.id).all()
    
    # Рассчитываем показатели
    total_calories_today = sum(stat.calories_burned for stat in today_stats)
    total_duration_today = sum(stat.duration_seconds for stat in today_stats) // 60  # в минутах
    total_exercises_today = len(today_stats)
    
    total_calories_all = sum(stat.calories_burned for stat in all_stats)
    total_duration_all = sum(stat.duration_seconds for stat in all_stats) // 60  # в минутах
    total_exercises_all = len(all_stats)
    
    # Прогресс программы (процент выполнения)
    program_progress = 0
    if user.program:
        program_dict = json.loads(user.program) if isinstance(user.program, str) else user.program
        total_planned_exercises = 0
        for day, exercises_ids in program_dict.items():
            total_planned_exercises += len(exercises_ids)
        
        if total_planned_exercises > 0:
            program_progress = round((total_exercises_all / total_planned_exercises) * 100)
            if program_progress > 100:
                program_progress = 100
    
    # Сравнение с предыдущим днем
    yesterday_start = today_start - timedelta(days=1)
    yesterday_stats = Statistics.query.filter(
        Statistics.user_id == user.id,
        Statistics.completed_at >= yesterday_start,
        Statistics.completed_at < today_start
    ).all()
    
    yesterday_calories = sum(stat.calories_burned for stat in yesterday_stats)
    yesterday_duration = sum(stat.duration_seconds for stat in yesterday_stats) // 60
    
    # Процент изменения
    progress_percent_change = 0
    if yesterday_calories > 0:
        progress_percent_change = round(((total_calories_today - yesterday_calories) / yesterday_calories) * 100)



        
    return render_template('index.html', 
                         username=session.get('username'), 
                         first_login=session.get('first_login'),
                         is_admin=is_admin,
                         current_exercises=current_exercises,
                         
                         total_calories_today=total_calories_today,
                         total_duration_today=total_duration_today,
                         total_exercises_today=total_exercises_today,
                        
                         total_calories_all=total_calories_all,
                         total_duration_all=total_duration_all,
                         total_exercises_all=total_exercises_all,
                         
                         program_progress=program_progress,
                         progress_percent_change=progress_percent_change)


@app.route('/admin')
@login_required
@admin_required
def admin_panel():
    users = User.query.all()
    exercises = Exercise.query.all()
    return render_template(
        'admin.html',
        username=session.get('username'),
        users=users,
        exercises=exercises,
    )


@app.route('/programs')
@login_required
def workouts():
    user = db.session.get(User, session['user_id'])
    if not user:
        flash('Пользователь не найден', 'error')
        return redirect(url_for('workouts'))

    exercises_list = []
    for ex in Exercise.query.all():
        if ex.sex == user.gender:
            exercises_list.append({
                'id': ex.id,
                'title': ex.title,
                'description': ex.description,
                'category': ex.category,
                'difficulty': ex.difficulty,
                'duration_minutes': ex.duration_minutes,
                'calories': ex.calories,
                'image_url': ex.image_url,
                'video_url': ex.video_url,
                'detailed_description': ex.detailed_description,
            })

    return render_template('programs.html', username=session.get('username'), exercises=exercises_list)


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
            all_exercise_ids: set = set()
            day_items: list = []

            for day_key, exercise_ids in program.items():
                day_str = str(day_key).strip()
                ids: list = []
                if isinstance(exercise_ids, list):
                    for value in exercise_ids:
                        try:
                            ids.append(int(value))
                        except Exception:
                            continue
                if ids:
                    all_exercise_ids.update(ids)
                day_items.append((day_str, ids))

            title_map: dict = {}
            if all_exercise_ids:
                exercises = Exercise.query.filter(Exercise.id.in_(list(all_exercise_ids))).all()
                title_map = {ex.id: ex.title for ex in exercises}

            def _day_number(day_value: str):
                digits = "".join(ch for ch in day_value.replace("_", " ").strip() if ch.isdigit())
                try:
                    return int(digits) if digits else None
                except Exception:
                    return None

            def _day_label(day_value: str) -> str:
                normalized = day_value.replace("_", " ").strip()
                if normalized.lower().startswith("day"):
                    digits = "".join(ch for ch in normalized if ch.isdigit())
                    return f"День {digits}" if digits else normalized
                return normalized.replace("Day", "День").replace("day", "День", 1)

            rendered_program = []
            fallback = 1
            for day_str, ids in day_items:
                num = _day_number(day_str) or fallback
                fallback += 1
                rendered_program.append({
                    "number": num,
                    "day": _day_label(day_str),
                    "exercises": [title_map.get(ex_id, f"#{ex_id}") for ex_id in ids],
                })

    return render_template('my_training.html', username=session.get('username'), program=rendered_program)


@app.route('/my-training/day/<int:day_number>')
@login_required
def my_training_day(day_number: int):
    ensure_user_program_column()
    user = db.session.get(User, session['user_id'])

    if not user or not user.program:
        flash('Программа тренировок не найдена. Сначала сгенерируй тренировку.', 'warning')
        return redirect(url_for('my_training'))

    try:
        program = json.loads(user.program)
    except Exception:
        flash('Не удалось прочитать программу тренировок.', 'error')
        return redirect(url_for('my_training'))

    if not isinstance(program, dict):
        flash('Неверный формат программы тренировок.', 'error')
        return redirect(url_for('my_training'))

    selected_ids: list = []
    for day_key, exercise_ids in program.items():
        day_str = str(day_key).replace("_", " ").strip()
        digits = "".join(ch for ch in day_str if ch.isdigit())
        if digits and int(digits) == day_number and isinstance(exercise_ids, list):
            for value in exercise_ids:
                try:
                    selected_ids.append(int(value))
                except Exception:
                    continue
            break

    if not selected_ids:
        flash('Тренировка для этого дня не найдена.', 'warning')
        return redirect(url_for('my_training'))

    exercises = Exercise.query.filter(Exercise.id.in_(selected_ids)).all()
    exercise_map = {ex.id: ex for ex in exercises}
    ordered_exercises = [exercise_map[ex_id] for ex_id in selected_ids if ex_id in exercise_map]

    return render_template(
        'my_training_day.html',
        username=session.get('username'),
        day_label=f"День {day_number}",
        day_number=day_number,
        exercises=ordered_exercises,
    )
@app.route('/api/training/day-details/<int:day_number>')
@login_required
def generate_training():
    ensure_user_program_column()
    user = db.session.get(User, session['user_id'])
    if not user:
        flash('Пользователь не найден', 'error')
        return redirect(url_for('my_training'))

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

        user.program = json.dumps(program_json, ensure_ascii=False)
        db.session.commit()

        flash('Тренировка сгенерирована', 'success')
        return redirect(url_for('my_training'))
    except Exception as e:
        app.logger.exception("Ошибка генерации тренировки: %s", e)
        flash(f'Ошибка генерации: {e}', 'error')
        return redirect(url_for('my_training'))


@app.route('/api/training/day-details/<int:day_number>')
@login_required
def training_day_details(day_number: int):
    """Получить детали дня тренировки (длительность, калории)."""
    try:
        user = db.session.get(User, session['user_id'])
        if not user or not user.program:
            return jsonify({'success': False, 'error': 'Программа не найдена'}), 400

        try:
            program = json.loads(user.program) if isinstance(user.program, str) else user.program
        except Exception:
            return jsonify({'success': False, 'error': 'Ошибка парсинга программы'}), 400

        if not isinstance(program, dict):
            return jsonify({'success': False, 'error': 'Неверный формат программы'}), 400

        # Ищем день с этим номером
        selected_ids = []
        for day_key, exercise_ids in program.items():
            day_str = str(day_key).replace("_", " ").strip()
            digits = "".join(ch for ch in day_str if ch.isdigit())
            if digits and int(digits) == day_number and isinstance(exercise_ids, list):
                for value in exercise_ids:
                    try:
                        selected_ids.append(int(value))
                    except Exception:
                        continue
                break

        if not selected_ids:
            return jsonify({'success': True, 'total_duration': 0, 'total_calories': 0})

        # Получаем упражнения
        exercises = Exercise.query.filter(Exercise.id.in_(selected_ids)).all()

        total_duration = sum(ex.duration_minutes for ex in exercises if ex.duration_minutes)
        total_calories = sum(ex.calories for ex in exercises if ex.calories)

        return jsonify({
            'success': True,
            'total_duration': total_duration,
            'total_calories': total_calories,
            'exercise_count': len(exercises)
        })

    except Exception as e:
        app.logger.exception(f"❌ Ошибка получения деталей дня: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/profile')
@login_required
def profile():
    user = db.session.get(User, session['user_id'])
     # Получаем избранные упражнения пользователя
    favorites = FavoriteExercise.query.filter_by(user_id=user.id).all()
    favorite_exercises = [fav.exercise for fav in favorites]

     # Общая статистика за все время
    all_stats = Statistics.query.filter_by(user_id=user.id).all()
    
    total_workouts = len(all_stats)  # Всего тренировок
    total_calories = sum(stat.calories_burned for stat in all_stats)  # Всего калорий
    total_seconds = sum(stat.duration_seconds for stat in all_stats)  # Всего секунд
    total_minutes = total_seconds // 60  # Всего минут

    return render_template('profile.html', 
                         username=session.get('username'),
                         user=user,
                         favorite_exercises=favorite_exercises,
                         total_workouts=total_workouts,
                         total_calories=total_calories,
                         total_minutes=total_minutes)

#Маршруты сервера
@app.route('/api/admin/set-admin/<int:user_id>', methods=['POST'])
@login_required
def training_calendar_events():
    """
    Возвращает тренировки из программы пользователя в формате календаря.
    Объединяет с событиями из Google Calendar (если подключен).
    """
    try:
        user = db.session.get(User, session['user_id'])

        if not user or not user.program:
            return jsonify({
                'success': True,
                'events': [],
                'source': 'local',
                'count': 0
            })

        # Парсим программу
        try:
            program = json.loads(user.program) if isinstance(user.program, str) else user.program
        except Exception as e:
            app.logger.exception("Ошибка парсинга программы: %s", e)
            return jsonify({'error': 'Не удалось прочитать программу'}), 500

        if not isinstance(program, dict):
            return jsonify({
                'success': True,
                'events': [],
                'source': 'local',
                'count': 0
            })

        # Дата начала программы (от created_at пользователя)
        program_start_date = user.created_at.date() if user.created_at else datetime.utcnow().date()

        events = []

        # Формируем события для каждого дня программы
        for day_key, exercise_ids in program.items():
            # Извлекаем номер дня
            day_str = str(day_key).replace("_", " ").strip()
            digits = "".join(ch for ch in day_str if ch.isdigit())

            if not digits:
                continue

            try:
                day_number = int(digits)
            except ValueError:
                continue

            # Вычисляем дату этой тренировки
            workout_date = program_start_date + timedelta(days=day_number - 1)

            # Получаем список упражнений
            if not isinstance(exercise_ids, list) or not exercise_ids:
                continue

            exercises = Exercise.query.filter(Exercise.id.in_(exercise_ids)).all()

            if not exercises:
                continue

            # Формируем описание
            exercise_titles = [ex.title for ex in exercises if ex.title]
            total_duration = sum(ex.duration_minutes for ex in exercises if ex.duration_minutes) or 60
            total_calories = sum(ex.calories for ex in exercises if ex.calories) or 0

            description = "\n".join([f"• {title}" for title in exercise_titles])

            # Время тренировки (по умолчанию 10:00)
            start_time = datetime.combine(workout_date, datetime.min.time().replace(hour=10, minute=0))
            end_time = start_time + timedelta(minutes=total_duration)

            events.append({
                'id': f'workout_{day_number}',
                'title': f'🏋️ Тренировка (День {day_number})',
                'description': description,
                'location': '',
                'start': start_time.isoformat(),
                'end': end_time.isoformat(),
                'all_day': False,
                'color_id': '10',  # зелёный цвет
                'html_link': f'/my-training/day/{day_number}',
                'source': 'local',  # метка источника
                'day_number': day_number,
                'total_duration': total_duration,
                'total_calories': total_calories,
                'exercise_count': len(exercises)
            })

        # Фильтр по месяцу (если указан)
        year = request.args.get('year', type=int)
        month = request.args.get('month', type=int)

        if year and month:
            from calendar import monthrange
            time_min = datetime(year, month, 1).date()
            last_day = monthrange(year, month)[1]
            time_max = datetime(year, month, last_day).date()

            events = [
                e for e in events
                if time_min <= datetime.fromisoformat(e['start']).date() <= time_max
            ]

        return jsonify({
            'success': True,
            'events': events,
            'source': 'local',
            'count': len(events),
            'program_start_date': program_start_date.isoformat()
        })

    except Exception as e:
        app.logger.exception("Ошибка получения тренировок для календаря: %s", e)
        return jsonify({'error': str(e), 'events': []}), 500

@app.route('/api/training/exercises-for-date')
@login_required
def exercises_for_date():
    """Получить упражнения на конкретную дату из программы пользователя."""
    try:
        user = db.session.get(User, session['user_id'])
        if not user or not user.program:
            return jsonify({'success': True, 'exercises': [], 'day': None, 'exercise_details': []})

        date_str = request.args.get('date')  # формат: "2026-05-06"
        if not date_str:
            return jsonify({'success': False, 'error': 'Дата не указана'}), 400

        # Парсим дату
        try:
            selected_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            return jsonify({'success': False, 'error': 'Неверный формат даты'}), 400

        # Парсим программу
        try:
            program = json.loads(user.program) if isinstance(user.program, str) else user.program
        except Exception:
            return jsonify({'success': True, 'exercises': [], 'day': None, 'exercise_details': []})

        if not isinstance(program, dict):
            return jsonify({'success': True, 'exercises': [], 'day': None, 'exercise_details': []})

        # Дата начала программы
        program_start_date = user.created_at.date() if user.created_at else datetime.utcnow().date()

        # Определяем номер дня программы для выбранной даты
        days_diff = (selected_date - program_start_date).days

        # Если дата раньше начала программы - нет тренировки
        if days_diff < 0:
            return jsonify({'success': True, 'exercises': [], 'day': None, 'exercise_details': []})

        # Количество дней в программе
        day_keys = list(program.keys())
        if not day_keys:
            return jsonify({'success': True, 'exercises': [], 'day': None, 'exercise_details': []})

        # Извлекаем максимальный номер дня
        max_day = 0
        for day_key in day_keys:
            day_str = str(day_key).replace("_", " ").strip()
            digits = "".join(ch for ch in day_str if ch.isdigit())
            if digits:
                try:
                    max_day = max(max_day, int(digits))
                except ValueError:
                    pass

        if max_day == 0:
            return jsonify({'success': True, 'exercises': [], 'day': None, 'exercise_details': []})

        # Вычисляем день программы (с повторением)
        program_day = (days_diff % max_day) + 1

        # Находим тренировку для этого дня
        exercise_ids = None
        day_label = None

        for day_key, ids in program.items():
            day_str = str(day_key).replace("_", " ").strip()
            digits = "".join(ch for ch in day_str if ch.isdigit())

            if digits:
                try:
                    day_num = int(digits)
                    if day_num == program_day:
                        exercise_ids = ids
                        day_label = f"День {day_num}"
                        break
                except ValueError:
                    pass

        if not exercise_ids or not isinstance(exercise_ids, list):
            return jsonify({'success': True, 'exercises': [], 'day': day_label, 'exercise_details': []})

        # Получаем упражнения
        exercises = Exercise.query.filter(Exercise.id.in_(exercise_ids)).all()

        exercises_list = []
        for ex in exercises:
            exercises_list.append({
                'id': ex.id,
                'title': ex.title,
                'description': ex.description,
                'category': ex.category,
                'difficulty': ex.difficulty,
                'duration_minutes': ex.duration_minutes,
                'calories': ex.calories,
                'image_url': ex.image_url,
                'video_url': ex.video_url,
                'detailed_description': ex.detailed_description,
                'sex': ex.sex,
            })

        # Также возвращаем детали упражнений для отображения в эвент-детейлс
        exercise_details = [
            {
                'title': ex.title,
                'duration_minutes': ex.duration_minutes,
                'calories': ex.calories,
                'image_url': ex.image_url,
            }
            for ex in exercises
        ]

        return jsonify({
            'success': True,
            'exercises': exercises_list,
            'exercise_details': exercise_details,  # Для отображения в событиях
            'day': day_label,
            'date': date_str,
            'program_day_number': program_day
        })

    except Exception as e:
        app.logger.exception(f"❌ Ошибка получения упражнений по дате: {e}")
        return jsonify({'success': False, 'error': str(e), 'exercises': [], 'exercise_details': []}), 500
@app.route('/api/training/combined-calendar-events')
@login_required
def combined_calendar_events():
    """
    Объединяет события из программы тренировок И Google Calendar.
    """
    try:
        year = request.args.get('year', type=int)
        month = request.args.get('month', type=int)

        all_events = []
        sources = []

        # 1. Получаем тренировки из программы
        training_url = f'/api/training/calendar-events'
        if year and month:
            training_url += f'?year={year}&month={month}'

        # Внутренний запрос (используем test_client для симуляции)
        with app.test_client() as client:
            # Копируем сессию
            with client.session_transaction() as sess:
                sess['user_id'] = session['user_id']

            resp = client.get(training_url)
            if resp.status_code == 200:
                data = resp.get_json()
                if data.get('success'):
                    all_events.extend(data.get('events', []))
                    sources.append('local')

        # 2. Получаем события из Google Calendar (если подключен)
        token_record = GoogleCalendarToken.query.filter_by(user_id=session['user_id']).first()

        if token_record and token_record.refresh_token:
            try:
                creds = _creds_from_db(token_record)
                creds = _refresh_creds_if_needed(creds)

                if creds.token != token_record.token:
                    _save_creds_to_db(token_record, creds)
                    db.session.commit()

                service = _get_calendar_service(creds)

                if year and month:
                    google_events = _fetch_events(service, year, month)
                else:
                    now = datetime.utcnow()
                    google_events = _fetch_events(service, now.year, now.month)

                # Помечаем события из Google
                for event in google_events:
                    event['source'] = 'google'

                all_events.extend(google_events)
                sources.append('google')

            except Exception as e:
                app.logger.warning(f"Ошибка загрузки Google Calendar: {e}")

        return jsonify({
            'success': True,
            'events': all_events,
            'sources': sources,
            'count': len(all_events),
            'has_google': 'google' in sources,
            'has_local': 'local' in sources
        })

    except Exception as e:
        app.logger.exception("Ошибка объединения событий: %s", e)
        return jsonify({'error': str(e), 'events': []}), 500
@app.route('/api/login', methods=['POST'])
def login():
    email = request.form['email']
    password = request.form['password']
    remember = request.form.get('remember')

    user = User.query.filter_by(email=email).first()
    if user and user.check_password(password):
        session.clear()
        session['user_id'] = user.id
        session['username'] = user.username
        session['first_login'] = user.first_login
        if remember:
            session.permanent = True
        app.logger.info(f"✅ Пользователь {user.username} (id={user.id}) вошёл в систему")
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

    if password != passcheck:
        flash('Пароли не совпадают', 'error')
        return redirect(url_for('auth'))

    new_user = User(username=username, email=email)
    new_user.set_password(password)
    db.session.add(new_user)
    db.session.commit()
    log_user_db_action(new_user, "INSERT (register)", details="new user created via registration")

    flash('Пользователь зарегистрирован!', 'success')
    return redirect(url_for('auth'))


@app.route('/api/logout', methods=['POST', 'GET'])
def logout():
    session.clear()
    flash('Вы вышли из системы', 'info')
    return redirect(url_for('auth'))

# ═══════════════════════════════════════════════════════════════════
#                      API МАРШРУТЫ — ПРОФИЛЬ
# ═══════════════════════════════════════════════════════════════════

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

        gender = request.form.get('gender')
        weight = request.form.get('weight')
        height = request.form.get('height')
        age = request.form.get('age')
        fitness_level = request.form.get('fitness_level')
        goal = request.form.get('goal')

        try:
            weight = float(weight) if weight else None
            height = float(height) if height else None
            age = int(age) if age else None
        except ValueError:
            flash('Пожалуйста, введите корректные числовые значения', 'error')
            return redirect(url_for('main'))

        normalized_goal = normalize_goal(goal)
        if not normalized_goal:
            flash('Некорректная цель', 'error')
            return redirect(url_for('main'))

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
        program = get_program(user_id)
        user = db.session.get(User, session['user_id'])

        if program is None:
            flash('Произошла ошибка при создании программы', 'error')
            return redirect(url_for("main"))

        full_program_dict = parse_program(program)
        is_admin = user.is_admin() if user else False
        return redirect(url_for("main",
                           username=session.get('username'), 
                           first_login = session.get('first_login'),
                           is_admin=is_admin,
                           program_dict = full_program_dict))
        
    except Exception as e:
        db.session.rollback()
        flash(f'Ошибка: {str(e)}', 'error')
        return redirect(url_for('main'))


@app.route('/api/update-profile', methods=['POST'])
@login_required
def update_profile():
    try:
        user = db.session.get(User, session['user_id'])
        if not user:
            flash('Пользователь не найден', 'error')
            return redirect(url_for('profile'))

        username = request.form.get('username')
        email = request.form.get('email')
        gender = request.form.get('gender')
        weight = request.form.get('weight')
        height = request.form.get('height')
        age = request.form.get('age')
        fitness_level = request.form.get('fitness_level')
        goal = request.form.get('goal')

        if email and email != user.email:
            if User.query.filter_by(email=email).first():
                flash('Пользователь с таким email уже существует', 'error')
                return redirect(url_for('profile'))

        if username and username != user.username:
            if User.query.filter_by(username=username).first():
                flash('Пользователь с таким именем уже существует', 'error')
                return redirect(url_for('profile'))

        try:
            weight = float(weight) if weight else None
            height = float(height) if height else None
            age = int(age) if age else None
        except ValueError:
            flash('Пожалуйста, введите корректные числовые значения', 'error')
            return redirect(url_for('profile'))

        if goal:
            normalized_goal = normalize_goal(goal)
            if not normalized_goal:
                flash('Некорректная цель', 'error')
                return redirect(url_for('profile'))
            user.goal = normalized_goal

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
        user = db.session.get(User, session['user_id'])
        old_password = request.form.get('old_password')
        new_password = request.form.get('new_password')
        confirm_password = request.form.get('confirm_password')

        if not user.check_password(old_password):
            flash('Неверный текущий пароль', 'error')
            return redirect(url_for('profile'))

        if new_password != confirm_password:
            flash('Новые пароли не совпадают', 'error')
            return redirect(url_for('profile'))

        if len(new_password) < 6:
            flash('Новый пароль должен содержать минимум 6 символов', 'error')
            return redirect(url_for('profile'))

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
            completed_at=datetime.utcnow()
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

@app.route('/api/save-statistics', methods=['POST'])
@login_required
def save_statistics():
    try:
        data = request.get_json()
        
        user_id = session.get('user_id')
        exercise_id = data.get('exercise_id')
        duration_seconds = data.get('duration_seconds')
        calories_burned = data.get('calories_burned')

        
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
            completed_at=datetime.utcnow()
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

# ═══════════════════════════════════════════════════════════════════
#                      API МАРШРУТЫ — ТРЕНИРОВКИ
# ═══════════════════════════════════════════════════════════════════

@app.route('/api/generate-training', methods=['POST'])
@login_required
def generate_training():
    ensure_user_program_column()
    user = db.session.get(User, session['user_id'])
    if not user:
        flash('Пользователь не найден', 'error')
        return redirect(url_for('my_training'))

    from chat import DEFAULT_GIGACHAT_AUTH_KEY, DEFAULT_SYSTEM_PROMPT

    if not DEFAULT_GIGACHAT_AUTH_KEY:
        flash('Не настроен ключ доступа GigaChat (GIGACHAT_AUTH_KEY)', 'error')
        return redirect(url_for('my_training'))

    try:
        exercises_list = []
        for ex in Exercise.query.all():
            if user.gender and ex.sex != user.gender:
                continue
            exercises_list.append({
                'id': ex.id, 'title': ex.title, 'description': ex.description,
                'category': ex.category, 'difficulty': ex.difficulty,
                'duration_minutes': ex.duration_minutes, 'calories': ex.calories,
                'image_url': ex.image_url, 'video_url': ex.video_url,
                'detailed_description': ex.detailed_description, 'sex': ex.sex,
            })

        user_data = {
            "id": user.id, "username": user.username, "gender": user.gender,
            "weight": user.weight, "height": user.height, "age": user.age,
            "fitness_level": user.fitness_level, "program": None, "goal": user.goal,
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

        # 1) Сбросить отметки выполнений (ВАЖНО: перед commit)
        WorkoutCompletion.query.filter_by(user_id=user.id).delete()
        # или так (если где-то ругается): db.session.query(WorkoutCompletion).filter_by(user_id=user.id).delete(synchronize_session=False)

        # 2) Сохранить новую программу
        user.program = json.dumps(program_json, ensure_ascii=False)
        db.session.commit()

        # 3) Добавить в Google Calendar (если подключен)
        add_program_to_calendar(user, program_json)
        flash('Тренировка сгенерирована', 'success')
        return redirect(url_for('my_training'))

    except Exception as e:
        app.logger.exception("Ошибка генерации тренировки: %s", e)
        flash(f'Ошибка генерации: {e}', 'error')
        return redirect(url_for('my_training'))

# ═══════════════════════════════════════════════════════════════════
#                API МАРШРУТЫ — ОТМЕТКИ ТРЕНИРОВОК ✅
# ═══════════════════════════════════════════════════════════════════

@app.route('/api/workout/mark-complete', methods=['POST'])
@login_required
def mark_workout_complete():
    """Отметить тренировку как выполненную."""
    try:
        data = request.get_json()
        day_number = data.get('day_number')
        completion_date = data.get('completion_date')  # формат: "2026-05-06"

        if not day_number or not completion_date:
            return jsonify({'error': 'Отсутствуют необходимые параметры'}), 400

        user_id = session.get('user_id')
        user = db.session.get(User, user_id)

        # Парсим дату
        try:
            comp_date = datetime.strptime(completion_date, '%Y-%m-%d').date()
        except ValueError:
            return jsonify({'error': 'Неверный формат даты'}), 400

        # Проверяем, не отметили ли уже
        existing = WorkoutCompletion.query.filter_by(
            user_id=user_id,
            day_number=day_number,
            completion_date=comp_date
        ).first()

        if existing:
            return jsonify({'success': True, 'message': 'Уже отмечено', 'already_exists': True})

        # Получаем упражнения для этого дня
        exercises = []
        if user and user.program:
            try:
                program = json.loads(user.program) if isinstance(user.program, str) else user.program

                for day_key, exercise_ids in program.items():
                    day_str = str(day_key).replace("_", " ").strip()
                    digits = "".join(ch for ch in day_str if ch.isdigit())

                    if digits and int(digits) == day_number:
                        exercises_objs = Exercise.query.filter(Exercise.id.in_(exercise_ids)).all()
                        exercises = [
                            {
                                'title': ex.title,
                                'duration_minutes': ex.duration_minutes,
                                'calories': ex.calories
                            }
                            for ex in exercises_objs
                        ]
                        break
            except Exception as e:
                app.logger.warning(f"Ошибка получения упражнений: {e}")

        # Создаём новую запись
        completion = WorkoutCompletion(
            user_id=user_id,
            day_number=day_number,
            completion_date=comp_date
        )
        db.session.add(completion)
        db.session.commit()

        # Добавляем в Google Calendar если подключен
        if user and exercises:
            add_completed_workout_to_calendar(user, day_number, comp_date, exercises)

        app.logger.info(f"✅ День {day_number} отмечен как выполненный для user_id={user_id}")
        return jsonify({'success': True, 'message': 'Тренировка отмечена как выполненная'})

    except Exception as e:
        db.session.rollback()
        app.logger.exception(f"❌ Ошибка отметки тренировки: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/workout/unmark-complete', methods=['POST'])
@login_required
def unmark_workout_complete():
    """Снять отметку о выполнении тренировки."""
    try:
        data = request.get_json()
        day_number = data.get('day_number')
        completion_date = data.get('completion_date')

        if not day_number or not completion_date:
            return jsonify({'error': 'Отсутствуют необходимые параметры'}), 400

        user_id = session.get('user_id')

        try:
            comp_date = datetime.strptime(completion_date, '%Y-%m-%d').date()
        except ValueError:
            return jsonify({'error': 'Неверный формат даты'}), 400

        completion = WorkoutCompletion.query.filter_by(
            user_id=user_id,
            day_number=day_number,
            completion_date=comp_date
        ).first()

        if completion:
            db.session.delete(completion)
            db.session.commit()
            app.logger.info(f"❌ Отметка дня {day_number} снята для user_id={user_id}")

        return jsonify({'success': True, 'message': 'Отметка снята'})

    except Exception as e:
        db.session.rollback()
        app.logger.exception(f"❌ Ошибка снятия отметки: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/workout/check-incomplete', methods=['GET'])
@login_required
def check_incomplete_workouts():
    """Получить список невыполненных тренировок (сегодня и раньше)."""
    try:
        user_id = session.get('user_id')
        user = db.session.get(User, user_id)

        if not user or not user.program:
            return jsonify({'incomplete_days': [], 'has_incomplete': False})

        # Парсим программу
        try:
            program = json.loads(user.program)
        except Exception:
            return jsonify({'incomplete_days': [], 'has_incomplete': False})

        # Используем дату создания юзера как дату начала программы
        program_start_date = user.created_at.date() if user.created_at else datetime.utcnow().date()

        today = datetime.utcnow().date()
        incomplete_days = []

        # Проверяем каждый день в программе
        for day_key, exercise_ids in program.items():
            # Извлекаем номер дня
            day_str = str(day_key).replace("_", " ").strip()
            digits = "".join(ch for ch in day_str if ch.isdigit())

            if not digits:
                continue

            try:
                day_number = int(digits)
            except ValueError:
                continue

            # Дата этого дня в программе
            workout_date = program_start_date + timedelta(days=day_number - 1)

            # Проверяем только сегодня и ранее
            if workout_date > today:
                continue

            # Проверяем, выполнена ли эта тренировка
            completion = WorkoutCompletion.query.filter_by(
                user_id=user_id,
                day_number=day_number,
                completion_date=workout_date
            ).first()

            if not completion:
                incomplete_days.append({
                    'day_number': day_number,
                    'day_label': f"День {day_number}",
                    'workout_date': workout_date.isoformat(),
                    'is_overdue': workout_date < today,  # просрочена ли
                })

        has_incomplete = len(incomplete_days) > 0

        return jsonify({
            'incomplete_days': incomplete_days,
            'has_incomplete': has_incomplete,
            'total_incomplete': len(incomplete_days),
        })

    except Exception as e:
        app.logger.exception(f"❌ Ошибка проверки невыполненных тренировок: {e}")
        return jsonify({'error': str(e), 'incomplete_days': [], 'has_incomplete': False}), 500
@app.route('/api/workout/is-completed/<int:day_number>', methods=['GET'])
@login_required
def is_workout_completed(day_number):
    """Проверить, выполнена ли конкретная тренировка в конкретный день."""
    try:
        user_id = session.get('user_id')
        completion_date_str = request.args.get('date')  # формат: "2026-05-06"

        if not completion_date_str:
            completion_date = datetime.utcnow().date()
        else:
            try:
                completion_date = datetime.strptime(completion_date_str, '%Y-%m-%d').date()
            except ValueError:
                return jsonify({'error': 'Неверный формат даты'}), 400

        completion = WorkoutCompletion.query.filter_by(
            user_id=user_id,
            day_number=day_number,
            completion_date=completion_date
        ).first()

        return jsonify({
            'completed': bool(completion),
            'day_number': day_number,
            'completion_date': completion_date.isoformat()
        })

    except Exception as e:
        app.logger.exception(f"❌ Ошибка проверки выполнения: {e}")
        return jsonify({'error': str(e)}), 500


# ═══════════════════════════════════════════════════════════════════
#                      API МАРШРУТЫ — АДМИН
# ═══════════════════════════════════════════════════════════════════

@app.route('/api/admin/set-admin/<int:user_id>', methods=['POST'])
@login_required
@admin_required
def set_admin(user_id):
    try:
        user = db.session.get(User, user_id)
        if not user:
            return jsonify({'error': 'Пользователь не найден'}), 404

        if user.id == session['user_id']:
            flash('Нельзя изменить права администратора у самого себя', 'error')
            return redirect(url_for('admin_panel'))

        user.adm = not user.adm
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
        title = request.form.get('title')
        description = request.form.get('description')
        category = request.form.get('category')
        difficulty = request.form.get('difficulty')
        duration_minutes = request.form.get('duration_minutes')
        calories = request.form.get('calories')
        detailed_description = request.form.get('detailed_description')
        sex = request.form.get('sex')

        if not all([title, category, duration_minutes, calories, sex]):
            flash('Пожалуйста, заполните все обязательные поля', 'error')
            return redirect(url_for('admin_panel'))

        image_url = None
        if 'image_file' in request.files:
            image_file = request.files['image_file']
            if image_file and image_file.filename and allowed_file(
                    image_file.filename, app.config['ALLOWED_EXTENSIONS_IMAGES']):
                filename = secure_filename(image_file.filename)
                name, ext = os.path.splitext(filename)
                unique_filename = f"{name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}{ext}"
                image_file.save(os.path.join(app.config['UPLOAD_FOLDER_IMAGES'], unique_filename))
                image_url = f"/static/images/workout/{unique_filename}"
            elif image_file and image_file.filename:
                flash('Неподдерживаемый формат изображения', 'error')
                return redirect(url_for('admin_panel'))

        if not image_url:
            image_url = request.form.get('image_url')
            if not image_url:
                flash('Пожалуйста, загрузите изображение или укажите URL', 'error')
                return redirect(url_for('admin_panel'))

        video_url = None
        if 'video_file' in request.files:
            video_file = request.files['video_file']
            if video_file and video_file.filename and allowed_file(
                    video_file.filename, app.config['ALLOWED_EXTENSIONS_VIDEOS']):
                filename = secure_filename(video_file.filename)
                name, ext = os.path.splitext(filename)
                unique_filename = f"{name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}{ext}"
                video_file.save(os.path.join(app.config['UPLOAD_FOLDER_VIDEOS'], unique_filename))
                video_url = f"/static/videos/{unique_filename}"
            elif video_file and video_file.filename:
                flash('Неподдерживаемый формат видео', 'error')
                return redirect(url_for('admin_panel'))

        if not video_url:
            video_url = request.form.get('video_url')

        new_exercise = Exercise(
            title=title, description=description, category=category,
            difficulty=difficulty, duration_minutes=int(duration_minutes),
            calories=int(calories), image_url=image_url, video_url=video_url,
            detailed_description=detailed_description, sex=sex,
        )
        db.session.add(new_exercise)
        db.session.commit()
        flash('Упражнение успешно добавлено!', 'success')
        return redirect(url_for('admin_panel'))

    except Exception as e:
        db.session.rollback()
        flash(f'Ошибка: {str(e)}', 'error')
        return redirect(url_for('admin_panel'))


@app.route('/api/admin/delete-exercise/<int:exercise_id>', methods=['POST'])
@login_required
@admin_required
def delete_exercise(exercise_id):
    try:
        exercise = db.session.get(Exercise, exercise_id)
        if not exercise:
            flash('Упражнение не найдено', 'error')
            return redirect(url_for('admin_panel'))

        if exercise.image_url and '/static/images/workout/' in exercise.image_url:
            path = exercise.image_url.replace('/static/', '../frontend/static/')
            if os.path.exists(path):
                os.remove(path)

        if exercise.video_url and '/static/videos/' in exercise.video_url:
            path = exercise.video_url.replace('/static/', '../frontend/static/')
            if os.path.exists(path):
                os.remove(path)

        db.session.delete(exercise)
        db.session.commit()
        flash(f'Упражнение {exercise.title} успешно удалено', 'success')
        return redirect(url_for('admin_panel'))

    except Exception as e:
        db.session.rollback()
        flash(f'Ошибка: {str(e)}', 'error')
        return redirect(url_for('admin_panel'))

# ═══════════════════════════════════════════════════════════════════
#                  API МАРШРУТЫ — GOOGLE CALENDAR
# ═══════════════════════════════════════════════════════════════════

@app.route('/api/calendar/connect')
@login_required
def calendar_connect():
    """Шаг 1: редирект на страницу согласия Google."""
    try:
        import hashlib
        import base64
        import secrets as _secrets

        user_id = session.get('user_id')
        app.logger.info(f"📅 OAuth старт для user_id={user_id}")

        code_verifier = _secrets.token_urlsafe(64)
        code_challenge = base64.urlsafe_b64encode(
            hashlib.sha256(code_verifier.encode()).digest()
        ).rstrip(b'=').decode()

        app.logger.info(f"🔑 code_verifier сгенерирован: {code_verifier[:20]}...")

        with open(GOOGLE_CREDENTIALS_FILE, 'r') as f:
            creds_data = json.load(f)
        client_config = creds_data.get('web') or creds_data.get('installed')
        client_id = client_config['client_id']
        auth_uri = client_config['auth_uri']

        import secrets as _sec
        state = _sec.token_urlsafe(32)

        from urllib.parse import urlencode
        params = {
            'client_id': client_id,
            'redirect_uri': GOOGLE_REDIRECT_URI,
            'response_type': 'code',
            'scope': ' '.join(GOOGLE_SCOPES),
            'access_type': 'offline',
            'state': state,
            'prompt': 'consent',
            'code_challenge': code_challenge,
            'code_challenge_method': 'S256',
        }
        auth_url = f"{auth_uri}?{urlencode(params)}"

        OAuthState.cleanup_old()
        oauth_state = OAuthState(
            user_id=user_id,
            state=state,
            code_verifier=code_verifier,
        )
        db.session.add(oauth_state)
        db.session.commit()

        app.logger.info(f"✅ State + code_verifier сохранены в БД для user_id={user_id}")
        return redirect(auth_url)

    except FileNotFoundError:
        flash('Файл credentials.json не найден.', 'error')
        return redirect(url_for('main'))
    except Exception as e:
        app.logger.exception("❌ Ошибка подключения Google Calendar: %s", e)
        flash(f'Ошибка подключения: {e}', 'error')
        return redirect(url_for('main'))


@app.route('/api/calendar/callback')
def calendar_callback():
    """Шаг 2: Google возвращает код — обмениваем на токены."""
    app.logger.info("═══ CALENDAR CALLBACK START ═══")
    app.logger.info(f"Request state: {request.args.get('state')}")

    try:
        state = request.args.get('state')
        if not state:
            flash('Ошибка авторизации: отсутствует state.', 'error')
            return redirect(url_for('auth'))

        oauth_state = OAuthState.query.filter_by(state=state).first()
        if not oauth_state:
            app.logger.error(f"❌ State не найден в БД: {state[:20]}...")
            flash('Сессия истекла. Попробуйте подключить снова.', 'error')
            return redirect(url_for('auth'))

        user_id = oauth_state.user_id
        code_verifier = oauth_state.code_verifier
        app.logger.info(f"✅ State найден в БД для user_id={user_id}")
        app.logger.info(f"🔑 code_verifier получен: {code_verifier[:20] if code_verifier else 'None'}...")

        db.session.delete(oauth_state)
        db.session.commit()

        error = request.args.get('error')
        if error:
            flash(f'Авторизация отменена: {error}', 'warning')
            return redirect(url_for('auth'))

        app.logger.info("🔄 Обмен кода на токены...")

        import requests as http_requests

        with open(GOOGLE_CREDENTIALS_FILE, 'r') as f:
            creds_data = json.load(f)

        client_config = creds_data.get('web') or creds_data.get('installed')
        client_id = client_config['client_id']
        client_secret = client_config['client_secret']
        token_uri = client_config['token_uri']

        code = request.args.get('code')
        app.logger.info(f"📤 Отправляем запрос на {token_uri}")

        token_response = http_requests.post(token_uri, data={
            'code': code,
            'client_id': client_id,
            'client_secret': client_secret,
            'redirect_uri': GOOGLE_REDIRECT_URI,
            'grant_type': 'authorization_code',
            'code_verifier': code_verifier,
        })

        token_data = token_response.json()
        app.logger.info(f"📥 Token response status: {token_response.status_code}")

        if 'error' in token_data:
            app.logger.error(f"❌ Ошибка получения токена: {token_data}")
            flash(f"Ошибка авторизации: {token_data.get('error_description', token_data.get('error'))}", 'error')
            return redirect(url_for('auth'))

        app.logger.info("✅ Токены получены успешно")

        token_record = GoogleCalendarToken.query.filter_by(user_id=user_id).first()
        if not token_record:
            token_record = GoogleCalendarToken(user_id=user_id)
            db.session.add(token_record)
            app.logger.info(f"➕ Создана новая запись для user_id={user_id}")
        else:
            app.logger.info(f"♻️ Обновление токена для user_id={user_id}")

        token_record.token = token_data.get('access_token')
        token_record.refresh_token = token_data.get('refresh_token')
        token_record.token_uri = token_uri
        token_record.client_id = client_id
        token_record.client_secret = client_secret
        token_record.scopes = json.dumps(GOOGLE_SCOPES)

        expires_in = token_data.get('expires_in', 3600)
        token_record.expiry = datetime.utcnow() + timedelta(seconds=expires_in)

        db.session.commit()
        app.logger.info(f"✅ Токены сохранены для user_id={user_id}")

        user = db.session.get(User, user_id)
        if user:
            session['user_id'] = user.id
            session['username'] = user.username
            session['first_login'] = user.first_login
            session.permanent = True
            app.logger.info(f"✅ Сессия восстановлена для {user.username}")

        flash('Google Calendar успешно подключен! 🎉', 'success')
        return redirect(url_for('main'))

    except Exception as e:
        app.logger.exception("❌ Ошибка callback Google Calendar: %s", e)
        flash(f'Ошибка авторизации: {e}', 'error')
        return redirect(url_for('main'))


@app.route('/api/calendar/disconnect', methods=['POST'])
@login_required
def calendar_disconnect():
    """Отвязывает Google Calendar от аккаунта."""
    try:
        token_record = GoogleCalendarToken.query.filter_by(user_id=session['user_id']).first()
        if token_record:
            db.session.delete(token_record)
            db.session.commit()
            app.logger.info(f"🔌 Google Calendar отключен для user_id={session['user_id']}")

        return jsonify({'success': True, 'message': 'Google Calendar отключен'})

    except Exception as e:
        db.session.rollback()
        app.logger.exception("❌ Ошибка отключения календаря: %s", e)
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/calendar/events')
@login_required
def calendar_events():
    """JSON API для виджета календаря."""
    try:
        token_record = GoogleCalendarToken.query.filter_by(user_id=session['user_id']).first()
        if not token_record or not token_record.refresh_token:
            return jsonify({'error': 'Google Calendar не подключен', 'connected': False}), 401

        creds = _creds_from_db(token_record)
        creds = _refresh_creds_if_needed(creds)

        if creds.token != token_record.token:
            _save_creds_to_db(token_record, creds)
            db.session.commit()

        year = request.args.get('year', type=int) or datetime.now().year
        month = request.args.get('month', type=int) or datetime.now().month

        service = _get_calendar_service(creds)
        events = _fetch_events(service, year, month)

        return jsonify({'connected': True, 'events': events, 'count': len(events)})

    except Exception as e:
        app.logger.exception("❌ Ошибка получения событий: %s", e)
        return jsonify({'error': str(e), 'connected': False}), 500


@app.route('/api/calendar/add-workout', methods=['POST'])
@login_required
def calendar_add_workout():
    """Добавляет тренировку в Google Calendar."""
    try:
        token_record = GoogleCalendarToken.query.filter_by(user_id=session['user_id']).first()
        if not token_record:
            return jsonify({'error': 'Google Calendar не подключен'}), 401

        data = request.get_json()
        if not data:
            return jsonify({'error': 'Нет данных'}), 400

        title = data.get('title', 'Тренировка')
        date = data.get('date')
        duration = int(data.get('duration_minutes', 60))
        description = data.get('description', '')

        if not date:
            return jsonify({'error': 'Укажите дату тренировки'}), 400

        creds = _creds_from_db(token_record)
        creds = _refresh_creds_if_needed(creds)

        if creds.token != token_record.token:
            _save_creds_to_db(token_record, creds)
            db.session.commit()

        service = _get_calendar_service(creds)
        result = _add_calendar_event(service, title, date, duration, description)

        return jsonify({
            'success': True,
            'event': result,
            'message': f'Тренировка «{title}» добавлена в календарь',
        })

    except Exception as e:
        app.logger.exception("❌ Ошибка добавления события: %s", e)
        return jsonify({'error': str(e)}), 500


@app.route('/api/calendar/status')
@login_required
def calendar_status():
    """Проверка статуса подключения Google Calendar."""
    token_record = GoogleCalendarToken.query.filter_by(user_id=session['user_id']).first()
    is_connected = bool(token_record and token_record.refresh_token)
    return jsonify({'connected': is_connected})

# ═══════════════════════════════════════════════════════════════════
#                         ИНИЦИАЛИЗАЦИЯ
# ═══════════════════════════════════════════════════════════════════

with app.app_context():
    db.create_all()
    ensure_goal_column()

if __name__ == '__main__':
    app.run(debug=True)
