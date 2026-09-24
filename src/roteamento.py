"""Roteamento viário robusto para o planejamento FTTH.

A Fase 6 centraliza aqui a construção do grafo de vias, a busca espacial de
nós e o cálculo de rotas. Ausência de malha ou de caminho deixa de ser
convertida silenciosamente em uma linha reta: o chamador recebe um status
explícito e pode gerar uma exceção auditável.
"""

from dataclasses import dataclass
import math
from typing import Iterable, List, Optional, Sequence, Tuple

import networkx as nx
from shapely.geometry import Point
from shapely.strtree import STRtree


Coordenada = Tuple[float, float]

ROTA_OK = "OK"
ROTA_SEM_MALHA = "SEM_MALHA"
ROTA_SEM_CAMINHO = "SEM_CAMINHO"
ROTA_FORA_DA_MALHA = "FORA_DA_MALHA"


def calcular_distancia_metros(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """Distância Haversine entre duas coordenadas WGS84."""

    raio_terra = 6_371_000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = (
        math.sin(delta_phi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return raio_terra * c


def calcular_metragem_coordenadas(coordenadas: Sequence[Coordenada]) -> float:
    return sum(
        calcular_distancia_metros(*coordenadas[i], *coordenadas[i + 1])
        for i in range(len(coordenadas) - 1)
    )


@dataclass(frozen=True)
class ResultadoRota:
    status: str
    coordenadas: List[Coordenada]
    distancia_m: float
    distancia_origem_malha_m: Optional[float] = None
    distancia_destino_malha_m: Optional[float] = None
    mensagem: str = ""

    @property
    def valida(self) -> bool:
        return self.status == ROTA_OK


class RoteadorViario:
    """Grafo de vias com índice espacial para busca eficiente do nó mais próximo."""

    def __init__(self, malha_viaria=None):
        self.grafo = nx.Graph()
        self._nos: List[Coordenada] = []
        self._pontos_nos: List[Point] = []
        self._indice: Optional[STRtree] = None
        self._construir(malha_viaria)

    def _construir(self, malha_viaria) -> None:
        if malha_viaria is None:
            return

        linhas = (
            list(malha_viaria.geoms)
            if hasattr(malha_viaria, "geoms")
            else [malha_viaria]
        )
        for linha in linhas:
            coords = [(float(lon), float(lat)) for lon, lat, *_ in linha.coords]
            for p1, p2 in zip(coords, coords[1:]):
                peso_m = calcular_distancia_metros(*p1, *p2)
                self.grafo.add_edge(p1, p2, weight=peso_m)

        self._nos = list(self.grafo.nodes)
        if self._nos:
            self._pontos_nos = [Point(*n) for n in self._nos]
            self._indice = STRtree(self._pontos_nos)

    def __len__(self) -> int:
        return len(self._nos)

    def no_mais_proximo(self, coordenada: Coordenada):
        if self._indice is None or not self._nos:
            return None, None

        ponto = Point(*coordenada)
        indice = int(self._indice.nearest(ponto))
        no = self._nos[indice]
        distancia_m = calcular_distancia_metros(*coordenada, *no)
        return no, distancia_m

    def calcular_rota(
        self,
        origem: Coordenada,
        destino: Coordenada,
        distancia_maxima_conexao_m: Optional[float] = None,
    ) -> ResultadoRota:
        origem = (float(origem[0]), float(origem[1]))
        destino = (float(destino[0]), float(destino[1]))

        if not self._nos:
            return ResultadoRota(
                status=ROTA_SEM_MALHA,
                coordenadas=[],
                distancia_m=0.0,
                mensagem="malha viária indisponível",
            )

        no_origem, dist_origem = self.no_mais_proximo(origem)
        no_destino, dist_destino = self.no_mais_proximo(destino)

        if distancia_maxima_conexao_m is not None:
            if dist_origem > distancia_maxima_conexao_m or dist_destino > distancia_maxima_conexao_m:
                return ResultadoRota(
                    status=ROTA_FORA_DA_MALHA,
                    coordenadas=[],
                    distancia_m=0.0,
                    distancia_origem_malha_m=dist_origem,
                    distancia_destino_malha_m=dist_destino,
                    mensagem=(
                        "origem ou destino excede a distância máxima de conexão à malha"
                    ),
                )

        try:
            caminho = nx.shortest_path(
                self.grafo,
                source=no_origem,
                target=no_destino,
                weight="weight",
            )
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            return ResultadoRota(
                status=ROTA_SEM_CAMINHO,
                coordenadas=[],
                distancia_m=0.0,
                distancia_origem_malha_m=dist_origem,
                distancia_destino_malha_m=dist_destino,
                mensagem="não existe caminho viário entre origem e destino",
            )

        rota = [origem] + list(caminho) + [destino]
        limpa: List[Coordenada] = []
        for coord in rota:
            if not limpa or coord != limpa[-1]:
                limpa.append(coord)

        return ResultadoRota(
            status=ROTA_OK,
            coordenadas=limpa,
            distancia_m=calcular_metragem_coordenadas(limpa),
            distancia_origem_malha_m=dist_origem,
            distancia_destino_malha_m=dist_destino,
        )


def expandir_bbox_com_pontos(
    bbox: Tuple[float, float, float, float],
    pontos: Iterable[Coordenada],
    margem_metros: float = 0.0,
) -> Tuple[float, float, float, float]:
    """Expande um bbox WGS84 para incluir pontos externos e uma margem métrica."""

    min_lon, min_lat, max_lon, max_lat = map(float, bbox)
    pontos = list(pontos)
    for lon, lat in pontos:
        min_lon = min(min_lon, float(lon))
        min_lat = min(min_lat, float(lat))
        max_lon = max(max_lon, float(lon))
        max_lat = max(max_lat, float(lat))

    if margem_metros <= 0:
        return min_lon, min_lat, max_lon, max_lat

    lat_ref = (min_lat + max_lat) / 2.0
    margem_lat = margem_metros / 111_320.0
    cos_lat = max(abs(math.cos(math.radians(lat_ref))), 0.01)
    margem_lon = margem_metros / (111_320.0 * cos_lat)
    return (
        min_lon - margem_lon,
        min_lat - margem_lat,
        max_lon + margem_lon,
        max_lat + margem_lat,
    )
