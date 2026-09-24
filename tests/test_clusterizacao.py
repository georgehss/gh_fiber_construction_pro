import logging

import numpy as np
import pytest

from src.clusterizacao import (
    ClusterizacaoError,
    agrupar_pontos_por_capacidade,
    atribuir_pontos_a_centros_capacitado,
    clusterizar_pontos_capacitado,
    validar_alocacao_hierarquica,
)
from src.posicionamento import _criar_modelo_capacitado


def pontos_em_linha(n, passo=0.0001):
    return np.array([[i * passo, 0.0] for i in range(n)], dtype=float)


def config_base():
    return {
        "engenharia": {
            "penetracao_estimada": 0.5,
            "reserva_capacidade_percentual": 0.0,
            "capacidade_hp_por_cto": 16,
            "splitter_cto_inicial": 8,
            "splitter_cto_expansao": 16,
            "ctos_por_pon": 8,
            "pons_por_ceo": 2,
        }
    }


def test_32_hp_ficam_em_duas_ctos_de_16():
    labels, clusters = clusterizar_pontos_capacitado(pontos_em_linha(32), 2, 16)

    assert len(labels) == 32
    assert sorted(c["quantidade"] for c in clusters) == [16, 16]
    assert max(c["quantidade"] for c in clusters) <= 16


def test_33_hp_exigem_tres_ctos_sem_estouro():
    labels, clusters = clusterizar_pontos_capacitado(pontos_em_linha(33), 3, 16)

    assert len(set(labels.tolist())) == 3
    assert sum(c["quantidade"] for c in clusters) == 33
    assert max(c["quantidade"] for c in clusters) <= 16


def test_clusterizacao_rejeita_capacidade_total_insuficiente():
    with pytest.raises(ClusterizacaoError, match="não comportam"):
        clusterizar_pontos_capacitado(pontos_em_linha(33), 2, 16)


def test_centros_manuais_respeitam_limite_16_hp():
    pontos = pontos_em_linha(30)
    centros = np.array([[0.0, 0.0], [0.003, 0.0]])

    labels = atribuir_pontos_a_centros_capacitado(pontos, centros, 16)
    ocupacoes = [int(np.sum(labels == i)) for i in range(2)]

    assert sum(ocupacoes) == 30
    assert max(ocupacoes) <= 16


def test_centros_manuais_insuficientes_sao_rejeitados():
    with pytest.raises(ClusterizacaoError, match="capacidade insuficiente"):
        atribuir_pontos_a_centros_capacitado(
            pontos_em_linha(17), np.array([[0.0, 0.0]]), 16
        )


def test_17_ctos_viram_tres_pons_de_no_maximo_oito():
    _, pons = agrupar_pontos_por_capacidade(pontos_em_linha(17), 8)

    assert len(pons) == 3
    assert sum(p["quantidade"] for p in pons) == 17
    assert max(p["quantidade"] for p in pons) <= 8


def test_5_pons_viram_tres_ceos_de_no_maximo_duas():
    _, ceos = agrupar_pontos_por_capacidade(pontos_em_linha(5), 2)

    assert len(ceos) == 3
    assert max(c["quantidade"] for c in ceos) <= 2


def test_modelo_completo_garante_hp_cto_pon_ceo():
    casas = pontos_em_linha(260)
    config = config_base()
    logger = logging.getLogger("teste_clusterizacao")

    # 260 HP -> ceil(260/16)=17 CTO -> 3 PON -> 2 CEO.
    ctos, pons, ceos, validacao = _criar_modelo_capacitado(
        casas, None, 17, logger, config
    )

    assert len(ctos) == 17
    assert len(pons) == 3
    assert len(ceos) == 2
    assert validacao["hp_atribuidos"] == 260
    assert validacao["maior_ocupacao_hp_cto"] <= 16
    assert validacao["maior_ocupacao_ctos_pon"] <= 8
    assert validacao["maior_ocupacao_pons_ceo"] <= 2
    assert validacao["valido"] is True


def test_correcao_manual_com_ctos_insuficientes_falha_claramente():
    casas = pontos_em_linha(33)
    manuais = np.array([[0.0, 0.0], [0.003, 0.0]])

    with pytest.raises(ClusterizacaoError, match="correção manual insuficiente"):
        _criar_modelo_capacitado(
            casas,
            manuais,
            3,
            logging.getLogger("teste_manual"),
            config_base(),
        )


def test_validador_detecta_hp_duplicado():
    ctos = [
        {"id": "CTO_1", "hp_indices": [0, 1]},
        {"id": "CTO_2", "hp_indices": [1, 2]},
    ]
    pons = [{"id": "PON_1", "cto_ids": ["CTO_1", "CTO_2"]}]
    ceos = [{"id": "CEO_1", "pon_ids": ["PON_1"]}]

    with pytest.raises(ClusterizacaoError, match="mais de uma CTO"):
        validar_alocacao_hierarquica(
            quantidade_hps=4,
            ctos=ctos,
            pons=pons,
            ceos=ceos,
            capacidade_hp_por_cto=16,
            ctos_por_pon=8,
            pons_por_ceo=2,
        )
