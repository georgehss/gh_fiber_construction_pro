import json

import pytest

from src.config_validator import ConfigValidator


def config_valida():
    return {
        "versao": "6.0",
        "entrada": {"arquivo_projeto": None, "arquivo_correcoes": None},
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
        },
        "equipamentos": {
            "nome_olt_padrao": "N70",
            "olt": {"latitude": None, "longitude": None},
        },
        "opcoes_visuais_e_nomes": {
            "nomear_cto_ceo_automaticamente": False,
            "colorir_cto_por_pon": True,
            "colorir_cabos_por_pon": True,
        },
        "api": {
            "overpass_timeout_segundos": 60,
            "overture_timeout_segundos": 60,
            "overpass_retry_max": 5,
            "overpass_backoff_factor": 1.0,
        },
        "cache": {"versao": "2.0", "expirar_dias": 30},
    }


def gravar(tmp_path, config):
    caminho = tmp_path / "config.json"
    caminho.write_text(json.dumps(config), encoding="utf-8")
    return caminho


def test_config_atual_e_valida(tmp_path):
    config = config_valida()
    assert ConfigValidator.validar(gravar(tmp_path, config)) == config


def test_rejeita_campo_obrigatorio_ausente(tmp_path):
    config = config_valida()
    del config["api"]["overpass_retry_max"]
    with pytest.raises(ValueError, match="api.overpass_retry_max"):
        ConfigValidator.validar(gravar(tmp_path, config))


def test_rejeita_bool_em_campo_inteiro(tmp_path):
    config = config_valida()
    config["engenharia"]["ctos_por_pon"] = True
    with pytest.raises(ValueError, match="engenharia.ctos_por_pon"):
        ConfigValidator.validar(gravar(tmp_path, config))


def test_aceita_penetracao_inteira_um(tmp_path):
    config = config_valida()
    config["engenharia"]["penetracao_estimada"] = 1
    validado = ConfigValidator.validar(gravar(tmp_path, config))
    assert validado["engenharia"]["penetracao_estimada"] == 1


def test_rejeita_distancia_entre_ctos_zero(tmp_path):
    config = config_valida()
    config["engenharia"]["distancia_maxima_entre_ctos_metros"] = 0
    with pytest.raises(ValueError, match="engenharia.distancia_maxima_entre_ctos_metros"):
        ConfigValidator.validar(gravar(tmp_path, config))


def test_rejeita_backoff_negativo(tmp_path):
    config = config_valida()
    config["api"]["overpass_backoff_factor"] = -0.1
    with pytest.raises(ValueError, match="api.overpass_backoff_factor"):
        ConfigValidator.validar(gravar(tmp_path, config))


def test_rejeita_reserva_maior_que_cem_porcento(tmp_path):
    config = config_valida()
    config["engenharia"]["reserva_capacidade_percentual"] = 1.01
    with pytest.raises(ValueError, match="engenharia.reserva_capacidade_percentual"):
        ConfigValidator.validar(gravar(tmp_path, config))


def test_rejeita_splitter_inicial_maior_que_expansao(tmp_path):
    config = config_valida()
    config["engenharia"]["splitter_cto_inicial"] = 16
    config["engenharia"]["splitter_cto_expansao"] = 8
    with pytest.raises(ValueError, match="splitter_cto_inicial"):
        ConfigValidator.validar(gravar(tmp_path, config))


def test_rejeita_expansao_menor_que_cobertura_hp(tmp_path):
    config = config_valida()
    config["engenharia"]["capacidade_hp_por_cto"] = 16
    config["engenharia"]["splitter_cto_expansao"] = 12
    with pytest.raises(ValueError, match="todos os HP"):
        ConfigValidator.validar(gravar(tmp_path, config))


def test_aceita_regra_cto_16_hp_splitter_8_16(tmp_path):
    config = config_valida()
    validado = ConfigValidator.validar(gravar(tmp_path, config))
    assert validado["engenharia"]["capacidade_hp_por_cto"] == 16
    assert validado["engenharia"]["splitter_cto_inicial"] == 8
    assert validado["engenharia"]["splitter_cto_expansao"] == 16


def test_rejeita_olt_com_apenas_latitude(tmp_path):
    config = config_valida()
    config["equipamentos"]["olt"]["latitude"] = -2.5
    with pytest.raises(ValueError, match="latitude e longitude"):
        ConfigValidator.validar(gravar(tmp_path, config))


def test_aceita_olt_com_coordenadas_validas(tmp_path):
    config = config_valida()
    config["equipamentos"]["olt"] = {"latitude": -2.5, "longitude": -44.3}
    validado = ConfigValidator.validar(gravar(tmp_path, config))
    assert validado["equipamentos"]["olt"]["latitude"] == -2.5
    assert validado["equipamentos"]["olt"]["longitude"] == -44.3


def test_rejeita_margem_bbox_negativa(tmp_path):
    config = config_valida()
    config["engenharia"]["margem_bbox_roteamento_metros"] = -1
    with pytest.raises(ValueError, match="margem_bbox_roteamento_metros"):
        ConfigValidator.validar(gravar(tmp_path, config))
