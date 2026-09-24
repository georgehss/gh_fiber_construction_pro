"""Clusterização capacitada para o planejamento FTTH.

A Fase 5 deixa de usar K-Means puro como regra de alocação. K-Means ainda é
utilizado somente para gerar sementes geográficas; a atribuição final é feita
com limite rígido de capacidade.
"""

from __future__ import annotations

import math
from typing import Any, Dict, Iterable, List, Sequence, Tuple

import numpy as np
from sklearn.cluster import KMeans


class ClusterizacaoError(ValueError):
    """Indica que uma alocação capacitada não pôde ser construída."""


def _validar_pontos(pontos: Sequence[Sequence[float]], nome: str = "pontos") -> np.ndarray:
    arr = np.asarray(pontos, dtype=float)
    if arr.size == 0:
        return np.empty((0, 2), dtype=float)
    if arr.ndim != 2 or arr.shape[1] != 2:
        raise ClusterizacaoError(f"{nome} deve possuir coordenadas no formato Nx2")
    if not np.isfinite(arr).all():
        raise ClusterizacaoError(f"{nome} contém coordenadas inválidas")
    return arr


def _validar_capacidade(capacidade: int) -> None:
    if isinstance(capacidade, bool) or not isinstance(capacidade, int) or capacidade <= 0:
        raise ClusterizacaoError("capacidade deve ser um inteiro positivo")


def _transformar_para_distancia(pontos: np.ndarray, latitude_ref: float) -> np.ndarray:
    if len(pontos) == 0:
        return pontos.copy()
    fator_lon = max(1e-9, math.cos(math.radians(latitude_ref)))
    return np.column_stack((pontos[:, 0] * fator_lon, pontos[:, 1]))


def _distancias_quadradas(pontos: np.ndarray, centros: np.ndarray) -> np.ndarray:
    latitude_ref = float(np.mean(pontos[:, 1])) if len(pontos) else 0.0
    p = _transformar_para_distancia(pontos, latitude_ref)
    c = _transformar_para_distancia(centros, latitude_ref)
    diferencas = p[:, None, :] - c[None, :, :]
    return np.sum(diferencas * diferencas, axis=2)


def _ordem_por_restricao(distancias: np.ndarray, indices: Iterable[int]) -> List[int]:
    indices = list(indices)
    if distancias.shape[1] <= 1:
        return sorted(indices)

    prioridades: List[Tuple[float, float, int]] = []
    for indice in indices:
        ordenadas = np.sort(distancias[indice])
        arrependimento = float(ordenadas[1] - ordenadas[0])
        menor = float(ordenadas[0])
        prioridades.append((-arrependimento, menor, indice))
    prioridades.sort()
    return [indice for _, _, indice in prioridades]


def atribuir_pontos_a_centros_capacitado(
    pontos: Sequence[Sequence[float]],
    centros: Sequence[Sequence[float]],
    capacidade: int,
    *,
    sementes_labels: Sequence[int] | None = None,
) -> np.ndarray:
    """Atribui pontos a centros fixos sem exceder a capacidade."""

    _validar_capacidade(capacidade)
    pontos_arr = _validar_pontos(pontos)
    centros_arr = _validar_pontos(centros, "centros")

    n_pontos = len(pontos_arr)
    n_centros = len(centros_arr)

    if n_pontos == 0:
        return np.empty(0, dtype=int)
    if n_centros == 0:
        raise ClusterizacaoError("não existem centros para receber os pontos")
    if n_centros * capacidade < n_pontos:
        raise ClusterizacaoError(
            f"capacidade insuficiente: {n_centros} centros x {capacidade} = "
            f"{n_centros * capacidade}, mas existem {n_pontos} pontos"
        )

    distancias = _distancias_quadradas(pontos_arr, centros_arr)
    labels = np.full(n_pontos, -1, dtype=int)
    ocupacao = np.zeros(n_centros, dtype=int)

    if sementes_labels is not None:
        sementes = np.asarray(sementes_labels, dtype=int)
        if len(sementes) != n_pontos:
            raise ClusterizacaoError("sementes_labels possui tamanho incompatível")
        for centro_idx in range(n_centros):
            membros = np.where(sementes == centro_idx)[0]
            if len(membros) == 0:
                raise ClusterizacaoError("cluster automático vazio durante refinamento")
            escolhido = int(membros[np.argmin(distancias[membros, centro_idx])])
            labels[escolhido] = centro_idx
            ocupacao[centro_idx] += 1

    pendentes = np.where(labels < 0)[0]
    for ponto_idx in _ordem_por_restricao(distancias, pendentes):
        ordem_centros = np.argsort(distancias[ponto_idx], kind="stable")
        destino = None
        for centro_idx in ordem_centros:
            centro_idx = int(centro_idx)
            if ocupacao[centro_idx] < capacidade:
                destino = centro_idx
                break
        if destino is None:
            raise ClusterizacaoError("não foi possível encontrar centro com capacidade livre")
        labels[ponto_idx] = destino
        ocupacao[destino] += 1

    if np.any(labels < 0):
        raise ClusterizacaoError("existem pontos sem atribuição após clusterização")
    if np.any(ocupacao > capacidade):
        raise ClusterizacaoError("a clusterização excedeu a capacidade configurada")

    return labels


