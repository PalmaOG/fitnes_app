from functools import wraps
import secrets
from flask import Flask, flash, redirect,render_template, request, url_for, session
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash,check_password_hash
from datetime import datetime

app = Flask(__name__, template_folder='../frontend', static_folder='../frontend/static')

# Конфигурация БД (SQLite)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///fitness.db'
app.secret_key = secrets.token_hex(16)  # В реальном проекте храните в переменных окружения

# Инициализируем БД
db = SQLAlchemy(app)

# Модель пользователя (пример)
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.today)
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

# Создаем таблицы (в первый раз)
with app.app_context():
    db.create_all()


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
    return render_template('index.html', username=session.get('username'))

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
    
    # Проверяем, существует ли пользователь
    if User.query.filter_by(email=email).first():
        flash('Пользователь уже существует', 'error')
        return redirect(url_for('auth'))
    
    if (password!=passcheck):
        flash('Пароли не совпадают', 'error')
        return redirect(url_for('auth'))

    # Создаем нового с хешированным паролем
    new_user = User(username=username, email=email)
    new_user.set_password(password)
    
    db.session.add(new_user)
    db.session.commit()
    
    flash('Пользователь зарегистрирован!','success')
    return redirect(url_for('auth'))

@app.route('/api/logout', methods=['POST'])
def logout():

    session.clear()
    flash('Вы вышли из системы', 'info')
    return redirect(url_for('auth'))

if __name__ == '__main__':
    app.run(debug=True)