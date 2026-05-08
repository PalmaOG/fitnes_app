import pytest
from app import db, User
from tests.conftest import login

def test_admin_page_requires_admin(client, test_user):
    """Test admin panel access by non-admin"""
    login(client, test_user.email, 'password123')
    response = client.get('/admin', follow_redirects=True)
    assert 'У вас нет прав доступа' in response.text

def test_admin_page_for_admin(client, test_admin):
    """Test admin panel access by admin"""
    login(client, test_admin.email, 'admin123')
    response = client.get('/admin')
    assert response.status_code == 200
    assert 'Админ панель' in response.text

def test_admin_set_user_admin(client, test_admin, test_user):
    """Test setting user as admin"""
    login(client, test_admin.email, 'admin123')
    response = client.post(f'/api/admin/set-admin/{test_user.id}', 
                          follow_redirects=True)
    assert response.status_code == 200
    assert test_user.is_admin() == True