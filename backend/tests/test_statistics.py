import pytest
import json
from app import db, Statistics
from tests.conftest import login

def test_save_statistics(client, test_user, test_exercises):
    """Test saving workout statistics"""
    login(client, test_user.email, 'password123')
    
    response = client.post('/api/save-statistics', 
                          json={
                              'exercise_id': test_exercises[0].id,
                              'duration_seconds': 180,
                              'calories_burned': 30,
                              'date': '2024-01-15'
                          },
                          content_type='application/json')
    
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data['success'] == True
    
    stats = Statistics.query.filter_by(user_id=test_user.id).first()
    assert stats is not None
    assert stats.duration_seconds == 180

def test_save_statistics_missing_data(client, test_user):
    """Test saving statistics with missing data"""
    login(client, test_user.email, 'password123')
    
    response = client.post('/api/save-statistics', 
                          json={'exercise_id': 1},
                          content_type='application/json')
    
    data = json.loads(response.data)
    assert data['success'] == False
    assert 'Недостаточно данных' in data['error']

def test_main_page_statistics(client, test_user, test_statistics):
    """Test statistics display on main page"""
    login(client, test_user.email, 'password123')
    response = client.get('/main')
    assert response.status_code == 200
    assert 'Прогресс программы' in response.text