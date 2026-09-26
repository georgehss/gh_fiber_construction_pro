# 🚀 GH Fiber Construction Pro

**Ferramenta profissional de pré-planejamento FTTH** para estimativa de Home Passed (HP), dimensionamento de CTO/PON/CEO, posicionamento geoespacial, roteamento físico e análise de orçamento óptico.

> **Status:** Fase 9 — Orçamento Óptico e Topologia de Backbone em Anel  
> **Versionamento Config:** 9.0  
> **Compatibilidade:** Python 3.9+

---

## 📋 Sumário Executivo

O GH Fiber Construction Pro é um **simulador integrado de redes FTTH** que automatiza todo o pipeline de planejamento:

1. **Contagem de HP** — Detecta edificações em polígono via Overture Maps
2. **Dimensionamento** — Calcula CTOs (16 HP), PONs (8 CTOs), CEOs (2 PONs)
3. **Posicionamento** — K-Means geoespacial com validação capacitada
4. **Roteamento** — Malha viária OSM com pesos em metros e índice espacial STRtree
5. **Backbone** — Minimum Spanning Tree com opção de topologia em anel
6. **Orçamento Óptico** — Análise BOM, perdas de sinal, margens de segurança
7. **Exportação** — KML/JSON para visualização em Google Earth e auditoria

---

## 🏗️ Arquitetura

```
src/
├── config.py                    # Carregamento e validação de config.json
├── config_validator.py          # Esquema de validação com pydantic
├── geo_io.py                    # I/O de geometrias (KML/KMZ)
├── cache_manager.py             # Cache com expiração para edificações
├── contagem_hp.py               # Pipeline de contagem de Home Passed
├── dimensionamento.py           # Cálculo de CTO/PON/CEO
├── clusterizacao.py             # K-Means capacitado e atribuição hierárquica
├── roteamento.py                # Grafo viário, snap e busca de rotas
├── posicionamento.py            # Orquestrador principal do posicionamento
├── orcamento_optico.py          # 🆕 BOM, perdas ópticas e margens
├── logger_config.py             # Logging estruturado
└── __main__.py                  # Menu interativo

data/
├── input/                       # KML/KMZ do projeto
└── output/                      # Resultados (KML, JSON)

tests/
├── test_*.py                    # Suite de 62+ testes unitários
└── validate_config.py           # Validação de config.json
```

---

## ⚙️ Instalação

### Linux / macOS

```bash
bash install.sh
source venv/bin/activate
```

### Windows (com venv ativo)

```powershell
python -m pip install -r requirements.txt
```

### Dependências Principais

```
shapely>=2.0.0              # Geometrias
networkx>=3.0.0             # Grafos e rotas
scikit-learn>=1.3.0         # K-Means
overturemaps>=0.1.0         # Edificações
pyarrow>=10.0.0             # Dados geoespaciais
```

---

## 🎯 Uso Rápido

### Menu Interativo

```bash
python -m src
```

**Opções:**
- `[1]` — Validar `config.json`
- `[2]` — Executar Contagem de HP
- `[3]` — Posicionar Elementos (CTO/PON/CEO)
- `[4]` — Fluxo Completo (Contagem + Posicionamento + Orçamento)
- `[0]` — Sair

### Pipeline Modular

```bash
# Apenas contagem
python -m src.contagem_hp

# Apenas posicionamento (requer dados calculados da contagem)
python -m src.posicionamento

# Apenas orçamento óptico (requer alocação FTTH)
python -m src.orcamento_optico

# Validar configuração
python tests/validate_config.py
```

---

## 📐 Regra de Engenharia

### Dimensionamento de CTO

Cada CTO cobre **fisicamente** até **16 Home Passed** independentemente da penetração:

```
Cobertura física máxima por CTO:     16 HP
Splitter inicial (50% penetração):    1×8
Splitter de expansão (100%):          1×16

Fórmula de CTOs necessárias:
  CTOs = ⌈(HP_reais × (1 + reserva_percentual)) / 16⌉

Exemplo com 100 HP e 20% de reserva:
  HP planejados = 100 × 1.20 = 120
  CTOs = ⌈120 / 16⌉ = 8
  Cobertura = 8 × 16 = 128 HP
```

### Hierarquia de Capacidade

