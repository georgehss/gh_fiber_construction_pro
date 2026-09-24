"""Leitura de entradas geoespaciais KML/KMZ e resolução de arquivos do projeto."""

from __future__ import annotations

import hashlib
import io
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from shapely.geometry import MultiPolygon, Polygon

KML_NS = "http://www.opengis.net/kml/2.2"
NS = {"kml": KML_NS}
EXTENSOES_SUPORTADAS = {".kml", ".kmz"}
MARCADORES_CORRECAO = ("editad", "corrig")


def _ler_xml_kml(caminho: Path) -> ET.Element:
    """Retorna a raiz XML de um KML ou do KML principal dentro de um KMZ."""

    caminho = Path(caminho)
    extensao = caminho.suffix.lower()

    if extensao == ".kml":
        try:
            return ET.parse(caminho).getroot()
        except ET.ParseError as exc:
            raise ValueError(f"KML inválido em '{caminho.name}': {exc}") from exc

    if extensao != ".kmz":
        raise ValueError(
            f"Formato não suportado: '{caminho.suffix}'. Use .kml ou .kmz."
        )

    try:
        with zipfile.ZipFile(caminho, "r") as arquivo_zip:
            membros_kml = [
                nome for nome in arquivo_zip.namelist() if nome.lower().endswith(".kml")
            ]
            if not membros_kml:
                raise ValueError(f"KMZ '{caminho.name}' não contém nenhum arquivo KML.")

            # doc.kml é a convenção mais comum. Quando não existir, usa o
            # primeiro KML em ordem determinística.
            membro = next(
                (nome for nome in membros_kml if Path(nome).name.lower() == "doc.kml"),
                sorted(membros_kml, key=str.lower)[0],
            )
            conteudo = arquivo_zip.read(membro)
    except zipfile.BadZipFile as exc:
        raise ValueError(f"KMZ inválido/corrompido: '{caminho.name}'.") from exc

    try:
        return ET.parse(io.BytesIO(conteudo)).getroot()
    except ET.ParseError as exc:
        raise ValueError(
            f"KML interno inválido em '{caminho.name}' ({membro}): {exc}"
        ) from exc


def _parse_coordenadas(texto: Optional[str]) -> List[Tuple[float, float]]:
    if not texto:
        return []

    coordenadas: List[Tuple[float, float]] = []
    for item in texto.strip().split():
        partes = item.split(",")
        if len(partes) < 2:
            continue
        try:
            coordenadas.append((float(partes[0]), float(partes[1])))
        except ValueError:
            continue
    return coordenadas


def _poligonos_validos(geometria) -> Iterable[Polygon]:
    """Normaliza/repara uma geometria e devolve somente polígonos válidos."""

    if geometria.is_empty:
        return []

    if not geometria.is_valid:
        geometria = geometria.buffer(0)

    if geometria.is_empty:
        return []
    if isinstance(geometria, Polygon):
        return [geometria]
    if isinstance(geometria, MultiPolygon):
        return list(geometria.geoms)
    return []


def extrair_poligonos(caminho: Path) -> List[Dict[str, object]]:
    """Extrai polígonos reais de um KML/KMZ, inclusive em ``MultiGeometry``.

    Somente elementos ``Polygon`` são considerados; pontos e linhas presentes
    no mesmo arquivo não são confundidos com a área do projeto. Buracos
    (``innerBoundaryIs``) são preservados.
    """

    caminho = Path(caminho)
    root = _ler_xml_kml(caminho)
    resultado: List[Dict[str, object]] = []

    for placemark in root.findall(".//kml:Placemark", NS):
        nome_elem = placemark.find("kml:name", NS)
        nome_base = (
            nome_elem.text.strip()
            if nome_elem is not None and nome_elem.text and nome_elem.text.strip()
            else "Polígono sem título"
        )

        poligonos_placemark = placemark.findall(".//kml:Polygon", NS)
        for indice_local, elem_polygon in enumerate(poligonos_placemark, start=1):
            outer = elem_polygon.find(
                "kml:outerBoundaryIs/kml:LinearRing/kml:coordinates", NS
            )
            shell = _parse_coordenadas(outer.text if outer is not None else None)
            if len(shell) < 3:
                continue

            holes = []
            for inner in elem_polygon.findall(
                "kml:innerBoundaryIs/kml:LinearRing/kml:coordinates", NS
            ):
                coords_hole = _parse_coordenadas(inner.text)
                if len(coords_hole) >= 3:
                    holes.append(coords_hole)

            try:
                geometria = Polygon(shell, holes)
            except (TypeError, ValueError):
                continue

            normalizados = list(_poligonos_validos(geometria))
            for indice_parte, poly in enumerate(normalizados, start=1):
                sufixo = ""
                if len(poligonos_placemark) > 1:
                    sufixo += f" #{indice_local}"
                if len(normalizados) > 1:
                    sufixo += f".{indice_parte}"
                resultado.append(
                    {
                        "nome": f"{nome_base}{sufixo}",
                        "geom": poly,
                        "bbox": poly.bounds,
                    }
                )

    if not resultado:
        raise ValueError(
            f"Nenhum Polygon válido foi encontrado em '{caminho.name}'."
        )
    return resultado


