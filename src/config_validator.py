# src/config_validator.py
import json
from pathlib import Path
from typing import Dict, Any

class ConfigValidator:
    """Valida arquivo config.json"""

    REGRAS = {
        'engenharia.penetracao_estimada': (float, lambda x: 0 < x <= 1),
        'engenharia.capacidade_splitter_cto': (int, lambda x: x > 0),
        'engenharia.ctos_por_pon': (int, lambda x: x > 0),
        'engenharia.pons_por_ceo': (int, lambda x: x > 0),
        'api.overpass_timeout_segundos': (int, lambda x: x > 0),
    }

    @staticmethod
    def validar(config_path: Path) -> Dict[str, Any]:
        """
        Carrega e valida config.json

        Raises:
            ValueError: Se config for inválida
            FileNotFoundError: Se arquivo não existir
        """
        if not config_path.exists():
            raise FileNotFoundError(f"Config não encontrada: {config_path}")

        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(f"JSON inválido em {config_path}: {e}")

        # Validar cada regra
        for campo, (tipo_esperado, validador) in ConfigValidator.REGRAS.items():
            partes = campo.split('.')
            valor = config

            # Navegar na estrutura aninhada
            try:
                for parte in partes[:-1]:
                    valor = valor[parte]
                valor = valor[partes[-1]]
            except (KeyError, TypeError):
                raise ValueError(f"Campo obrigatório ausente: {campo}")

            # Validar tipo
            if not isinstance(valor, tipo_esperado):
                raise ValueError(
                    f"{campo}: esperado {tipo_esperado.__name__}, "
                    f"recebido {type(valor).__name__}"
                )

            # Validar regra lógica
            if not validador(valor):
                raise ValueError(f"{campo}: valor inválido ({valor})")

        return config

# Uso:
# config = ConfigValidator.validar(BASE_DIR / "config.json")