from functools import wraps
import secrets
from flask import Flask, flash, redirect,render_template, request, url_for, session
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash,check_password_hash
from datetime import datetime

app = Flask(__name__, template_folder='../frontend', static_folder='../frontend/static')

# Конфигурация БД (SQLite)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///fitness.db'
app.secret_key = secrets.token_hex(16)  

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

    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

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
    
    
    def __repr__(self):
        return f'<Exercise {self.title}>'
    

# Декоратор для проверки авторизации
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Пожалуйста, войдите в систему', 'warning')
            return redirect(url_for('auth'))
        return f(*args, **kwargs)
    return decorated_function

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
    return render_template('index.html', username=session.get('username'), first_login = session.get('first_login'))

@app.route('/programs')
@login_required
def workouts():
    exercises = Exercise.query.all()
    # Преобразуем объекты Exercise в словари для JSON сериализации
    exercises_list = []
    for exercise in exercises:
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

#Маршруты сервера
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


@app.route('/api/updateProfile', methods=['POST'])
def updateProfile():
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
        return redirect(url_for('main'))
        
    except Exception as e:
        db.session.rollback()
        flash(f'Произошла ошибка при сохранении профиля: {str(e)}', 'error')
        return redirect(url_for('main'))


if __name__ == '__main__':
    app.run(debug=True)