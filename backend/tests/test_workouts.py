import pytest
import json
from app import db, Exercise
from tests.conftest import login

def test_programs_page_authenticated(client, test_user, test_exercises):
    """Test workouts page for authenticated user"""
    login(client, test_user.email, 'password123')
    response = client.get('/programs')
    assert response.status_code == 200
    assert 'Библиотека упражнений' in response.text

def test_programs_page_filters_by_gender(client, test_user, test_exercises):
    """Test exercise filtering by gender"""
    login(client, test_user.email, 'password123')
    response = client.get('/programs')
    assert response.status_code == 200
    assert 'Pushups' in response.text

def test_favorite_toggle(client, test_user, test_exercises):
    """Test add/remove favorite"""
    login(client, test_user.email, 'password123')
    
    response = client.post('/api/favorite/toggle', 
                          json={'exercise_id': test_exercises[0].id},
                          content_type='application/json')
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data['success'] == True
    assert data['action'] == 'added'
    
    response = client.post('/api/favorite/toggle', 
                          json={'exercise_id': test_exercises[0].id},
                          content_type='application/json')
    data = json.loads(response.data)
    assert data['action'] == 'removed'

def test_get_favorites(client, test_user, test_exercises):
    """Test get favorites list"""
    login(client, test_user.email, 'password123')
    
    client.post('/api/favorite/toggle', 
               json={'exercise_id': test_exercises[0].id},
               content_type='application/json')
    client.post('/api/favorite/toggle', 
               json={'exercise_id': test_exercises[1].id},
               content_type='application/json')
    
    response = client.get('/api/favorites')
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data['success'] == True
    assert test_exercises[0].id in data['favorites']
    assert test_exercises[1].id in data['favorites']