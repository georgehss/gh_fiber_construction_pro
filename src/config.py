"""Carregamento centralizado da configuração do projeto.

Todos os módulos devem obter a configuração por este módulo. A validação
continua concentrada em :class:`ConfigValidator`, enquanto este arquivo define
o caminho oficial de ``config.json`` e o ponto único de carregamento.
"""

from pathlib import Path
from typing import Any, Dict, Optional, Union

from .config_validator import ConfigValidator


BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_FILE = BASE_DIR / "config.json"


def carregar_config(config_path: Optional[Union[str, Path]] = None) -> Dict[str, Any]:
    """Carrega e valida a configuração oficial do projeto.

    Args:
        config_path: caminho alternativo, útil principalmente para testes.

    Returns:
        Dicionário de configuração já validado.
    """

    caminho = Path(config_path) if config_path is not None else CONFIG_FILE
    return ConfigValidator.validar(caminho)
