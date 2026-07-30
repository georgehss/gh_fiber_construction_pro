# tests/test_contagem_hp_ai.py
# tests/test_contagem_hp_ai.py
import pytest
from pathlib import Path
from unittest.mock import Mock, patch
from src.contagem_hp_ai import calcular_ftth

def test_calcular_ftth_basico():
    """Teste de cálculo FTTH básico"""
    hp = 100
    resultado = calcular_ftth(hp)

    assert resultado['hc'] == 50      # 50% penetração
    assert resultado['ctos'] == 7     # ceil(50/8) = 7
    assert resultado['pons'] == 1     # ceil(7/8) = 1
    assert resultado['ceos'] == 1     # ceil(1/2) = 1

def test_calcular_ftth_grande():
    """Teste com muitas casas"""
    hp = 1000
    resultado = calcular_ftth(hp)

    assert resultado['hc'] == 500
    assert resultado['ctos'] == 63
    assert resultado['pons'] == 8
    assert resultado['ceos'] == 4

def test_calcular_ftth_zero():
    """Teste com zero casas"""
    hp = 0
    resultado = calcular_ftth(hp)

    assert resultado['hc'] == 0
    assert resultado['ctos'] == 0
    assert resultado['pons'] == 0
    assert resultado['ceos'] == 0

# ... mais testes ...