import pytest
from app import db, User, Exercise, Statistics, FavoriteExercise

def test_create_user(client):
    """Тест создания пользователя"""
    user = User(
        username='newuser',
        email='new@example.com',
        password_hash='hash',
        gender='female',
        weight=60.0,
        height=165.0,
        age=28,
        fitness_level='beginner'
    )
    db.session.add(user)
    db.session.commit()
    
    saved_user = User.query.filter_by(email='new@example.com').first()
    assert saved_user is not None
    assert saved_user.username == 'newuser'
    assert saved_user.gender == 'female'

def test_user_password_hashing(client, test_user):
    """Тест хеширования пароля"""
    assert test_user.check_password('password123') == True
    assert test_user.check_password('wrongpassword') == False

def test_user_is_admin(client, test_user, test_admin):
    """Тест проверки прав администратора"""
    assert test_user.is_admin() == False
    assert test_admin.is_admin() == True

def test_create_exercise(client):
    """Тест создания упражнения"""
    exercise = Exercise(
        title='Планка',
        description='Упражнение для пресса',
        category='strength',
        difficulty='intermediate',
        duration_minutes=3,
        calories=30,
        image_url='/static/images/plank.jpg',
        sex='unisex'
    )
    db.session.add(exercise)
    db.session.commit()
    
    saved_exercise = Exercise.query.filter_by(title='Планка').first()
    assert saved_exercise is not None
    assert saved_exercise.calories == 30

def test_statistics_relationship(client, test_user, test_statistics):
    """Тест связи статистики с пользователем"""
    user = db.session.get(User, test_user.id)
    assert len(user.statistics) == 5
    assert all(stat.user_id == test_user.id for stat in user.statistics)

def test_favorite_exercise(client, test_user, test_exercises):
    """Тест добавления упражнения в избранное"""
    favorite = FavoriteExercise(
        user_id=test_user.id,
        exercise_id=test_exercises[0].id
    )
    db.session.add(favorite)
    db.session.commit()
    
    user = db.session.get(User, test_user.id)
    assert len(user.favorites) == 1
    assert user.favorites[0].exercise_id == test_exercises[0].id