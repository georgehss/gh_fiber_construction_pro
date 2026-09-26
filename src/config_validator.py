import json
from pathlib import Path
from typing import Any, Dict, Tuple, Union

ExpectedType = Union[type, Tuple[type, ...]]

class ConfigValidator:
    """Carrega e valida o arquivo ``config.json`` do projeto."""

    REGRAS = {
        "versao": (str, lambda x: bool(x.strip())),
        "entrada.arquivo_projeto": ((str, type(None)), lambda x: x is None or bool(x.strip())),
        "entrada.arquivo_correcoes": ((str, type(None)), lambda x: x is None or bool(x.strip())),
        "entrada.arquivo_postes": ((str, type(None)), lambda x: x is None or bool(x.strip())),
        "engenharia.penetracao_estimada": ((int, float), lambda x: 0 < x <= 1),
        "engenharia.reserva_capacidade_percentual": ((int, float), lambda x: 0 <= x <= 1),
        "engenharia.capacidade_hp_por_cto": (int, lambda x: x > 0),
        "engenharia.splitter_cto_inicial": (int, lambda x: x > 0),
        "engenharia.splitter_cto_expansao": (int, lambda x: x > 0),
        "engenharia.ctos_por_pon": (int, lambda x: x > 0),
        "engenharia.pons_por_ceo": (int, lambda x: x > 0),
        "engenharia.distancia_maxima_snap_metros": ((int, float), lambda x: x >= 0),
        "engenharia.distancia_maxima_entre_ctos_metros": ((int, float), lambda x: x > 0),
        "engenharia.margem_bbox_roteamento_metros": ((int, float), lambda x: x >= 0),
        "engenharia.fisica.margem_flecha_percentual": ((int, float), lambda x: x >= 0),
        "engenharia.fisica.reserva_tecnica_cto_metros": ((int, float), lambda x: x >= 0),
        "engenharia.fisica.reserva_tecnica_ceo_metros": ((int, float), lambda x: x >= 0),
        "engenharia.fisica.reserva_tecnica_olt_metros": ((int, float), lambda x: x >= 0),
        "engenharia.topologia_backbone.modo": (str, lambda x: x in ["arvore", "anel"]),
        "engenharia.topologia_backbone.permitir_rotas_parcialmente_disjuntas": (bool, lambda x: True),
        "equipamentos.nome_olt_padrao": (str, lambda x: bool(x.strip())),
        "equipamentos.olt.latitude": ((int, float, type(None)), lambda x: x is None or -90 <= x <= 90),
        "equipamentos.olt.longitude": ((int, float, type(None)), lambda x: x is None or -180 <= x <= 180),
        "opcoes_visuais_e_nomes.nomear_cto_ceo_automaticamente": (bool, lambda x: True),
        "opcoes_visuais_e_nomes.colorir_cto_por_pon": (bool, lambda x: True),
        "opcoes_visuais_e_nomes.colorir_cabos_por_pon": (bool, lambda x: True),
        "api.overpass_timeout_segundos": (int, lambda x: x > 0),
        "api.overture_timeout_segundos": (int, lambda x: x > 0),
        "api.overpass_retry_max": (int, lambda x: x >= 0),
        "api.overpass_backoff_factor": ((int, float), lambda x: x >= 0),
        "cache.versao": (str, lambda x: bool(x.strip())),
        "cache.expirar_dias": (int, lambda x: x > 0),
        "orcamento_optico.potencia_saida_olt_dbm": ((int, float), lambda x: True),
        "orcamento_optico.sensibilidade_minima_onu_dbm": ((int, float), lambda x: x < 0),
        "orcamento_optico.margem_seguranca_db": ((int, float), lambda x: x >= 0),
        "orcamento_optico.perdas.fibra_por_km": ((int, float), lambda x: x >= 0),
        "orcamento_optico.perdas.fusao": ((int, float), lambda x: x >= 0),
        "orcamento_optico.perdas.conector": ((int, float), lambda x: x >= 0),
        "orcamento_optico.perdas.splitter_1x8": ((int, float), lambda x: x >= 0),
        "orcamento_optico.perdas.splitter_1x16": ((int, float), lambda x: x >= 0),
    }

    @staticmethod
    def _nome_tipo(tipo_esperado: ExpectedType) -> str:
        if isinstance(tipo_esperado, tuple):
            return " ou ".join(t.__name__ for t in tipo_esperado)
        return tipo_esperado.__name__

    @staticmethod
    def _tipo_valido(valor: Any, tipo_esperado: ExpectedType) -> bool:
        # Em Python, bool herda de int. Para configuração, True/False não devem
        # ser aceitos como números inteiros ou reais.
        if isinstance(valor, bool) and tipo_esperado is not bool:
            return False
        if isinstance(tipo_esperado, tuple) and isinstance(valor, bool):
            return bool in tipo_esperado
        return isinstance(valor, tipo_esperado)

    @staticmethod
    def validar(config_path: Path) -> Dict[str, Any]:
        """
        Carrega e valida ``config.json``.

        Raises:
            FileNotFoundError: se o arquivo não existir.
            ValueError: se o JSON ou algum parâmetro obrigatório for inválido.
        """
        config_path = Path(config_path)
        if not config_path.exists():
            raise FileNotFoundError(f"Config não encontrada: {config_path}")

        try:
            with config_path.open("r", encoding="utf-8") as f:
                config = json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(f"JSON inválido em {config_path}: {e}") from e

        # Injeção de defaults para retrocompatibilidade com Fases 6 e 7
        entrada = config.setdefault("entrada", {})
        if "arquivo_postes" not in entrada:
            entrada["arquivo_postes"] = None
            
        engenharia = config.setdefault("engenharia", {})
        if "fisica" not in engenharia:
            engenharia["fisica"] = {
                "margem_flecha_percentual": 0.03,
                "reserva_tecnica_cto_metros": 10.0,
                "reserva_tecnica_ceo_metros": 30.0,
                "reserva_tecnica_olt_metros": 50.0
            }
        
        if "topologia_backbone" not in engenharia:
            engenharia["topologia_backbone"] = {
                "modo": "arvore", # O comportamento original era em árvore (MST)
                "permitir_rotas_parcialmente_disjuntas": False
            }

        # Injeção de defaults para a Fase 9 (Orçamento Óptico)
        orcamento = config.setdefault("orcamento_optico", {})
        if not orcamento:
            config["orcamento_optico"] = {
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

        for campo, (tipo_esperado, validador) in ConfigValidator.REGRAS.items():
            valor: Any = config
            try:
                for parte in campo.split("."):
                    valor = valor[parte]
            except (KeyError, TypeError) as e:
                raise ValueError(f"Campo obrigatório ausente: {campo}") from e

            if not ConfigValidator._tipo_valido(valor, tipo_esperado):
                raise ValueError(
                    f"{campo}: esperado {ConfigValidator._nome_tipo(tipo_esperado)}, "
                    f"recebido {type(valor).__name__}"
                )

            if not validador(valor):
                raise ValueError(f"{campo}: valor inválido ({valor})")

        if engenharia["splitter_cto_inicial"] > engenharia["splitter_cto_expansao"]:
            raise ValueError(
                "engenharia.splitter_cto_inicial não pode superar splitter_cto_expansao"
            )
        if engenharia["splitter_cto_expansao"] < engenharia["capacidade_hp_por_cto"]:
            raise ValueError(
                "engenharia.splitter_cto_expansao deve comportar todos os HP da CTO"
            )

        olt = config["equipamentos"]["olt"]
        lat_olt = olt["latitude"]
        lon_olt = olt["longitude"]
        if (lat_olt is None) != (lon_olt is None):
            raise ValueError(
                "equipamentos.olt.latitude e longitude devem ser informadas juntas ou ambas nulas"
            )

        return config