def _montar_clusters(
    pontos: np.ndarray,
    labels: np.ndarray,
    quantidade_clusters: int,
    capacidade: int,
) -> List[Dict[str, Any]]:
    clusters: List[Dict[str, Any]] = []
    for cluster_idx in range(quantidade_clusters):
        indices = np.where(labels == cluster_idx)[0]
        if len(indices):
            centro = np.mean(pontos[indices], axis=0)
            centro_tuple = (float(centro[0]), float(centro[1]))
        else:
            centro_tuple = (float("nan"), float("nan"))
        clusters.append(
            {
                "indice": cluster_idx,
                "indices": [int(i) for i in indices],
                "centro": centro_tuple,
                "quantidade": int(len(indices)),
                "capacidade": capacidade,
                "folga": int(capacidade - len(indices)),
            }
        )
    return clusters


def clusterizar_pontos_capacitado(
    pontos: Sequence[Sequence[float]],
    quantidade_clusters: int,
    capacidade: int,
    *,
    random_state: int = 42,
    max_iter: int = 20,
) -> Tuple[np.ndarray, List[Dict[str, Any]]]:
    """Clusteriza pontos com limite rígido por cluster.

    K-Means fornece somente sementes iniciais. A alocação final passa pelo
    atribuidor capacitado e os centros são recalculados iterativamente.
    """

    _validar_capacidade(capacidade)
    pontos_arr = _validar_pontos(pontos)
    n_pontos = len(pontos_arr)

    if isinstance(quantidade_clusters, bool) or not isinstance(quantidade_clusters, int):
        raise ClusterizacaoError("quantidade_clusters deve ser um inteiro")
    if quantidade_clusters < 0:
        raise ClusterizacaoError("quantidade_clusters não pode ser negativa")
    if n_pontos == 0:
        if quantidade_clusters != 0:
            raise ClusterizacaoError("não é possível criar clusters sem pontos")
        return np.empty(0, dtype=int), []
    if quantidade_clusters <= 0:
        raise ClusterizacaoError("é necessário pelo menos um cluster")
    if quantidade_clusters > n_pontos:
        raise ClusterizacaoError(
            f"há mais clusters ({quantidade_clusters}) que pontos ({n_pontos})"
        )
    if quantidade_clusters * capacidade < n_pontos:
        raise ClusterizacaoError(
            f"{quantidade_clusters} clusters de capacidade {capacidade} não comportam "
            f"{n_pontos} pontos"
        )

    if quantidade_clusters == 1:
        labels = np.zeros(n_pontos, dtype=int)
        return labels, _montar_clusters(pontos_arr, labels, 1, capacidade)

    latitude_ref = float(np.mean(pontos_arr[:, 1]))
    pontos_cluster = _transformar_para_distancia(pontos_arr, latitude_ref)
    kmeans = KMeans(
        n_clusters=quantidade_clusters,
        random_state=random_state,
        n_init=20,
    )
    labels = kmeans.fit_predict(pontos_cluster)
    centros = np.array(
        [np.mean(pontos_arr[labels == i], axis=0) for i in range(quantidade_clusters)],
        dtype=float,
    )

    for _ in range(max_iter):
        novos_labels = atribuir_pontos_a_centros_capacitado(
            pontos_arr,
            centros,
            capacidade,
            sementes_labels=labels,
        )
        novos_centros = np.array(
            [np.mean(pontos_arr[novos_labels == i], axis=0) for i in range(quantidade_clusters)],
            dtype=float,
        )
        if np.array_equal(novos_labels, labels):
            labels = novos_labels
            centros = novos_centros
            break
        labels = novos_labels
        centros = novos_centros

    clusters = _montar_clusters(pontos_arr, labels, quantidade_clusters, capacidade)
    if any(c["quantidade"] == 0 for c in clusters):
        raise ClusterizacaoError("cluster automático vazio após refinamento")
    if any(c["quantidade"] > capacidade for c in clusters):
        raise ClusterizacaoError("cluster automático acima da capacidade")

    return labels, clusters


