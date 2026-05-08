import os
import sys
import pytest
import tempfile
import json
from datetime import UTC, datetime, timedelta

# Добавляем путь к backend
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app, db, User, Exercise, Statistics, FavoriteExercise
from werkzeug.security import generate_password_hash

# Эти функции должны быть доступны для импорта в другие тесты
def login(client, email, password):
    """Вспомогательная функция для входа"""
    return client.post('/api/login', data={
        'email': email,
        'password': password
    }, follow_redirects=True)

def logout(client):
    """Вспомогательная функция для выхода"""
    return client.get('/api/logout', follow_redirects=True)

@pytest.fixture
def client():
    """Настройка тестового клиента Flask с тестовой БД"""
    app.config['TESTING'] = True
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///test_fitness.db'
    app.config['WTF_CSRF_ENABLED'] = False
    app.config['SERVER_NAME'] = 'localhost.localdomain'
    
    with app.test_client() as client:
        with app.app_context():
            db.create_all()
            yield client
            db.session.remove()
            db.drop_all()

@pytest.fixture
def test_user(client):
    """Создание тестового пользователя с программой тренировок"""
    user = User(
        username='testuser',
        email='test@example.com',
        password_hash=generate_password_hash('password123'),
        gender='male',
        weight=75.0,
        height=180.0,
        age=25,
        fitness_level='intermediate',
        goal='maintain_weight',
        first_login=False,
        adm=False
    )
    db.session.add(user)
    db.session.commit()
    
    # Добавляем программу после сохранения пользователя
    user.program = json.dumps({
        "2024-01-15": [
            {"id": 1, "status": "pending"},
            {"id": 2, "status": "pending"}
        ]
    })
    db.session.commit()
    
    return user

@pytest.fixture
def test_admin(client):
    """Создание тестового администратора"""
    admin = User(
        username='admin',
        email='admin@example.com',
        password_hash=generate_password_hash('admin123'),
        gender='male',
        weight=80.0,
        height=185.0,
        age=30,
        fitness_level='advanced',
        goal='gain_mass',
        first_login=False,
        adm=True
    )
    db.session.add(admin)
    db.session.commit()
    return admin

@pytest.fixture
def test_exercises(client):
    """Создание тестовых упражнений"""
    exercises = [
        Exercise(
            id=1,
            title='Pushups',
            description='Classic pushups from the floor',
            category='strength',
            difficulty='intermediate',
            duration_minutes=5,
            calories=50,
            image_url='/static/images/pushup.jpg',
            sex='male'
        ),
        Exercise(
            id=2,
            title='Squats',
            description='Bodyweight squats',
            category='strength',
            difficulty='beginner',
            duration_minutes=5,
            calories=40,
            image_url='/static/images/squat.jpg',
            sex='unisex'
        ),
        Exercise(
            id=3,
            title='Running in place',
            description='Intensive cardio',
            category='cardio',
            difficulty='intermediate',
            duration_minutes=10,
            calories=100,
            image_url='/static/images/running.jpg',
            sex='unisex'
        )
    ]
    for ex in exercises:
        db.session.add(ex)
    db.session.commit()
    return exercises

@pytest.fixture
def test_statistics(client, test_user, test_exercises):
    """Создание тестовой статистики"""
    stats = []
    for i in range(5):
        stat = Statistics(
            user_id=test_user.id,
            exercise_id=test_exercises[i % 3].id,
            duration_seconds=(i + 1) * 60,
            calories_burned=(i + 1) * 50,
            completed=True,
            completed_at=datetime.now(UTC) - timedelta(days=i)
        )
        stats.append(stat)
        db.session.add(stat)
    db.session.commit()
    return stats

@pytest.fixture
def test_favorite(client, test_user, test_exercises):
    """Создание тестового избранного"""
    favorite = FavoriteExercise(
        user_id=test_user.id,
        exercise_id=test_exercises[0].id
    )
    db.session.add(favorite)
    db.session.commit()
    return favorite