# GH Fiber Construction Pro

Ferramenta de pré-planejamento FTTH para estimativa de Home Passed (HP), dimensionamento físico de CTO/PON/CEO e posicionamento geoespacial dos elementos de rede.

> Estado atual: **Fase 6 concluída**. Além da regra capacitada de **16 HP por CTO**, o roteamento agora possui estados explícitos, usa pesos em metros e índice espacial, não converte falhas em cabos retos silenciosos e pode inserir a **OLT física** no feeder/backbone.

## Estrutura

```text
gh_fiber_construction_pro/
├── config.json
├── pyproject.toml
├── requirements.txt
├── install.sh
├── src/
│   ├── __init__.py
│   ├── __main__.py
│   ├── main.py
│   ├── config.py
│   ├── config_validator.py
│   ├── geo_io.py
│   ├── cache_manager.py
│   ├── dimensionamento.py
│   ├── clusterizacao.py
│   ├── roteamento.py
│   ├── contagem_hp.py
│   ├── posicionamento.py
│   └── logger_config.py
├── data/
│   ├── input/
│   └── output/
└── tests/
    ├── test_cache_manager.py
    ├── test_clusterizacao.py
    ├── test_config_loader.py
    ├── test_config_validator.py
    ├── test_contagem_hp.py
    ├── test_dimensionamento.py
    ├── test_geo_io.py
    ├── test_posicionamento_config.py
    ├── test_roteamento.py
    └── validate_config.py
```

## Instalação

No Linux/macOS:

```bash
bash install.sh
source venv/bin/activate
```

No Windows, com o ambiente virtual ativado:

```powershell
python -m pip install -r requirements.txt
```

## Execução

A partir da raiz do projeto:

```bash
python -m src
```

Etapas separadas:

```bash
python -m src.contagem_hp
python -m src.posicionamento
```

Validação da configuração:

```bash
python tests/validate_config.py
```

## Regra de engenharia da CTO

A partir da Fase 5, a CTO possui três conceitos separados:

```text
Cobertura física máxima:     16 HP
Splitter inicial:           1x8
Splitter de expansão:      1x16
```

Com penetração de 50%, uma CTO cheia possui expectativa de:

```text
16 HP × 50% = 8 HC
```

Portanto, o splitter 1x8 atende a expectativa inicial. Se a penetração crescer, a mesma CTO pode ser expandida para 1x16 e atender todos os 16 HP cobertos.

A quantidade de CTOs **não é mais reduzida pela taxa de penetração**. A regra principal é:

```text
CTOs = ceil(HP planejados / 16)
```

Exemplo com 100 HP e sem reserva:

```text
HP detectados                 100
HC esperado (50%)              50
CTOs necessárias                7
Cobertura física instalada    112 HP
Capacidade inicial              56 HC  (7 × 1x8)
Capacidade após expansão       112 HC  (7 × 1x16)
```

## Configuração da Fase 6

A configuração atual está na versão `6.0`.

Trecho principal de engenharia:

```json
{
  "engenharia": {
    "penetracao_estimada": 0.5,
    "reserva_capacidade_percentual": 0.0,
    "capacidade_hp_por_cto": 16,
    "splitter_cto_inicial": 8,
    "splitter_cto_expansao": 16,
    "ctos_por_pon": 8,
    "pons_por_ceo": 2,
    "distancia_maxima_snap_metros": 50,
    "distancia_maxima_entre_ctos_metros": 150,
    "margem_bbox_roteamento_metros": 150
  },
  "equipamentos": {
    "nome_olt_padrao": "N70",
    "olt": {
      "latitude": null,
      "longitude": null
    }
  }
}
```

### Reserva

`reserva_capacidade_percentual` passa a ser aplicada sobre **HP físico**. Exemplo com 100 HP e 20% de reserva:

```text
HP reais                      100
HP planejados                 120
CTOs                           8
Cobertura instalada           128 HP
```

A reserva cria capacidade física adicional sem alterar a definição de HC.

### Validação dos splitters

A configuração exige:

```text
splitter_cto_inicial <= splitter_cto_expansao
splitter_cto_expansao >= capacidade_hp_por_cto
```

Assim, a expansão precisa ser capaz de atender todos os HP cobertos pela CTO.

## Clusterização capacitada

O arquivo `src/clusterizacao.py` introduz a alocação com limites rígidos.

