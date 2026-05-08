import pytest
from app import db, User
from tests.conftest import login, logout

def test_register_page(client):
    """Test registration page"""
    response = client.get('/auth')
    assert response.status_code == 200
    assert 'FitHub' in response.text

def test_register_success(client):
    """Test successful registration"""
    response = client.post('/api/register', data={
        'username': 'newuser2',
        'email': 'newuser2@example.com',
        'password': 'password123',
        'passcheck': 'password123'
    }, follow_redirects=True)
    
    assert response.status_code == 200
    user = User.query.filter_by(email='newuser2@example.com').first()
    assert user is not None
    assert user.username == 'newuser2'

def test_register_password_mismatch(client):
    """Test registration with mismatched passwords"""
    response = client.post('/api/register', data={
        'username': 'testuser2',
        'email': 'test2@example.com',
        'password': 'password123',
        'passcheck': 'different123'
    }, follow_redirects=True)
    
    assert 'Пароли не совпадают' in response.text

def test_register_existing_email(client, test_user):
    """Test registration with existing email"""
    response = client.post('/api/register', data={
        'username': 'another',
        'email': test_user.email,
        'password': 'password123',
        'passcheck': 'password123'
    }, follow_redirects=True)
    
    assert 'Пользователь уже существует' in response.text

def test_login_success(client, test_user):
    """Test successful login"""
    response = login(client, test_user.email, 'password123')
    assert response.status_code == 200
    
    with client.session_transaction() as sess:
        assert sess['user_id'] == test_user.id
        assert sess['username'] == test_user.username

def test_login_invalid_password(client, test_user):
    """Test login with invalid password"""
    response = login(client, test_user.email, 'wrongpassword')
    assert 'Неверный email или пароль' in response.text

def test_login_nonexistent_email(client):
    """Test login with non-existent email"""
    response = login(client, 'nonexistent@example.com', 'password123')
    assert 'Неверный email или пароль' in response.text

def test_logout(client, test_user):
    """Test logout"""
    login(client, test_user.email, 'password123')
    response = logout(client)
    assert response.status_code == 200
    
    with client.session_transaction() as sess:
        assert 'user_id' not in sess