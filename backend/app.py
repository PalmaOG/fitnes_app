from functools import wraps
import secrets
from flask import Flask, flash, jsonify, redirect,render_template, request, url_for, session
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash,check_password_hash
from werkzeug.utils import secure_filename
from datetime import datetime
import time
import os
from chat import get_program
import json


app = Flask(__name__, template_folder='../frontend', static_folder='../frontend/static')

# Конфигурация БД (SQLite)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///fitness.db'
app.secret_key = secrets.token_hex(16)  
app.config['UPLOAD_FOLDER_IMAGES'] = '../frontend/static/images/workout'
app.config['UPLOAD_FOLDER_VIDEOS'] = '../frontend/static/videos'
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024  # 500MB max file size
app.config['ALLOWED_EXTENSIONS_IMAGES'] = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
app.config['ALLOWED_EXTENSIONS_VIDEOS'] = {'mp4', 'webm', 'ogg', 'mov'}

# Создаем папки если их нет
os.makedirs(app.config['UPLOAD_FOLDER_IMAGES'], exist_ok=True)
os.makedirs(app.config['UPLOAD_FOLDER_VIDEOS'], exist_ok=True)

def allowed_file(filename, allowed_extensions):
    """Проверка разрешенного расширения файла"""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in allowed_extensions

# Инициализируем БД
db = SQLAlchemy(app)

# Модель пользователя 
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.today)
    gender = db.Column(db.String(20), nullable=True)
    weight = db.Column(db.Float, nullable=True)  # в кг
    height = db.Column(db.Float, nullable=True)  # в см
    age = db.Column(db.Integer, nullable=True)
    fitness_level = db.Column(db.String(30), nullable=True)
    first_login = db.Column(db.Boolean, default=True)  # Флаг первого входа
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
    title = db.Column(db.String(200), nullable=False)  # Название упражнения
    description = db.Column(db.Text, nullable=True)    # Описание
    category = db.Column(db.String(50), nullable=False)  # cardio, strength, yoga, stretching
    difficulty = db.Column(db.String(20), default='beginner')  # beginner, intermediate, advanced
    
    # Длительность и калории
    duration_minutes = db.Column(db.Integer, nullable=False)  # Длительность в минутах
    calories = db.Column(db.Integer, nullable=False)  # Сжигаемые калории
    
    # Изображения и видео
    image_url = db.Column(db.String(500), nullable=False)  # Путь к изображению
    video_url = db.Column(db.String(500), nullable=True)   # Путь к видео
    
    # Детальная информация для модального окна
    detailed_description = db.Column(db.Text, nullable=True)  # Подробное описание

    sex = db.Column(db.String(10), nullable=False)
    
    
    def __repr__(self):
        return f'<Exercise {self.title}>'


def parse_program(program_dict: dict):
    full_program = {}

    for day, exercise_ids in program_dict.items():
        full_exercises = []
        
        for exercise_id in exercise_ids:
            # Получаем упражнение из БД
            exercise = Exercise.query.get(exercise_id)
            
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


# Декоратор для проверки авторизации
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
        user = User.query.get(session['user_id'])
        if not user or not user.is_admin():
            flash('У вас нет прав доступа к этой странице', 'error')
            return redirect(url_for('main'))
        
        return f(*args, **kwargs)
    return wrapper

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
    user = User.query.get(session['user_id'])
    is_admin = user.is_admin() if user else False

     # Получаем программу пользователя
    current_exercises = []
    
    if user.program:
        # Преобразуем JSON строку в словарь
        import json
        program_dict = json.loads(user.program) if isinstance(user.program, str) else user.program
        
        # Получаем упражнения из "Day 1"
        day1_exercises_ids = program_dict.get("Day 1", [])
        
        if day1_exercises_ids:
            # Получаем полные данные упражнений из БД
            exercises = Exercise.query.filter(Exercise.id.in_(day1_exercises_ids)).all()
            
            # Преобразуем в словари для удобства
            current_exercises = []
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
                    'sex': ex.sex
                })

    return render_template('index.html', 
                           username=session.get('username'), 
                           first_login = session.get('first_login'),
                           is_admin=is_admin,
                           current_exercises = current_exercises)

# Админ панель
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
    user = User.query.get(session['user_id'])
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

    return render_template('programs.html', username=session.get('username'), exercises=exercises_list)


@app.route('/profile')
@login_required
def profile():
    user = User.query.get(session['user_id'])
    return render_template('profile.html', 
                         username=session.get('username'),
                         user=user)

#Маршруты сервера
@app.route('/api/admin/set-admin/<int:user_id>', methods=['POST'])
@login_required
@admin_required
def set_admin(user_id):
    try:
        user = User.query.get(user_id)
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
        user = User.query.get(user_id)
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
        exercise = Exercise.query.get(exercise_id)
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
        # Получаем ID пользователя из сессии
        user_id = session.get('user_id')
        
        if not user_id:
            flash('Пользователь не авторизован', 'error')
            return redirect(url_for('auth'))
        
        # Находим пользователя в БД
        user = User.query.get(user_id)
        
        if not user:
            flash('Пользователь не найден', 'error')
            return redirect(url_for('auth'))
        
        # Получаем данные из формы
        gender = request.form.get('gender')
        weight = request.form.get('weight')
        height = request.form.get('height')
        age = request.form.get('age')
        fitness_level = request.form.get('fitness_level')
         
        # Преобразование типов данных
        try:
            weight = float(weight) if weight else None
            height = float(height) if height else None
            age = int(age) if age else None
        except ValueError:
            flash('Пожалуйста, введите корректные числовые значения', 'error')
            return redirect(url_for('main'))
        
        # Обновляем данные пользователя
        user.gender = gender
        user.weight = weight
        user.height = height
        user.age = age
        user.fitness_level = fitness_level
        user.first_login = False  # Сбрасываем флаг первого входа
        
        # Сохраняем изменения в БД
        db.session.commit()
        session['first_login'] = False
        flash('Профиль успешно обновлен!', 'success')
        program = get_program(user_id)
        user = User.query.get(session['user_id'])
        if program is None:
           flash(f'Произошла ошибка при создании программы:', 'error')
           return redirect(url_for("main"))
        else:
            full_program_dict = parse_program(program)
        is_admin = user.is_admin() if user else False
        return render_template('index.html', 
                           username=session.get('username'), 
                           first_login = session.get('first_login'),
                           is_admin=is_admin,
                           program_dict = full_program_dict)
        
    except Exception as e:
        db.session.rollback()
        flash(f'Произошла ошибка при сохранении профиля: {str(e)}', 'error')
        return redirect(url_for('main'))




@app.route('/api/update-profile', methods=['POST'])
@login_required
def update_profile():
    try:
        user_id = session.get('user_id')
        user = User.query.get(user_id)
        
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
        user = User.query.get(user_id)
        
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

if __name__ == '__main__':
    app.run(host="0.0.0.0", port=5000, debug=True)