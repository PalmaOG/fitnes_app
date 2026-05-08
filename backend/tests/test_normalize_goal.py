import pytest
from app import normalize_goal

def test_normalize_goal_canonical():
    """Test normalization of canonical values"""
    assert normalize_goal('lose_weight') == 'lose_weight'
    assert normalize_goal('maintain_weight') == 'maintain_weight'
    assert normalize_goal('gain_mass') == 'gain_mass'

def test_normalize_goal_russian():
    """Test normalization of Russian values"""
    assert normalize_goal('похудение') == 'lose_weight'
    assert normalize_goal('похудеть') == 'lose_weight'
    assert normalize_goal('поддержание') == 'maintain_weight'
    assert normalize_goal('поддержание веса') == 'maintain_weight'
    assert normalize_goal('набор') == 'gain_mass'
    assert normalize_goal('набор массы') == 'gain_mass'

def test_normalize_goal_case_insensitive():
    """Test normalization with different case"""
    assert normalize_goal('LOSE_WEIGHT') == 'lose_weight'
    assert normalize_goal('MAINTAIN_WEIGHT') == 'maintain_weight'
    assert normalize_goal('Похудеть') == 'lose_weight'

def test_normalize_goal_none():
    """Test normalization of None"""
    assert normalize_goal(None) is None

def test_normalize_goal_empty():
    """Test normalization of empty string"""
    assert normalize_goal('') is None
    assert normalize_goal('   ') is None

def test_normalize_goal_unknown():
    """Test normalization of unknown value"""
    assert normalize_goal('unknown') is None