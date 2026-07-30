#!/bin/bash
# install.sh

echo "🚀 Instalando GH Fiber Construction Pro v2.0..."

# Criar venv
python3 -m venv venv
source venv/bin/activate

# Instalar dependências
pip install --upgrade pip
pip install -r requirements.txt

# Validar instalação
python -c "import overturemaps; import shapely; print('✅ Dependências OK')"

# Criar diretórios
mkdir -p data/input data/output logs tests

echo "✅ Instalação concluída!"
echo "Execute: source venv/bin/activate"