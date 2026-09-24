import json

from src.config import carregar_config
from tests.test_config_validator import config_valida


def test_loader_centralizado_usa_validador(tmp_path):
    config = config_valida()
    caminho = tmp_path / "config.json"
    caminho.write_text(json.dumps(config), encoding="utf-8")
    assert carregar_config(caminho) == config