def agrupar_pontos_por_capacidade(
    pontos: Sequence[Sequence[float]],
    capacidade: int,
    *,
    random_state: int = 42,
) -> Tuple[np.ndarray, List[Dict[str, Any]]]:
    _validar_capacidade(capacidade)
    pontos_arr = _validar_pontos(pontos)
    if len(pontos_arr) == 0:
        return np.empty(0, dtype=int), []
    quantidade = math.ceil(len(pontos_arr) / capacidade)
    return clusterizar_pontos_capacitado(
        pontos_arr,
        quantidade,
        capacidade,
        random_state=random_state,
    )


def validar_alocacao_hierarquica(
    *,
    quantidade_hps: int,
    ctos: Sequence[Dict[str, Any]],
    pons: Sequence[Dict[str, Any]],
    ceos: Sequence[Dict[str, Any]],
    capacidade_hp_por_cto: int,
    ctos_por_pon: int,
    pons_por_ceo: int,
) -> Dict[str, Any]:
    """Valida as invariantes físicas HP -> CTO -> PON -> CEO."""

    hp_indices: List[int] = []
    cto_ids = set()
    for cto in ctos:
        cto_id = cto["id"]
        if cto_id in cto_ids:
            raise ClusterizacaoError(f"ID de CTO duplicado: {cto_id}")
        cto_ids.add(cto_id)
        indices = list(cto.get("hp_indices", []))
        if len(indices) > capacidade_hp_por_cto:
            raise ClusterizacaoError(
                f"{cto_id} possui {len(indices)} HP, acima do limite {capacidade_hp_por_cto}"
            )
        hp_indices.extend(indices)

    if len(hp_indices) != quantidade_hps:
        raise ClusterizacaoError(
            f"HP atribuídos ({len(hp_indices)}) diferente do total ({quantidade_hps})"
        )
    if len(set(hp_indices)) != len(hp_indices):
        raise ClusterizacaoError("um ou mais HP foram atribuídos a mais de uma CTO")
    if set(hp_indices) != set(range(quantidade_hps)):
        raise ClusterizacaoError("existem HP sem CTO atribuída")

    pons_ids = set()
    ctos_em_pons: List[str] = []
    for pon in pons:
        pon_id = pon["id"]
        if pon_id in pons_ids:
            raise ClusterizacaoError(f"ID de PON duplicado: {pon_id}")
        pons_ids.add(pon_id)
        ids = list(pon.get("cto_ids", []))
        if len(ids) > ctos_por_pon:
            raise ClusterizacaoError(
                f"{pon_id} possui {len(ids)} CTOs, acima do limite {ctos_por_pon}"
            )
        ctos_em_pons.extend(ids)

    if set(ctos_em_pons) != cto_ids or len(ctos_em_pons) != len(set(ctos_em_pons)):
        raise ClusterizacaoError("cada CTO deve pertencer a exatamente uma PON")

    ceos_ids = set()
    pons_em_ceos: List[str] = []
    for ceo in ceos:
        ceo_id = ceo["id"]
        if ceo_id in ceos_ids:
            raise ClusterizacaoError(f"ID de CEO duplicado: {ceo_id}")
        ceos_ids.add(ceo_id)
        ids = list(ceo.get("pon_ids", []))
        if len(ids) > pons_por_ceo:
            raise ClusterizacaoError(
                f"{ceo_id} possui {len(ids)} PONs, acima do limite {pons_por_ceo}"
            )
        pons_em_ceos.extend(ids)

    if set(pons_em_ceos) != pons_ids or len(pons_em_ceos) != len(set(pons_em_ceos)):
        raise ClusterizacaoError("cada PON deve pertencer a exatamente uma CEO")

    ocupacoes_cto = [len(cto.get("hp_indices", [])) for cto in ctos]
    ocupacoes_pon = [len(pon.get("cto_ids", [])) for pon in pons]
    ocupacoes_ceo = [len(ceo.get("pon_ids", [])) for ceo in ceos]

    return {
        "hp_total": quantidade_hps,
        "hp_atribuidos": len(hp_indices),
        "ctos_total": len(ctos),
        "ctos_acima_capacidade": sum(v > capacidade_hp_por_cto for v in ocupacoes_cto),
        "maior_ocupacao_hp_cto": max(ocupacoes_cto, default=0),
        "pons_total": len(pons),
        "pons_acima_capacidade": sum(v > ctos_por_pon for v in ocupacoes_pon),
        "maior_ocupacao_ctos_pon": max(ocupacoes_pon, default=0),
        "ceos_total": len(ceos),
        "ceos_acima_capacidade": sum(v > pons_por_ceo for v in ocupacoes_ceo),
        "maior_ocupacao_pons_ceo": max(ocupacoes_ceo, default=0),
        "valido": True,
    }