### HP → CTO

Cada HP pertence a exatamente uma CTO e nenhuma CTO automática recebe mais de:

```text
capacidade_hp_por_cto = 16 HP
```

K-Means é usado somente para gerar sementes geográficas. A atribuição final passa por um algoritmo capacitado e é validada antes da exportação.

Exemplos:

```text
32 HP → 2 CTOs, máximo 16 HP em cada
33 HP → 3 CTOs
100 HP → 7 CTOs
```

### CTO → PON

Cada CTO pertence a exatamente uma PON e cada PON recebe no máximo:

```text
ctos_por_pon = 8 CTOs
```

Exemplo:

```text
17 CTOs → 3 PONs
```

### PON → CEO

Cada PON pertence a exatamente uma CEO e cada CEO recebe no máximo:

```text
pons_por_ceo = 2 PONs
```

Exemplo:

```text
5 PONs → 3 CEOs
```

A sequência física dos cabos continua sendo organizada pelas ruas, mas o roteamento não pode mais mover uma CTO de uma PON para outra nem estourar as capacidades para facilitar o desenho.

## Correções manuais de CTO

Se um KML/KMZ de correção contiver posições de CTO, essas posições são preservadas e os HPs são redistribuídos entre elas respeitando 16 HP por CTO.

Se as CTOs manuais forem insuficientes, o posicionamento é interrompido com erro claro. Exemplo:

```text
33 HP
2 CTOs manuais
capacidade = 2 × 16 = 32 HP

Resultado: erro de capacidade; o projeto exige pelo menos mais uma CTO.
```

Se o arquivo manual possuir menos CTOs que o planejamento com reserva, mas ainda comportar todos os HP reais, o sistema registra um alerta de perda da reserva planejada.

## IDs internos

CTOs, PONs e CEOs agora recebem IDs internos únicos:

```text
CTO_0001
PON_0001
CEO_0001
```

Esses IDs são usados pela topologia, independentemente do nome visual mostrado no KML. Isso corrige o problema em que várias CEOs exibidas apenas como `CEO` colapsavam no grafo do backbone.

A opção `nomear_cto_ceo_automaticamente` continua controlando apenas o texto visual.

## Roteamento e topologia física

A Fase 6 move a lógica de grafo para `src/roteamento.py`. As arestas do grafo passam a ter peso em **metros**, calculado por Haversine, e a busca do nó viário mais próximo usa `STRtree` em vez de percorrer todos os nós a cada rota.

Cada tentativa de rota retorna um dos estados:

```text
OK
SEM_MALHA
SEM_CAMINHO
FORA_DA_MALHA
```

Somente `OK` vira cabo normal. Uma falha de roteamento não é mais convertida silenciosamente em uma linha reta. Quando necessário, o sistema cria:

```text
<projeto> - Excecoes de Roteamento.kml
```

As linhas vermelhas desse arquivo são **referências visuais de pendência** e não representam rotas válidas. O mesmo detalhe é registrado em `Alocacao FTTH.json`.

### OLT física

A posição da OLT é opcional. Para incluí-la no projeto, informe latitude e longitude juntas:

```json
{
  "equipamentos": {
    "nome_olt_padrao": "N70",
    "olt": {
      "latitude": -2.5000000,
      "longitude": -44.3000000
    }
  }
}
```

Quando configurada, a OLT:

- entra no bbox usado para baixar a malha viária;
- é alinhada à rua dentro de `distancia_maxima_snap_metros`;
- é exportada em `<projeto> - OLT.kml`;
- participa da árvore de feeder/backbone com as CEOs.

Se as coordenadas permanecerem `null`, o projeto continua funcionando e o backbone é calculado apenas entre CEOs, com aviso no log.

`margem_bbox_roteamento_metros` acrescenta uma margem ao bbox consultado no Overpass e é especialmente útil quando a OLT está fora da área dos HPs.

## KML/KMZ e entrada

Coloque a área do projeto em `data/input/`. KML e KMZ são suportados.

Quando houver múltiplos arquivos, defina explicitamente:

```json
{
  "entrada": {
    "arquivo_projeto": "Projeto.kmz",
    "arquivo_correcoes": "Projeto Corrigido.kml"
  }
}
```

O parser suporta múltiplos polígonos, `MultiGeometry` e buracos internos (`innerBoundaryIs`).

