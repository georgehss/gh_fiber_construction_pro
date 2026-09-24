"""Regras de dimensionamento físico FTTH.

A partir da Fase 5, a CTO é dimensionada por cobertura de Home Passed (HP),
não pelo splitter inicial. A regra operacional adotada é:

* uma CTO cobre no máximo ``capacidade_hp_por_cto`` HP (padrão: 16);
* a CTO nasce com splitter 1x8 para a ocupação inicial esperada;
* a CTO pode ser expandida para 1x16, permitindo atender todos os 16 HP;
* a penetração calcula HC esperado, mas não reduz a quantidade física de CTOs.
"""

from __future__ import annotations

import math
from typing import Any, Dict


class DimensionamentoError(ValueError):
    """Indica inconsistência nos dados ou nas regras de dimensionamento."""


def _ceil_div(valor: int, capacidade: int) -> int:
    if valor <= 0:
        return 0
    return math.ceil(valor / capacidade)


def recalcular_hierarquia_por_ctos(total_ctos: int, config: Dict[str, Any]) -> Dict[str, int]:
    """Recalcula PONs e CEOs a partir de uma quantidade real de CTOs."""

    if isinstance(total_ctos, bool) or not isinstance(total_ctos, int):
        raise DimensionamentoError("total_ctos deve ser um número inteiro")
    if total_ctos < 0:
        raise DimensionamentoError("total_ctos não pode ser negativo")

    engenharia = config["engenharia"]
    ctos_por_pon = engenharia["ctos_por_pon"]
    pons_por_ceo = engenharia["pons_por_ceo"]

    total_pons = _ceil_div(total_ctos, ctos_por_pon)
    total_ceos = _ceil_div(total_pons, pons_por_ceo)

    return {"ctos": total_ctos, "pons": total_pons, "ceos": total_ceos}


def validar_dimensionamento(resultado: Dict[str, Any]) -> None:
    """Valida as invariantes matemáticas do dimensionamento físico."""

    detalhe = resultado["dimensionamento"]
    demanda_hp = detalhe["demanda_hp_planejada"]
    capacidade_hp_cto = detalhe["capacidade_hp_por_cto"]
    splitter_inicial = detalhe["splitter_cto_inicial"]
    splitter_expansao = detalhe["splitter_cto_expansao"]
    ctos_por_pon = detalhe["ctos_por_pon"]
    pons_por_ceo = detalhe["pons_por_ceo"]

    ctos = resultado["ctos"]
    pons = resultado["pons"]
    ceos = resultado["ceos"]

    if splitter_inicial > splitter_expansao:
        raise DimensionamentoError("splitter inicial não pode superar o splitter de expansão")
    if splitter_expansao < capacidade_hp_cto:
        raise DimensionamentoError(
            "splitter de expansão deve comportar todos os HP cobertos pela CTO"
        )

    if ctos * capacidade_hp_cto < demanda_hp:
        raise DimensionamentoError("capacidade física de CTO insuficiente para os HP")
    if pons * ctos_por_pon < ctos:
        raise DimensionamentoError("capacidade de PON insuficiente para as CTOs")
    if ceos * pons_por_ceo < pons:
        raise DimensionamentoError("capacidade de CEO insuficiente para as PONs")

    if ctos > 0 and (ctos - 1) * capacidade_hp_cto >= demanda_hp:
        raise DimensionamentoError("quantidade de CTOs não é mínima")
    if pons > 0 and (pons - 1) * ctos_por_pon >= ctos:
        raise DimensionamentoError("quantidade de PONs não é mínima")
    if ceos > 0 and (ceos - 1) * pons_por_ceo >= pons:
        raise DimensionamentoError("quantidade de CEOs não é mínima")