def extrair_pontos(caminho: Path) -> List[Dict[str, object]]:
    """Extrai Placemarks do tipo Point de um KML/KMZ de correções."""

    root = _ler_xml_kml(Path(caminho))
    elementos: List[Dict[str, object]] = []

    for placemark in root.findall(".//kml:Placemark", NS):
        nome_tag = placemark.find("kml:name", NS)
        ponto_tag = placemark.find(".//kml:Point/kml:coordinates", NS)
        if nome_tag is None or not nome_tag.text or ponto_tag is None:
            continue

        coords = _parse_coordenadas(ponto_tag.text)
        if not coords:
            continue
        lon, lat = coords[0]
        elementos.append({"nome": nome_tag.text.strip(), "lat": lat, "lon": lon})

    return elementos


def bbox_total(poligonos: Sequence[Dict[str, object]]) -> Tuple[float, float, float, float]:
    if not poligonos:
        raise ValueError("Não há polígonos para calcular o bbox do projeto.")

    bounds = [item["geom"].bounds for item in poligonos]
    return (
        min(b[0] for b in bounds),
        min(b[1] for b in bounds),
        max(b[2] for b in bounds),
        max(b[3] for b in bounds),
    )


def hash_geometria_projeto(poligonos: Sequence[Dict[str, object]]) -> str:
    """Hash determinístico das geometrias, independente do nome dos Placemarks."""

    partes = sorted(item["geom"].wkb_hex for item in poligonos)
    conteudo = "|".join(partes).encode("ascii")
    return hashlib.sha256(conteudo).hexdigest()


def eh_arquivo_correcao(caminho: Path) -> bool:
    nome = Path(caminho).stem.lower()
    return any(marcador in nome for marcador in MARCADORES_CORRECAO)


def _arquivos_geoespaciais(input_dir: Path) -> List[Path]:
    return sorted(
        [
            item
            for item in Path(input_dir).iterdir()
            if item.is_file() and item.suffix.lower() in EXTENSOES_SUPORTADAS
        ],
        key=lambda p: p.name.lower(),
    )


def _resolver_explicito(input_dir: Path, nome: str, finalidade: str) -> Path:
    caminho = Path(input_dir) / nome
    if not caminho.exists():
        raise FileNotFoundError(
            f"Arquivo de {finalidade} configurado não encontrado: '{caminho}'."
        )
    if caminho.suffix.lower() not in EXTENSOES_SUPORTADAS:
        raise ValueError(
            f"Arquivo de {finalidade} deve ser KML ou KMZ: '{caminho.name}'."
        )
    return caminho


def resolver_arquivo_projeto(input_dir: Path, config: Dict) -> Path:
    entrada = config.get("entrada", {})
    explicito = entrada.get("arquivo_projeto")
    if explicito:
        return _resolver_explicito(input_dir, explicito, "projeto")

    candidatos = [p for p in _arquivos_geoespaciais(input_dir) if not eh_arquivo_correcao(p)]
    if not candidatos:
        raise FileNotFoundError("Nenhum arquivo KML/KMZ de projeto foi encontrado em data/input/.")
    if len(candidatos) > 1:
        nomes = ", ".join(p.name for p in candidatos)
        raise ValueError(
            "Mais de um arquivo de projeto foi encontrado em data/input/: "
            f"{nomes}. Defina 'entrada.arquivo_projeto' no config.json."
        )
    return candidatos[0]


def resolver_arquivo_correcoes(input_dir: Path, config: Dict) -> Optional[Path]:
    entrada = config.get("entrada", {})
    explicito = entrada.get("arquivo_correcoes")
    if explicito:
        return _resolver_explicito(input_dir, explicito, "correções")

    candidatos = [p for p in _arquivos_geoespaciais(input_dir) if eh_arquivo_correcao(p)]
    if not candidatos:
        return None
    if len(candidatos) > 1:
        nomes = ", ".join(p.name for p in candidatos)
        raise ValueError(
            "Mais de um arquivo de correções foi encontrado em data/input/: "
            f"{nomes}. Defina 'entrada.arquivo_correcoes' no config.json."
        )
    return candidatos[0]
