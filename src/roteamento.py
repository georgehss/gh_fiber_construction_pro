"""Roteamento viário robusto para o planejamento FTTH.

A Fase 7 evolui o roteamento para um modelo híbrido: se os postes físicos
estiverem disponíveis, constrói a topologia baseada na infraestrutura,
penalizando travessias de rua. Aplica o cálculo real de metragem (flechas
e reservas técnicas) antes de devolver o resultado.
"""

from dataclasses import dataclass
import math
from typing import Iterable, List, Optional, Sequence, Tuple, Dict, Any

import networkx as nx
from shapely.geometry import Point, LineString
from shapely.strtree import STRtree

# Importação da função utilitária criada na Fase 7
from .geo_io import calcular_metragem_com_reserva


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

    def __init__(self, malha_viaria=None, postes: Optional[List[Point]] = None, config: Optional[Dict[str, Any]] = None):
        self.grafo = nx.Graph()
        self._nos: List[Coordenada] = []
        self._pontos_nos: List[Point] = []
        self._indice: Optional[STRtree] = None
        self.config = config or {}
        
        # Decide qual estratégia de grafo usar (Fase 7)
        if postes:
            self._construir_por_postes(postes, malha_viaria)
        else:
            self._construir_por_malha(malha_viaria)

    def _construir_por_malha(self, malha_viaria) -> None:
        """Fallback: Constrói grafo usando eixos de rua (Fase 6)."""
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
                self.grafo.add_edge(p1, p2, weight=peso_m, real_dist=peso_m)

        self._gerar_indice()

    def _construir_por_postes(self, postes: List[Point], malha_viaria) -> None:
        """Constrói grafo ligando postes próximos, penalizando travessias viárias (Fase 7)."""
        if not postes:
            return

        raio_maximo_vao_m = 60.0
        penalidade_travessia = 3.0 # Triplica o "peso" da rota caso o trecho cruze a rua
        
        linhas_ruas = list(malha_viaria.geoms) if hasattr(malha_viaria, "geoms") and malha_viaria else []
        indice_ruas = STRtree(linhas_ruas) if linhas_ruas else None
        indice_postes = STRtree(postes)

        for i, p1 in enumerate(postes):
            coord1 = (p1.x, p1.y)
            # Busca vizinhos por bounding box expandido grosseiramente (~60m em graus WGS84)
            margem_deg = raio_maximo_vao_m / 111_320.0
            bbox = (p1.x - margem_deg, p1.y - margem_deg, p1.x + margem_deg, p1.y + margem_deg)
            vizinhos_idx = indice_postes.query(bbox)
            
            for idx in vizinhos_idx:
                if idx <= i:
                    continue # Evita arestas duplicadas e self-loops
                
                p2 = postes[idx]
                coord2 = (p2.x, p2.y)
                dist_m = calcular_distancia_metros(*coord1, *coord2)
                
                if dist_m <= raio_maximo_vao_m:
                    peso_rota = dist_m
                    
                    # Checa se o cabo cruza uma rua do OSM para aplicar penalidade
                    if indice_ruas is not None:
                        segmento = LineString([p1, p2])
                        # Consulta apenas ruas próximas ao segmento para performance
                        idx_ruas_proximas = indice_ruas.query(segmento)
                        for r_idx in idx_ruas_proximas:
                            if segmento.intersects(linhas_ruas[r_idx]):
                                peso_rota *= penalidade_travessia
                                break # Penaliza uma vez por trecho
                                
                    self.grafo.add_edge(coord1, coord2, weight=peso_rota, real_dist=dist_m)
                    
        self._gerar_indice()

    def _gerar_indice(self):
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
        tipo_elemento: str = "distribuicao"
    ) -> ResultadoRota:
        origem = (float(origem[0]), float(origem[1]))
        destino = (float(destino[0]), float(destino[1]))

        if not self._nos:
            return ResultadoRota(
                status=ROTA_SEM_MALHA,
                coordenadas=[],
                distancia_m=0.0,
                mensagem="malha viária/física indisponível",
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
                mensagem="não existe caminho físico entre origem e destino",
            )

        rota = [origem] + list(caminho) + [destino]
        limpa: List[Coordenada] = []
        for coord in rota:
            if not limpa or coord != limpa[-1]:
                limpa.append(coord)

        # Na Fase 7, calculamos a distância limpa e depois aplicamos as margens e reservas
        dist_2d = calcular_metragem_coordenadas(limpa)
        dist_final_reserva = calcular_metragem_com_reserva(dist_2d, self.config, tipo_elemento)

        return ResultadoRota(
            status=ROTA_OK,
            coordenadas=limpa,
            distancia_m=dist_final_reserva,
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