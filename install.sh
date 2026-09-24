#!/bin/bash
set -e

echo "Instalando GH Fiber Construction Pro v2.0..."

python3 -m venv venv
source venv/bin/activate

python -m pip install --upgrade pip
python -m pip install -r requirements.txt

python -c "import overturemaps; import shapely; import networkx; import sklearn; print('Dependencias OK')"

mkdir -p data/input data/output

python tests/validate_config.py

echo "Instalacao concluida."
echo "Ative o ambiente: source venv/bin/activate"
echo "Execute o sistema: python -m src"
