# Makefile
.PHONY: help install test lint format clean run

help:
    @echo "🔧 GH Fiber Construction Pro - Comandos disponíveis:"
    @echo "  make install    - Instalar dependências"
    @echo "  make test       - Executar testes"
    @echo "  make lint       - Verificar código (flake8)"
    @echo "  make format     - Formatar código (black)"
    @echo "  make clean      - Limpar cache"
    @echo "  make run        - Executar pipeline completo"

install:
    pip install -r requirements.txt
    pip install -r requirements-dev.txt

test:
    pytest tests/ -v --cov=src

lint:
    flake8 src/ --max-line-length=100

format:
    black src/ tests/

clean:
    find . -type d -name __pycache__ -exec rm -rf {} +
    find . -type f -name "*.pyc" -delete
    rm -rf .pytest_cache .coverage htmlcov

run:
    python src/contagem_hp_ai.py
    python src/posicionamento_inteligente.py

all: install lint test run