import pytest

from src.contagem_hp import calcular_ftth, criar_reader_overture


@pytest.fixture
def config_base():
    return {
        "engenharia": {
            "penetracao_estimada": 0.50,
            "reserva_capacidade_percentual": 0.0,
            "capacidade_hp_por_cto": 16,
            "splitter_cto_inicial": 8,
            "splitter_cto_expansao": 16,
            "ctos_por_pon": 8,
            "pons_por_ceo": 2,
        }
    }


def test_calcular_ftth_basico(config_base):
    resultado = calcular_ftth(100, config_base)

    assert {k: resultado[k] for k in ("hp", "hc", "ctos", "pons", "ceos")} == {
        "hp": 100,
        "hc": 50,
        "ctos": 7,
        "pons": 1,
        "ceos": 1,
    }


def test_calcular_ftth_grande(config_base):
    resultado = calcular_ftth(1000, config_base)

    assert {k: resultado[k] for k in ("hp", "hc", "ctos", "pons", "ceos")} == {
        "hp": 1000,
        "hc": 500,
        "ctos": 63,
        "pons": 8,
        "ceos": 4,
    }


def test_calcular_ftth_zero(config_base):
    resultado = calcular_ftth(0, config_base)

    assert {k: resultado[k] for k in ("hp", "hc", "ctos", "pons", "ceos")} == {
        "hp": 0,
        "hc": 0,
        "ctos": 0,
        "pons": 0,
        "ceos": 0,
    }


class _OvertureComTimeout:
    def __init__(self):
        self.chamada = None

    def record_batch_reader(
        self,
        overture_type,
        bbox=None,
        connect_timeout=None,
        request_timeout=None,
    ):
        self.chamada = {
            "overture_type": overture_type,
            "bbox": bbox,
            "connect_timeout": connect_timeout,
            "request_timeout": request_timeout,
        }
        return object()


class _OvertureSemTimeout:
    def __init__(self):
        self.chamada = None

    def record_batch_reader(self, overture_type, bbox=None):
        self.chamada = {"overture_type": overture_type, "bbox": bbox}
        return object()


def test_overture_timeout_aplicado_quando_api_suporta():
    overture = _OvertureComTimeout()
    bbox = (-44.4, -2.6, -44.2, -2.4)

    criar_reader_overture(overture, bbox, 37)

    assert overture.chamada == {
        "overture_type": "building",
        "bbox": bbox,
        "connect_timeout": 37,
        "request_timeout": 37,
    }


def test_overture_mantem_compatibilidade_sem_parametros_timeout():
    overture = _OvertureSemTimeout()
    bbox = (-44.4, -2.6, -44.2, -2.4)

    criar_reader_overture(overture, bbox, 37)

    assert overture.chamada == {"overture_type": "building", "bbox": bbox}
