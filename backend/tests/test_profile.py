import pytest
from app import db, User
from tests.conftest import login, logout

def test_profile_page_requires_login(client):
    """Test profile access without authentication"""
    response = client.get('/profile', follow_redirects=True)
    assert 'Пожалуйста, войдите' in response.text

def test_profile_page_authenticated(client, test_user):
    """Test profile access for authenticated user"""
    login(client, test_user.email, 'password123')
    response = client.get('/profile')
    assert response.status_code == 200
    assert 'Мой профиль' in response.text

def test_update_profile(client, test_user):
    """Test profile update"""
    login(client, test_user.email, 'password123')
    response = client.post('/api/update-profile', data={
        'username': 'updateduser',
        'email': 'updated@example.com',
        'gender': 'female',
        'weight': '65',
        'height': '170',
        'age': '26',
        'fitness_level': 'advanced',
        'goal': 'lose_weight'
    }, follow_redirects=True)
    
    assert response.status_code == 200
    updated_user = db.session.get(User, test_user.id)
    assert updated_user.username == 'updateduser'
    assert updated_user.weight == 65.0

def test_change_password(client, test_user):
    """Test password change"""
    login(client, test_user.email, 'password123')
    response = client.post('/api/change-password', data={
        'old_password': 'password123',
        'new_password': 'newpassword456',
        'confirm_password': 'newpassword456'
    }, follow_redirects=True)
    
    assert response.status_code == 200
    
    logout(client)
    response = login(client, test_user.email, 'password123')
    assert 'Неверный email или пароль' in response.text
    
    response = login(client, test_user.email, 'newpassword456')
    assert response.status_code == 200

def test_change_password_wrong_old(client, test_user):
    """Test password change with wrong old password"""
    login(client, test_user.email, 'password123')
    response = client.post('/api/change-password', data={
        'old_password': 'wrongpassword',
        'new_password': 'newpassword',
        'confirm_password': 'newpassword'
    }, follow_redirects=True)
    
    assert 'Неверный текущий пароль' in response.text