## Cache

O cache das edificações continua validado por:

- versão;
- expiração;
- hash da geometria;
- compatibilidade do formato.

A atualização da Fase 5 para a Fase 6 **não exige baixar novamente as edificações** se o cache atual ainda for válido. A mudança desta fase atua no roteamento e na topologia física; o dimensionamento de 16 HP/CTO permanece o mesmo.

## Fluxo atual

1. Resolve o KML/KMZ principal.
2. Extrai e valida os polígonos.
3. Reutiliza ou atualiza o cache Overture.
4. Calcula HP.
5. Calcula HC esperado pela penetração.
6. Dimensiona CTOs por cobertura física de 16 HP.
7. Calcula PONs e CEOs mínimas.
8. Executa clusterização capacitada HP → CTO.
9. Executa agrupamento capacitado CTO → PON.
10. Executa agrupamento capacitado PON → CEO.
11. Valida todas as atribuições.
12. Expande o bbox de roteamento para incluir a OLT física, quando configurada.
13. Faz snap dos elementos para a malha viária dentro do limite configurado.
14. Constrói grafo viário com pesos em metros e índice espacial.
15. Ordena o cabeamento por PON e calcula rotas com status explícito.
16. Insere a OLT na árvore de feeder/backbone, quando configurada.
17. Exporta cabos válidos, exceções de roteamento e relatório de alocação.

## Arquivos de saída

Entre os arquivos gerados:

```text
<projeto>_dados_calculados.json
<projeto>_casas_cache.json
<projeto> - Residências HP.kml
<projeto> - Caixas de Terminação Óptica (CTO).kml
<projeto> - Caixas de Emenda Óptica (CEO).kml
<projeto> - Cabos de Distribuição.kml
<projeto> - OLT.kml                         # quando configurada
<projeto> - Cabos de Backbone (OLT-CEOs).kml
<projeto> - Excecoes de Roteamento.kml      # quando houver pendências
<projeto> - Alocacao FTTH.json
```

O arquivo `Alocacao FTTH.json` registra a auditoria capacitada e, na Fase 6, também informa a OLT, bbox consultado, quantidade de nós da malha, cabos válidos e todas as exceções de roteamento.

## Migração para a Fase 6

Partindo da Fase 5, mantenha as regras de CTO e acrescente:

```json
"margem_bbox_roteamento_metros": 150
```

e, dentro de `equipamentos`:

```json
"olt": {
  "latitude": null,
  "longitude": null
}
```

Informe as coordenadas reais da OLT quando quiser ativar o feeder físico OLT → CEOs. Latitude e longitude devem ser preenchidas juntas.

## Histórico: migração da Fase 4 para a Fase 5

Remova os campos antigos:

```json
"dimensionamento_cto_por": "hc",
"capacidade_splitter_cto": 8
```

E use:

```json
"capacidade_hp_por_cto": 16,
"splitter_cto_inicial": 8,
"splitter_cto_expansao": 16
```

Depois execute novamente:

```bash
python -m src.contagem_hp
```

Isso regenera `<projeto>_dados_calculados.json` com a regra física correta. Em seguida execute o posicionamento.

## Testes

Execute:

```bash
python -m pytest -q
```

A suíte da Fase 6 possui **62 testes** cobrindo configuração, dimensionamento 16 HP/CTO, splitters 1x8/1x16, clusterização capacitada, cache, KML/KMZ, Overpass/Overture, snap, roteamento em metros, malhas desconectadas, limites de conexão e OLT física.

## Limitações ainda conhecidas

- a clusterização capacitada ainda otimiza os agrupamentos principalmente por proximidade geográfica, não pelo custo integral da malha viária;
- a malha OSM representa ruas, não necessariamente postes, dutos ou infraestrutura efetivamente disponível para lançamento;
- a árvore de backbone minimiza metragem de rota, mas ainda não modela redundância, anéis ou caminhos protegidos;
- orçamento óptico, fibras por cabo, reserva técnica de cabo/fibra, emendas e BOM ainda não estão modelados;
- exceções de roteamento exigem revisão de engenharia antes da liberação do projeto.

A próxima fase deve concentrar-se em **validação operacional e relatório de engenharia**, consolidando conectividade, metragens, exceções, capacidades e materiais para revisão final.