```
Home Passed (HP)
    ↓ K-Means capacitado (máx 16 HP/CTO)
Caixa de Terminação Óptica (CTO)
    ↓ Agrupamento capacitado (máx 8 CTO/PON)
Ponto de Emenda Óptica (PON)
    ↓ Agrupamento capacitado (máx 2 PON/CEO)
Caixa de Emenda de Óptica (CEO)
    ↓ Minimum Spanning Tree
Optical Line Terminal (OLT) — opcional
```

---

## 🔧 Configuração (config.json 9.0)

### Seção: Engenharia

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
    "margem_bbox_roteamento_metros": 150,
    "fisica": {
      "margem_flecha_percentual": 0.03,
      "reserva_tecnica_cto_metros": 10.0,
      "reserva_tecnica_ceo_metros": 30.0,
      "reserva_tecnica_olt_metros": 50.0
    },
    "topologia_backbone": {
      "modo": "anel",
      "permitir_rotas_parcialmente_disjuntas": true
    }
  }
}
```

### Seção: Orçamento Óptico (🆕 Fase 9)

```json
{
  "orcamento_optico": {
    "potencia_saida_olt_dbm": 4.5,
    "sensibilidade_minima_onu_dbm": -27.0,
    "margem_seguranca_db": 2.0,
    "perdas": {
      "fibra_por_km": 0.25,
      "fusao": 0.1,
      "conector": 0.5,
      "splitter_1x8": 10.5,
      "splitter_1x16": 13.5
    }
  }
}
```

### Seção: Equipamentos

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

Deixe `latitude` e `longitude` como `null` para desabilitar feeder físico OLT → CEOs.

---

## 📊 Fluxo Completo (Fase 9)

1. ✅ Valida `config.json` (schema pydantic)
2. ✅ Carrega KML/KMZ do projeto
3. ✅ Reutiliza ou atualiza cache de edificações (Overture + OSM)
4. ✅ **Contagem de HP** — Detecção e validação
5. ✅ **Dimensionamento** — CTOs, PONs, CEOs calculadas
6. ✅ **Clusterização** — Atribuição capacitada HP → CTO → PON → CEO
7. ✅ **Roteamento** — Snap à malha viária e cálculo de rotas com status
8. ✅ **Cabeamento** — Daisy-chain PON + derivações automáticas
9. ✅ **Backbone** — MST (ou topologia em anel) OLT ↔ CEOs
10. ✅ **Orçamento Óptico** (🆕) — BOM, perdas, margens, ativos por CEO/CTO
11. ✅ **Exportação** — KML colorido + JSON de auditoria

---

## 📁 Arquivos de Saída

```
data/output/
├── <projeto>_dados_calculados.json          # Métricas de dimensionamento
├── <projeto>_casas_cache.json               # Cache de edificações
├── <projeto> - Residências HP.kml           # Pontos de casas
├── <projeto> - Caixas de Terminação Óptica (CTO).kml
├── <projeto> - Caixas de Emenda Óptica (CEO).kml
├── <projeto> - Cabos de Distribuição.kml    # PON → CTO
├── <projeto> - OLT.kml                      # Quando configurada
├── <projeto> - Cabos de Backbone (OLT-CEOs).kml
├── <projeto> - Excecoes de Roteamento.kml   # Pendências de rota
└── <projeto> - Alocacao FTTH.json           # Auditoria completa
```

### Conteúdo de "Alocacao FTTH.json"

```json
{
  "projeto": "nome_do_projeto",
  "versao_config": "9.0",
  "hp_detectados": 100,
  "hp_planejados": 100,
  "ctos_necessarias": 7,
  "pons_necessarias": 1,
  "ceos_necessarias": 1,
  "olt": {
    "nome": "N70",
    "latitude": -2.5,
    "longitude": -44.3,
    "incluida_no_backbone": true
  },
  "cabos_validos": 14,
  "cabos_com_excecao": 2,
  "metragem_total_m": 8542.3,
  "ctos_alocadas": [
    {
      "id": "CTO_0001",
      "nome": "CTO_Centro",
      "latitude": -2.4912,
      "longitude": -44.2856,
      "hp_atribuidos": 16,
      "hp_estimados_50_pct": 8,
      "pon_atribuida": "PON_0001"
    }
  ],
  "cabos": [
    {
      "id": "CABO_0001",
      "tipo": "distribuicao",
      "origem": "CTO_0001",
      "destino": "CASA_100",
      "status": "OK",
      "distancia_m": 42.5
    },
    {
      "id": "CABO_0002",
      "tipo": "derivacao",
      "origem": "CABO_0001",
      "destino": "CASA_101",
      "status": "OK",
      "distancia_m": 15.3
    }
  ],
  "exceções_roteamento": [
    {
      "cabos": ["CABO_0015"],
      "motivo": "SEM_CAMINHO",
      "detalhes": "Nenhum caminho encontrado na malha viária entre CTO_0007 e CASA_087"
    }
  ]
}
```

---

## 🧪 Testes

### Executar Suite Completa

```bash
python -m pytest -q
```

**Cobertura:** 62+ testes cobrindo:
- ✅ Validação de configuração (pydantic schema)
- ✅ Dimensionamento 16 HP/CTO com reserva
- ✅ Clusterização capacitada K-Means
- ✅ Roteamento em grafo viário
- ✅ Cache com expiração
- ✅ Parsing KML/KMZ e geometrias complexas
- ✅ Orçamento óptico e BOM
- ✅ Topologia de anel e MST
- ✅ Manejo de exceções e edge cases

### Teste Específico

```bash
python -m pytest tests/test_dimensionamento.py -v
python -m pytest tests/test_clusterizacao.py -v
python -m pytest tests/test_orcamento_optico.py -v
```

---

## 🔄 Migração de Versões

### De Fase 8 para Fase 9

Atualize `config.json`:

```json
{
  "versao": "9.0",
  "orcamento_optico": {
    "potencia_saida_olt_dbm": 4.5,
    "sensibilidade_minima_onu_dbm": -27.0,
    "margem_seguranca_db": 2.0,
    "perdas": {
      "fibra_por_km": 0.25,
      "fusao": 0.1,
      "conector": 0.5,
      "splitter_1x8": 10.5,
      "splitter_1x16": 13.5
    }
  },
  "engenharia": {
    "topologia_backbone": {
      "modo": "anel",
      "permitir_rotas_parcialmente_disjuntas": true
    }
  }
}
```

Reexecute a contagem para gerar `_dados_calculados.json` compatível:

```bash
python -m src.contagem_hp
```

### De Fase 6 para Fase 8

Adicione ao `engenharia`:

```json
"topologia_backbone": {
  "modo": "anel",
  "permitir_rotas_parcialmente_disjuntas": true
}
```

---

## 🆕 Novidades Fase 9

| Recurso | Descrição |
|---------|-----------|
| **Orçamento Óptico** | Cálculo de BOM por CTO/CEO, perdas totais, margens de segurança |
| **Topologia em Anel** | Backbone pode ser configurado como anel para redundância |
| **Rotas Parcialmente Disjuntas** | Permite caminhos alternativos em caso de falha |
| **Config 9.0** | Schema expandido com validação pydantic |
| **Auditoria Óptica** | Relatório JSON com assinatura óptica por nó |

---

## 🐛 Limitações Conhecidas

- ❌ Clusterização ainda otimiza principalmente por proximidade geográfica, não pelo custo integral da rota
- ❌ Malha OSM representa ruas, não necessariamente postes ou infraestrutura real disponível
- ❌ Backbone não modela ainda falha-over automática ou proteção de anéis duplos
- ❌ Orçamento óptico não computa fibras por cabo nem BOM de hardware (OLT, ONU, PSU)
- ❌ Exceções de roteamento exigem revisão manual antes de liberação

---

## 📈 Roadmap Futuro

### Fase 10 (Próxima)
- [ ] Validação operacional com dados reais de campo
- [ ] Hardware BOM (OLT, ONU, PSU, reatores)
- [ ] Redundância de fibra (single-mode vs multi-mode)
- [ ] Traçado real de postes (GIS integrado)

### Fase 11+
- [ ] Simulação de falhas e convergência
- [ ] Otimização de custo de rota vs capacidade
- [ ] API REST para integração
- [ ] Dashboard web com visualização real-time

---

## 📞 Suporte

Para dúvidas, erros ou melhorias:

1. Valide `config.json`: `python tests/validate_config.py`
2. Verifique logs: `data/output/app.log`
3. Execute testes: `python -m pytest -v`
4. Revise `Alocacao FTTH.json` para exceções de roteamento

---

## 📝 Licença

Propriedade da GH Fiber. Uso interno.

---

**Última atualização:** Setembro 2026  
**Versão Config:** 9.0  
**Status:** Production-Ready