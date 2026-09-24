import json
from datetime import datetime, timedelta, timezone

from shapely.geometry import Polygon

from src.cache_manager import carregar_cache_casas, caminho_cache_casas, salvar_cache_casas


def config_cache():
    return {"cache": {"versao": "2.0", "expirar_dias": 30}}


def poligonos(offset=0.0):
    poly = Polygon(
        [
            (0 + offset, 0),
            (1 + offset, 0),
            (1 + offset, 1),
            (0 + offset, 1),
            (0 + offset, 0),
        ]
    )
    return [{"nome": "Setor", "geom": poly, "bbox": poly.bounds}]


def test_cache_valido_e_reutilizado(tmp_path):
    pontos = [[0.2, 0.2], [0.8, 0.8]]
    resumo = [{"indice": 1, "nome": "Setor", "bbox": [0, 0, 1, 1], "hp_detectados": 2}]
    salvar_cache_casas(tmp_path, "Projeto", poligonos(), pontos, resumo, config_cache())

    carregado = carregar_cache_casas(tmp_path, "Projeto", poligonos(), config_cache())

    assert carregado == (pontos, resumo)


def test_cache_e_invalidado_quando_geometria_muda(tmp_path):
    salvar_cache_casas(tmp_path, "Projeto", poligonos(), [[0.2, 0.2]], [], config_cache())

    assert carregar_cache_casas(
        tmp_path, "Projeto", poligonos(offset=2.0), config_cache()
    ) is None


def test_cache_expirado_nao_e_reutilizado(tmp_path):
    salvar_cache_casas(tmp_path, "Projeto", poligonos(), [[0.2, 0.2]], [], config_cache())
    caminho = caminho_cache_casas(tmp_path, "Projeto")
    payload = json.loads(caminho.read_text(encoding="utf-8"))
    payload["metadata"]["expires_at"] = (
        datetime.now(timezone.utc) - timedelta(minutes=1)
    ).isoformat()
    caminho.write_text(json.dumps(payload), encoding="utf-8")

    assert carregar_cache_casas(tmp_path, "Projeto", poligonos(), config_cache()) is None


def test_cache_legado_lista_e_invalidado(tmp_path):
    caminho = caminho_cache_casas(tmp_path, "Projeto")
    caminho.write_text(json.dumps([[0.2, 0.2]]), encoding="utf-8")

    assert carregar_cache_casas(tmp_path, "Projeto", poligonos(), config_cache()) is None
