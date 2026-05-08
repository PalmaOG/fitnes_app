import pytest
import json
from app import db, User
from tests.conftest import login

def test_intro_api(client, test_user):
    """Test intro API"""
    login(client, test_user.email, 'password123')
    response = client.post('/api/intro', data={
        'gender': 'female',
        'weight': '65',
        'height': '170',
        'age': '28',
        'fitness_level': 'intermediate',
        'goal': 'lose_weight'
    }, follow_redirects=True)
    
    assert response.status_code == 200

def test_update_exercise_status(client, test_user):
    """Test exercise status update"""
    login(client, test_user.email, 'password123')
    
    # Обновляем статус упражнения (программа уже есть в test_user)
    response = client.post('/api/update-exercise-status',
                          json={
                              'date': '2024-01-15',
                              'exercise_id': 1,
                              'status': 'completed'
                          },
                          content_type='application/json')
    
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data['success'] == True
    
    # Проверяем, что статус обновился
    with client.application.app_context():
        user = db.session.get(User, test_user.id)
        program = json.loads(user.program)
        assert program['2024-01-15'][0]['status'] == 'completed'

def test_check_day_completion(client, test_user):
    """Test day completion check"""
    login(client, test_user.email, 'password123')
    
    response = client.get('/api/check-day-completion/2024-01-15')
    assert response.status_code == 200
    data = json.loads(response.data)
    assert 'all_completed' in data