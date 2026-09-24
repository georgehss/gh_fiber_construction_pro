from shapely.geometry import LineString, Point

from src.posicionamento import (
    COR_CABO_PADRAO_KML,
    alinhar_ponto_na_rua,
    criar_sessao_com_retry,
    montar_consulta_overpass,
    obter_cor_cabo_pon,
    obter_paleta_pon,
)


def config_api(retry=5, backoff=1.0):
    return {
        "api": {
            "overpass_timeout_segundos": 60,
            "overture_timeout_segundos": 60,
            "overpass_retry_max": retry,
            "overpass_backoff_factor": backoff,
        }
    }


def test_retry_overpass_respeita_config():
    sessao = criar_sessao_com_retry(config_api(retry=7, backoff=2.5))
    retries = sessao.get_adapter("https://").max_retries

    assert retries.total == 7
    assert retries.backoff_factor == 2.5


def test_query_overpass_respeita_timeout_configurado():
    query = montar_consulta_overpass((-44.4, -2.6, -44.2, -2.4), 23)

    assert "[timeout:23]" in query
    assert "[timeout:60]" not in query


def test_snap_ocorre_quando_dentro_do_limite():
    # Aproximadamente 11 m da via no equador.
    via = LineString([(0.0, -0.001), (0.0, 0.001)])
    ponto = Point(0.0001, 0.0)

    lon, lat = alinhar_ponto_na_rua(ponto, via, distancia_maxima_metros=20)

    assert abs(lon) < 1e-12
    assert abs(lat) < 1e-12


def test_snap_e_ignorado_quando_excede_limite():
    # Aproximadamente 111 m da via no equador.
    via = LineString([(0.0, -0.001), (0.0, 0.001)])
    ponto = Point(0.001, 0.0)

    lon, lat = alinhar_ponto_na_rua(ponto, via, distancia_maxima_metros=50)

    assert lon == ponto.x
    assert lat == ponto.y


def test_cor_de_cabo_respeita_opcao_desativada():
    assert obter_cor_cabo_pon(1, False) == COR_CABO_PADRAO_KML
    assert obter_cor_cabo_pon(4, False) == COR_CABO_PADRAO_KML


def test_cor_de_cabo_respeita_paleta_quando_ativada():
    _, cor_pon_2 = obter_paleta_pon(2)
    assert obter_cor_cabo_pon(2, True) == cor_pon_2


def test_olt_fisica_e_convertida_para_lon_lat():
    from src.posicionamento import obter_olt_fisica

    config = {
        "equipamentos": {
            "nome_olt_padrao": "N70",
            "olt": {"latitude": -2.5, "longitude": -44.3},
        }
    }
    olt = obter_olt_fisica(config)

    assert olt["id"] == "OLT_0001"
    assert olt["nome"] == "N70"
    assert olt["coords_brutas"] == (-44.3, -2.5)