def calcular_dimensionamento_ftth(hp: int, config: Dict[str, Any]) -> Dict[str, Any]:
    """Calcula HC esperado e a hierarquia física CTO -> PON -> CEO.

    A quantidade de CTOs é sempre calculada por HP. A penetração é usada para
    estimar quantos desses HP estarão conectados inicialmente (HC), permitindo
    avaliar se os splitters 1x8 instalados no lançamento são suficientes ou se
    já existe necessidade de expansão.
    """

    if isinstance(hp, bool) or not isinstance(hp, int):
        raise DimensionamentoError("hp deve ser um número inteiro")
    if hp < 0:
        raise DimensionamentoError("hp não pode ser negativo")

    engenharia = config["engenharia"]
    penetracao = engenharia["penetracao_estimada"]
    reserva_pct = engenharia["reserva_capacidade_percentual"]
    capacidade_hp_cto = engenharia["capacidade_hp_por_cto"]
    splitter_inicial = engenharia["splitter_cto_inicial"]
    splitter_expansao = engenharia["splitter_cto_expansao"]
    ctos_por_pon = engenharia["ctos_por_pon"]
    pons_por_ceo = engenharia["pons_por_ceo"]

    hc = math.ceil(hp * penetracao)
    demanda_hp_planejada = math.ceil(hp * (1 + reserva_pct)) if hp else 0
    reserva_hp = demanda_hp_planejada - hp

    hierarquia = recalcular_hierarquia_por_ctos(
        _ceil_div(demanda_hp_planejada, capacidade_hp_cto), config
    )
    ctos = hierarquia["ctos"]
    pons = hierarquia["pons"]
    ceos = hierarquia["ceos"]

    capacidade_hp_instalada = ctos * capacidade_hp_cto
    capacidade_hc_inicial = ctos * splitter_inicial
    capacidade_hc_expansao = ctos * splitter_expansao
    deficit_hc_inicial = max(0, hc - capacidade_hc_inicial)

    resultado: Dict[str, Any] = {
        "hp": hp,
        "hc": hc,
        "ctos": ctos,
        "pons": pons,
        "ceos": ceos,
        "dimensionamento": {
            # Campos novos e semanticamente explícitos.
            "regra_cto": "cobertura_hp",
            "penetracao_estimada": penetracao,
            "reserva_capacidade_percentual": reserva_pct,
            "reserva_hp": reserva_hp,
            "demanda_hp_planejada": demanda_hp_planejada,
            "capacidade_hp_por_cto": capacidade_hp_cto,
            "capacidade_hp_instalada": capacidade_hp_instalada,
            "folga_hp_instalada": capacidade_hp_instalada - demanda_hp_planejada,
            "splitter_cto_inicial": splitter_inicial,
            "splitter_cto_expansao": splitter_expansao,
            "capacidade_hc_inicial": capacidade_hc_inicial,
            "capacidade_hc_expansao": capacidade_hc_expansao,
            "hc_estimado": hc,
            "deficit_hc_inicial": deficit_hc_inicial,
            "expansao_splitter_necessaria_no_cenario_estimado": deficit_hc_inicial > 0,
            "hc_teorico_por_cto_cheia": capacidade_hp_cto * penetracao,
            "ctos_por_pon": ctos_por_pon,
            "capacidade_ctos_em_pons": pons * ctos_por_pon,
            "folga_ctos_em_pons": pons * ctos_por_pon - ctos,
            "pons_por_ceo": pons_por_ceo,
            "capacidade_pons_em_ceos": ceos * pons_por_ceo,
            "folga_pons_em_ceos": ceos * pons_por_ceo - pons,
            # Aliases de compatibilidade com relatórios da Fase 4.
            "modo": "hp",
            "base_dimensionamento": hp,
            "demanda_dimensionada": demanda_hp_planejada,
            "capacidade_cto_unitaria": capacidade_hp_cto,
            "capacidade_cto_instalada": capacidade_hp_instalada,
            "folga_unidades_cto": capacidade_hp_instalada - demanda_hp_planejada,
        },
    }

    validar_dimensionamento(resultado)
    return resultado
