from shapely.geometry import LineString, MultiLineString

from src.roteamento import (
    ROTA_FORA_DA_MALHA,
    ROTA_OK,
    ROTA_SEM_CAMINHO,
    ROTA_SEM_MALHA,
    RoteadorViario,
    expandir_bbox_com_pontos,
)


def test_rota_valida_usa_peso_em_metros():
    via = LineString([(0.0, 0.0), (0.001, 0.0), (0.002, 0.0)])
    roteador = RoteadorViario(via)

    resultado = roteador.calcular_rota((0.0, 0.0), (0.002, 0.0), 5)

    assert resultado.status == ROTA_OK
    assert resultado.valida is True
    assert 220 <= resultado.distancia_m <= 225
    assert len(roteador) == 3


def test_malha_vazia_retorna_status_explicito_sem_linha_reta():
    resultado = RoteadorViario(None).calcular_rota((0.0, 0.0), (0.001, 0.0), 50)

    assert resultado.status == ROTA_SEM_MALHA
    assert resultado.coordenadas == []
    assert resultado.valida is False


def test_componentes_desconectados_nao_viram_linha_reta():
    malha = MultiLineString(
        [
            [(0.0, 0.0), (0.001, 0.0)],
            [(0.01, 0.0), (0.011, 0.0)],
        ]
    )
    resultado = RoteadorViario(malha).calcular_rota(
        (0.0, 0.0), (0.011, 0.0), 20
    )

    assert resultado.status == ROTA_SEM_CAMINHO
    assert resultado.coordenadas == []


def test_endpoint_fora_do_limite_da_malha_e_excecao():
    via = LineString([(0.0, -0.001), (0.0, 0.001)])
    resultado = RoteadorViario(via).calcular_rota(
        (0.001, 0.0), (0.0, 0.001), 50
    )

    assert resultado.status == ROTA_FORA_DA_MALHA
    assert resultado.coordenadas == []
    assert resultado.distancia_origem_malha_m > 100


def test_bbox_de_roteamento_inclui_olt_externa_e_margem():
    bbox = (-44.30, -2.50, -44.29, -2.49)
    expandido = expandir_bbox_com_pontos(
        bbox, [(-44.40, -2.60)], margem_metros=100
    )

    assert expandido[0] < -44.40
    assert expandido[1] < -2.60
    assert expandido[2] > -44.29
    assert expandido[3] > -2.49
