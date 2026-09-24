import copy

import pytest

from src.dimensionamento import (
    DimensionamentoError,
    calcular_dimensionamento_ftth,
    recalcular_hierarquia_por_ctos,
    validar_dimensionamento,
)


@pytest.fixture
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


def test_cto_e_dimensionada_por_16_hp(config_base):
    resultado = calcular_dimensionamento_ftth(100, config_base)

    assert resultado["hp"] == 100
    assert resultado["hc"] == 50
    assert resultado["ctos"] == 7
    assert resultado["pons"] == 1
    assert resultado["ceos"] == 1
    detalhe = resultado["dimensionamento"]
    assert detalhe["regra_cto"] == "cobertura_hp"
    assert detalhe["capacidade_hp_por_cto"] == 16
    assert detalhe["capacidade_hp_instalada"] == 112
    assert detalhe["capacidade_hc_inicial"] == 56
    assert detalhe["capacidade_hc_expansao"] == 112


def test_penetracao_nao_altera_quantidade_fisica_de_ctos(config_base):
    baixa = copy.deepcopy(config_base)
    alta = copy.deepcopy(config_base)
    baixa["engenharia"]["penetracao_estimada"] = 0.2
    alta["engenharia"]["penetracao_estimada"] = 0.8

    r_baixa = calcular_dimensionamento_ftth(100, baixa)
    r_alta = calcular_dimensionamento_ftth(100, alta)

    assert r_baixa["ctos"] == r_alta["ctos"] == 7
    assert r_baixa["hc"] == 20
    assert r_alta["hc"] == 80
    assert r_alta["dimensionamento"]["deficit_hc_inicial"] == 24
    assert r_alta["dimensionamento"]["expansao_splitter_necessaria_no_cenario_estimado"]


def test_17_hp_exigem_duas_ctos(config_base):
    resultado = calcular_dimensionamento_ftth(17, config_base)
    assert resultado["ctos"] == 2
    assert resultado["dimensionamento"]["capacidade_hp_instalada"] == 32


def test_reserva_e_aplicada_sobre_hp(config_base):
    config = copy.deepcopy(config_base)
    config["engenharia"]["reserva_capacidade_percentual"] = 0.20

    resultado = calcular_dimensionamento_ftth(100, config)
    detalhe = resultado["dimensionamento"]

    assert detalhe["reserva_hp"] == 20
    assert detalhe["demanda_hp_planejada"] == 120
    assert resultado["ctos"] == 8
    assert detalhe["capacidade_hp_instalada"] == 128
    assert detalhe["folga_hp_instalada"] == 8


def test_arredondamento_da_reserva_e_conservador(config_base):
    config = copy.deepcopy(config_base)
    config["engenharia"]["reserva_capacidade_percentual"] = 0.10

    resultado = calcular_dimensionamento_ftth(17, config)

    assert resultado["hc"] == 9
    assert resultado["dimensionamento"]["demanda_hp_planejada"] == 19
    assert resultado["ctos"] == 2


def test_zero_nao_cria_elementos(config_base):
    resultado = calcular_dimensionamento_ftth(0, config_base)

    assert resultado["hc"] == 0
    assert resultado["ctos"] == 0
    assert resultado["pons"] == 0
    assert resultado["ceos"] == 0
    assert resultado["dimensionamento"]["capacidade_hp_instalada"] == 0


def test_hp_negativo_e_rejeitado(config_base):
    with pytest.raises(DimensionamentoError, match="não pode ser negativo"):
        calcular_dimensionamento_ftth(-1, config_base)


def test_recalculo_hierarquia_apos_correcao_manual(config_base):
    assert recalcular_hierarquia_por_ctos(17, config_base) == {
        "ctos": 17,
        "pons": 3,
        "ceos": 2,
    }


def test_invariante_detecta_capacidade_cto_insuficiente(config_base):
    resultado = calcular_dimensionamento_ftth(100, config_base)
    resultado["ctos"] = 6

    with pytest.raises(DimensionamentoError, match="CTO insuficiente"):
        validar_dimensionamento(resultado)


def test_invariante_exige_expansao_capaz_de_atender_16_hp(config_base):
    resultado = calcular_dimensionamento_ftth(100, config_base)
    resultado["dimensionamento"]["splitter_cto_expansao"] = 8

    with pytest.raises(DimensionamentoError, match="todos os HP"):
        validar_dimensionamento(resultado)
