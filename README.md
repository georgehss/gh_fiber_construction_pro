# 🌐 GH Fiber Construction Pro - Template Automatizado FTTH

Sistema inteligente para contagem automatizada de Home Passed (HP) usando Inteligência Artificial (Overture Maps) e posicionamento otimizado de caixas de atendimento (CTOs e CEOs) utilizando algoritmos de clusterização (K-Means).

## 📁 Estrutura do Projeto

```text
gh_fiber_construction_pro/
├── config.json               # Regras de engenharia (splitters, penetração)
├── src/                      # Scripts de automação
│   ├── contagem_hp_ai.py
│   └── posicionamento.py
├── data/
│   ├── input/                # Coloque os KMLs/KMZs de entrada aqui
│   └── output/               # Resultados, KMLs gerados e caches
└── docs/                     # Documentação de apoio

⚙️ Configuração Inicial
Instale as dependências:
Abra o terminal na pasta raiz e instale as bibliotecas necessárias:

Bash
pip install -r requirements.txt

Configure as Regras de Negócio:
Edite o arquivo config.json na raiz do projeto para definir a taxa de penetração esperada, tamanho dos splitters e nomenclatura da OLT padrão.

🚀 Como Usar (Passo a Passo)
Passo 1: Preparar o Polígono

Desenhe o polígono de atendimento no Google Earth ou QGIS.

Salve o arquivo .kml ou .kmz e coloque-o exclusivamente na pasta data/input/.

Nota: Certifique-se de que haja apenas um arquivo de projeto por vez nesta pasta para evitar conflitos.

Passo 2: Contagem de HP via IA

Execute o script de contagem para baixar as edificações da nuvem e realizar o pré-cálculo da rede:

Bash
python src/contagem_hp_ai.py
O sistema salvará os cálculos e gerará um KML com as residências detectadas na pasta data/output/.

Passo 3: Posicionamento Inteligente

Após a contagem, execute o script de posicionamento para espalhar as caixas pela malha viária:

Bash
python src/posicionamento_inteligente.py
Os arquivos finais CTOs Posicionadas.kml e CEOs Posicionadas.kml estarão disponíveis na pasta data/output/.

🧹 Limpeza para Novos Projetos
Para iniciar um novo projeto, basta apagar os arquivos da pasta data/input/ e data/output/ e inserir o novo KML de loteamento.