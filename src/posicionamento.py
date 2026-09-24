import xml.etree.ElementTree as ET
import math, json, os, requests, itertools
from shapely.geometry import Point, MultiLineString, LineString
from shapely.ops import nearest_points
import numpy as np
from pathlib import Path
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from .cache_manager import carregar_cache_casas
from .config import carregar_config
from .clusterizacao import (
    ClusterizacaoError,
    agrupar_pontos_por_capacidade,
    atribuir_pontos_a_centros_capacitado,
    clusterizar_pontos_capacitado,
    validar_alocacao_hierarquica,
)
from .dimensionamento import calcular_dimensionamento_ftth, recalcular_hierarquia_por_ctos
from .geo_io import (
    bbox_total,
    extrair_poligonos,
    extrair_pontos,
    resolver_arquivo_correcoes,
    resolver_arquivo_projeto,
)
from .logger_config import configurar_logger
from .roteamento import (
    ROTA_FORA_DA_MALHA,
    ROTA_OK,
    ROTA_SEM_CAMINHO,
    ROTA_SEM_MALHA,
    RoteadorViario,
    calcular_distancia_metros as _calcular_distancia_metros,
    calcular_metragem_coordenadas,
    expandir_bbox_com_pontos,
)
import networkx as nx

# Identifica a pasta raiz do projeto de forma dinâmica
BASE_DIR = Path(__file__).resolve().parent.parent

INPUT_DIR = BASE_DIR / "data" / "input"
OUTPUT_DIR = BASE_DIR / "data" / "output"
KML_NS = 'http://www.opengis.net/kml/2.2'
ET.register_namespace('', KML_NS)

COR_CABO_PADRAO_KML = "ff00ffff"  # Amarelo em AABBGGRR


def carregar_casas_cache(nome_projeto, caminho_projeto, logger, CONFIG):
    poligonos = extrair_poligonos(Path(caminho_projeto))
    cache = carregar_cache_casas(OUTPUT_DIR, nome_projeto, poligonos, CONFIG, logger=logger)
    if cache is None:
        raise FileNotFoundError(
            "❌ Cache de edificações ausente, expirado ou incompatível com a geometria atual. "
            "Rode primeiro 'python -m src.contagem_hp'."
        )
    pontos, _ = cache
    return np.array(pontos), poligonos

def extrair_bbox_poligono(caminho_kml):
    """Compatibilidade: retorna o bbox combinado de todos os polígonos KML/KMZ."""
    return bbox_total(extrair_poligonos(Path(caminho_kml)))

def ler_kml_corrigido_pelo_usuario(caminho_arquivo_kml, logger):
    """Lê pontos CTO/CEO de um KML ou KMZ de correções."""
    caminho = Path(caminho_arquivo_kml)
    logger.info("🔍 Lendo arquivo de correções: %s", caminho.name)
    try:
        elementos = extrair_pontos(caminho)
        logger.info("✅ %d elementos carregados do arquivo de correções.", len(elementos))
        return elementos
    except (OSError, ValueError) as exc:
        logger.warning("⚠️ Erro ao ler correções: %s. O arquivo será ignorado.", exc)
        return []

def criar_sessao_com_retry(CONFIG):
    """Cria sessão HTTP usando a política de retry definida no config."""

    api_config = CONFIG["api"]
    sessao = requests.Session()
    retry_strategy = Retry(
        total=api_config["overpass_retry_max"],
        backoff_factor=api_config["overpass_backoff_factor"],
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["HEAD", "GET", "POST"],
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    sessao.mount("http://", adapter)
    sessao.mount("https://", adapter)
    return sessao


def montar_consulta_overpass(bbox, timeout_segundos):
    """Monta a consulta Overpass usando o timeout configurado."""

    min_lon, min_lat, max_lon, max_lat = bbox
    return f"""
[out:json][timeout:{timeout_segundos}];
(way["highway"]({min_lat},{min_lon},{max_lat},{max_lon});
 way["junction"]({min_lat},{min_lon},{max_lat},{max_lon}););
out geom;
"""


def baixar_linhas_ruas(bbox, logger, CONFIG):
    logger.info("🛣️ Obtendo malha viária...")
    api_config = CONFIG["api"]
    timeout = api_config["overpass_timeout_segundos"]
    overpass_query = montar_consulta_overpass(bbox, timeout)
    url = "https://overpass-api.de/api/interpreter"
    headers = {"User-Agent": "FTTH_Snapper/2.1", "Accept": "application/json"}
    linhas_ruas = []
    try:
        sessao = criar_sessao_com_retry(CONFIG)
        res = sessao.post(
            url,
            data={"data": overpass_query},
            headers=headers,
            timeout=timeout,
        )
        res.raise_for_status()
        data = res.json()
        for elem in data.get("elements", []):
            geom = elem.get("geometry", [])
            if len(geom) >= 2:
                coords = [(pt["lon"], pt["lat"]) for pt in geom]
                linhas_ruas.append(LineString(coords))
        return MultiLineString(linhas_ruas) if linhas_ruas else None
    except requests.exceptions.RequestException as e:
        logger.warning(f"⚠️ Erro ao obter vias: {e}")
        return None


def alinhar_ponto_na_rua(
    ponto,
    malha_viaria,
    distancia_maxima_metros=None,
    logger=None,
    rotulo="ponto",
):
    """Alinha um ponto à via somente quando o snap respeita o limite.

    Se não houver malha viária ou se a via mais próxima estiver além de
    ``distancia_maxima_metros``, a coordenada original é preservada.
    """

    if malha_viaria is None:
        return ponto.x, ponto.y

    pt_proximo = nearest_points(malha_viaria, ponto)[0]
    distancia_snap = calcular_distancia_metros(
        ponto.x, ponto.y, pt_proximo.x, pt_proximo.y
    )

    if (
        distancia_maxima_metros is not None
        and distancia_snap > distancia_maxima_metros
    ):
        if logger is not None:
            logger.warning(
                "⚠️ Snap ignorado para %s: via mais próxima a %.1fm "
                "(limite %.1fm).",
                rotulo,
                distancia_snap,
                distancia_maxima_metros,
            )
        return ponto.x, ponto.y

    return pt_proximo.x, pt_proximo.y

def construir_grafo_ruas(malha_viaria):
    """Compatibilidade: constrói o roteador viário indexado da Fase 6."""

    return RoteadorViario(malha_viaria)


def calcular_rota_detalhada(roteador, pt_origem, pt_destino, distancia_maxima_conexao_m=None):
    """Retorna ResultadoRota com status explícito, sem fallback silencioso."""

    if not isinstance(roteador, RoteadorViario):
        raise TypeError("roteador deve ser uma instância de RoteadorViario")
    return roteador.calcular_rota(
        pt_origem,
        pt_destino,
        distancia_maxima_conexao_m=distancia_maxima_conexao_m,
    )


def calcular_rota_pela_rua(roteador, pt_origem, pt_destino):
    """Compatibilidade legada: retorna coordenadas somente para rotas válidas."""

    resultado = calcular_rota_detalhada(roteador, pt_origem, pt_destino)
    return resultado.coordenadas if resultado.valida else []


def calcular_distancia_metros(lon1, lat1, lon2, lat2):
    return _calcular_distancia_metros(lon1, lat1, lon2, lat2)


def calcular_metragem_rota(rota):
    return calcular_metragem_coordenadas(rota)


def obter_olt_fisica(CONFIG):
    """Retorna metadados da OLT física ou ``None`` quando não configurada."""

    equipamentos = CONFIG["equipamentos"]
    olt = equipamentos["olt"]
    if olt["latitude"] is None or olt["longitude"] is None:
        return None
    return {
        "id": "OLT_0001",
        "nome": equipamentos["nome_olt_padrao"],
        "coords_brutas": (float(olt["longitude"]), float(olt["latitude"])),
    }


# --- DEFINIÇÃO DA PALETA DE CORES POR PON ---
def obter_paleta_pon(pon_num):
    """Retorna ciclicamente uma tupla (URL_Icone, Cor_Linha_Hex_AABBGGRR) para diferenciar as PONs"""
    paletas = [
        ("http://maps.google.com/mapfiles/kml/paddle/blu-blank.png", "ffff0000"),  # Azul
        ("http://maps.google.com/mapfiles/kml/paddle/grn-blank.png", "ff00ff00"),  # Verde
        ("http://maps.google.com/mapfiles/kml/paddle/ylw-blank.png", "ff00ffff"),  # Amarelo
        ("http://maps.google.com/mapfiles/kml/paddle/purple-blank.png", "ffff00ff"),# Roxo
        ("http://maps.google.com/mapfiles/kml/paddle/orange-blank.png", "ff0088ff"),# Laranja
        ("http://maps.google.com/mapfiles/kml/paddle/pink-blank.png", "ffff00aa"),  # Rosa
    ]
    return paletas[(pon_num - 1) % len(paletas)]


def obter_cor_cabo_pon(pon_num, colorir_cabos):
    """Retorna a cor do cabo respeitando a opção visual do projeto."""

    if not colorir_cabos:
        return COR_CABO_PADRAO_KML
    _, cor = obter_paleta_pon(pon_num)
    return cor

# --- FUNÇÕES KML DINÂMICAS ---
def criar_kml_pontos_dinamico(nome_arquivo, pasta_nome, pontos, logger):
    kml = ET.Element(f'{{{KML_NS}}}kml')
    doc = ET.SubElement(kml, f'{{{KML_NS}}}Document')
    folder = ET.SubElement(doc, f'{{{KML_NS}}}Folder')
    nome_folder = ET.SubElement(folder, f'{{{KML_NS}}}name')
    nome_folder.text = pasta_nome
    
    for item in pontos:
        pm = ET.SubElement(folder, f'{{{KML_NS}}}Placemark')
        p_name = ET.SubElement(pm, f'{{{KML_NS}}}name')
        p_name.text = item['nome']

        if item.get('descricao'):
            descricao = ET.SubElement(pm, f'{{{KML_NS}}}description')
            descricao.text = item['descricao']
        
        if item.get('icone'):
            style = ET.SubElement(pm, f'{{{KML_NS}}}Style')
            icon_style = ET.SubElement(style, f'{{{KML_NS}}}IconStyle')
            scale = ET.SubElement(icon_style, f'{{{KML_NS}}}scale')
            scale.text = "1.2"
            icon = ET.SubElement(icon_style, f'{{{KML_NS}}}Icon')
            href = ET.SubElement(icon, f'{{{KML_NS}}}href')
            href.text = item['icone']
        
        point = ET.SubElement(pm, f'{{{KML_NS}}}Point')
        coords = ET.SubElement(point, f'{{{KML_NS}}}coordinates')
        coords.text = f"{item['coords'][0]},{item['coords'][1]},0"
        
    tree = ET.ElementTree(kml)
    tree.write(nome_arquivo, encoding='utf-8', xml_declaration=True)

def criar_kml_linhas_dinamico(nome_arquivo, pasta_nome, linhas, logger, largura=2):
    kml = ET.Element(f'{{{KML_NS}}}kml')
    doc = ET.SubElement(kml, f'{{{KML_NS}}}Document')
    folder = ET.SubElement(doc, f'{{{KML_NS}}}Folder')
    nome_folder = ET.SubElement(folder, f'{{{KML_NS}}}name')
    nome_folder.text = pasta_nome
    
    for linha in linhas:
        pm = ET.SubElement(folder, f'{{{KML_NS}}}Placemark')
        p_name = ET.SubElement(pm, f'{{{KML_NS}}}name')
        p_name.text = linha['nome']

        if linha.get('descricao'):
            descricao = ET.SubElement(pm, f'{{{KML_NS}}}description')
            descricao.text = linha['descricao']
        
        style = ET.SubElement(pm, f'{{{KML_NS}}}Style')
        line_style = ET.SubElement(style, f'{{{KML_NS}}}LineStyle')
        color = ET.SubElement(line_style, f'{{{KML_NS}}}color')
        color.text = linha.get('cor', COR_CABO_PADRAO_KML)  # Default amarelo
        width = ET.SubElement(line_style, f'{{{KML_NS}}}width')
        width.text = str(largura)
        
        ls = ET.SubElement(pm, f'{{{KML_NS}}}LineString')
        tessellate = ET.SubElement(ls, f'{{{KML_NS}}}tessellate')
        tessellate.text = '1'
        coords = ET.SubElement(ls, f'{{{KML_NS}}}coordinates')
        coords_str = " ".join([f"{lon},{lat},0" for lon, lat in linha['coords']])
        coords.text = coords_str
        
    tree = ET.ElementTree(kml)
    tree.write(nome_arquivo, encoding='utf-8', xml_declaration=True)


def _ordenar_ctos_por_rota(
    ctos,
    coord_ceo,
    roteador,
    distancia_maxima_entre_ctos,
    distancia_maxima_conexao_m=None,
):
    """Ordena CTOs de uma PON sem transformar falha de rota em linha válida."""

    pendentes = list(ctos)
    ordenadas = []
    if not pendentes:
        return ordenadas

    def chave_rota(origem, destino):
        resultado = calcular_rota_detalhada(
            roteador, origem, destino, distancia_maxima_conexao_m
        )
        if resultado.valida:
            return (0, resultado.distancia_m)
        # A distância geodésica serve apenas para uma ordenação determinística
        # quando não existe rota; o cabo continuará marcado como exceção.
        return (1, calcular_distancia_metros(*origem, *destino))

    atual = min(
        pendentes,
        key=lambda c: chave_rota(coord_ceo, c["coords_brutas"]),
    )
    ordenadas.append(atual)
    pendentes.remove(atual)

    while pendentes:
        ultima = ordenadas[-1]
        candidatos = sorted(
            pendentes,
            key=lambda cand: chave_rota(ultima["coords_brutas"], cand["coords_brutas"]),
        )
        escolhido = candidatos[0]
        resultado = calcular_rota_detalhada(
            roteador,
            ultima["coords_brutas"],
            escolhido["coords_brutas"],
            distancia_maxima_conexao_m,
        )

        if (not resultado.valida) or resultado.distancia_m > distancia_maxima_entre_ctos:
            derivacoes = []
            for origem in ordenadas:
                for cand in pendentes:
                    rota = calcular_rota_detalhada(
                        roteador,
                        origem["coords_brutas"],
                        cand["coords_brutas"],
                        distancia_maxima_conexao_m,
                    )
                    if rota.valida and rota.distancia_m <= distancia_maxima_entre_ctos:
                        derivacoes.append((rota.distancia_m, cand["id"], cand))
            if derivacoes:
                derivacoes.sort(key=lambda item: (item[0], item[1]))
                escolhido = derivacoes[0][2]

        ordenadas.append(escolhido)
        pendentes.remove(escolhido)

    return ordenadas


def _ordenar_ceos_geograficamente(ceos):
    """Ordena CEOs de forma determinística para nomenclatura/apresentação."""

    restantes = list(ceos)
    if not restantes:
        return []

    atual = min(
        restantes,
        key=lambda z: (z["coords"][0], -z["coords"][1], z["id"]),
    )
    ordenadas = [atual]
    restantes.remove(atual)

    while restantes:
        proxima = min(
            restantes,
            key=lambda z: (
                math.hypot(
                    z["coords"][0] - atual["coords"][0],
                    z["coords"][1] - atual["coords"][1],
                ),
                z["id"],
            ),
        )
        ordenadas.append(proxima)
        restantes.remove(proxima)
        atual = proxima

    return ordenadas


def _criar_modelo_capacitado(
    casas_coords,
    posicoes_ctos_manuais,
    total_ctos_planejado,
    logger,
    CONFIG,
):
    """Cria HP -> CTO -> PON -> CEO respeitando limites rígidos."""

    engenharia = CONFIG["engenharia"]
    capacidade_hp = engenharia["capacidade_hp_por_cto"]
    ctos_por_pon = engenharia["ctos_por_pon"]
    pons_por_ceo = engenharia["pons_por_ceo"]

    n_hp = len(casas_coords)
    if n_hp == 0:
        raise ClusterizacaoError("não existem HP para posicionamento")

    ctos = []
    if posicoes_ctos_manuais is not None and len(posicoes_ctos_manuais) > 0:
        centros = np.asarray(posicoes_ctos_manuais, dtype=float)
        if len(centros) * capacidade_hp < n_hp:
            raise ClusterizacaoError(
                f"correção manual insuficiente: {len(centros)} CTOs cobrem no máximo "
                f"{len(centros) * capacidade_hp} HP, mas o projeto possui {n_hp} HP"
            )
        if len(centros) < total_ctos_planejado:
            logger.warning(
                "⚠️ O arquivo manual possui %d CTOs, abaixo das %d planejadas (incluindo reserva).",
                len(centros),
                total_ctos_planejado,
            )
        labels_cto = atribuir_pontos_a_centros_capacitado(
            casas_coords, centros, capacidade_hp
        )
        logger.info(
            "🧭 %d CTOs manuais mantidas; HPs redistribuídos com limite de %d HP/CTO.",
            len(centros),
            capacidade_hp,
        )
        for idx, centro in enumerate(centros):
            indices = np.where(labels_cto == idx)[0]
            ctos.append(
                {
                    "id": f"CTO_{idx + 1:04d}",
                    "coords_brutas": (float(centro[0]), float(centro[1])),
                    "hp_indices": [int(i) for i in indices],
                }
            )
    else:
        labels_cto, clusters_cto = clusterizar_pontos_capacitado(
            casas_coords,
            total_ctos_planejado,
            capacidade_hp,
        )
        for idx, cluster in enumerate(clusters_cto):
            ctos.append(
                {
                    "id": f"CTO_{idx + 1:04d}",
                    "coords_brutas": tuple(cluster["centro"]),
                    "hp_indices": list(cluster["indices"]),
                }
            )
        logger.info(
            "✅ Clusterização capacitada HP→CTO: máximo observado %d/%d HP por CTO.",
            max(len(c["hp_indices"]) for c in ctos),
            capacidade_hp,
        )

    # CTO -> PON: a quantidade de PONs é a mínima compatível com a capacidade.
    coords_ctos = [c["coords_brutas"] for c in ctos]
    labels_pon, clusters_pon = agrupar_pontos_por_capacidade(coords_ctos, ctos_por_pon)
    pons = []
    for idx, cluster in enumerate(clusters_pon):
        cto_indices = list(cluster["indices"])
        pon_id = f"PON_{idx + 1:04d}"
        cto_ids = [ctos[i]["id"] for i in cto_indices]
        pons.append(
            {
                "id": pon_id,
                "coords_brutas": tuple(cluster["centro"]),
                "cto_ids": cto_ids,
            }
        )
        for cto_idx in cto_indices:
            ctos[cto_idx]["pon_id"] = pon_id

    # PON -> CEO: a CEO passa a respeitar rigidamente pons_por_ceo.
    coords_pons = [p["coords_brutas"] for p in pons]
    labels_ceo, clusters_ceo = agrupar_pontos_por_capacidade(coords_pons, pons_por_ceo)
    ceos = []
    for idx, cluster in enumerate(clusters_ceo):
        pon_indices = list(cluster["indices"])
        ceo_id = f"CEO_{idx + 1:04d}"
        pon_ids = [pons[i]["id"] for i in pon_indices]
        ceos.append(
            {
                "id": ceo_id,
                "coords_brutas": tuple(cluster["centro"]),
                "pon_ids": pon_ids,
            }
        )
        for pon_idx in pon_indices:
            pons[pon_idx]["ceo_id"] = ceo_id

    validacao = validar_alocacao_hierarquica(
        quantidade_hps=n_hp,
        ctos=ctos,
        pons=pons,
        ceos=ceos,
        capacidade_hp_por_cto=capacidade_hp,
        ctos_por_pon=ctos_por_pon,
        pons_por_ceo=pons_por_ceo,
    )

    return ctos, pons, ceos, validacao


def executar_posicionamento_inteligente(
    kml_poligono,
    total_ctos,
    total_pons,
    no_olt,
    nome_projeto,
    logger,
    CONFIG,
):
    casas_coords, poligonos = carregar_casas_cache(
        nome_projeto, kml_poligono, logger, CONFIG
    )
    bbox = bbox_total(poligonos)
    olt_fisica = obter_olt_fisica(CONFIG)

    engenharia = CONFIG["engenharia"]
    pontos_bbox = [olt_fisica["coords_brutas"]] if olt_fisica is not None else []
    bbox_roteamento = expandir_bbox_com_pontos(
        bbox,
        pontos_bbox,
        margem_metros=engenharia["margem_bbox_roteamento_metros"],
    )
    malha_viaria = baixar_linhas_ruas(bbox_roteamento, logger, CONFIG)
    grafo_ruas = construir_grafo_ruas(malha_viaria)
    if len(grafo_ruas) == 0:
        logger.warning(
            "⚠️ Malha viária indisponível. Cabos não serão convertidos em linhas retas; "
            "as ligações serão registradas como exceções de roteamento."
        )

    capacidade_hp = engenharia["capacidade_hp_por_cto"]
    splitter_inicial = engenharia["splitter_cto_inicial"]
    splitter_expansao = engenharia["splitter_cto_expansao"]
    ctos_por_pon = engenharia["ctos_por_pon"]
    pons_por_ceo = engenharia["pons_por_ceo"]
    distancia_maxima_snap = engenharia["distancia_maxima_snap_metros"]
    distancia_maxima_entre_ctos = engenharia["distancia_maxima_entre_ctos_metros"]
    penetracao = engenharia["penetracao_estimada"]

    # Não confia cegamente em JSON de fases anteriores: recalcula o plano com
    # a regra atual de 16 HP/CTO e a reserva configurada.
    dimensionamento_atual = calcular_dimensionamento_ftth(len(casas_coords), CONFIG)
    total_ctos_calculado = dimensionamento_atual["ctos"]
    if total_ctos != total_ctos_calculado:
        logger.warning(
            "⚠️ CTOs do JSON recalculadas pela regra atual: %d → %d.",
            total_ctos,
            total_ctos_calculado,
        )
    total_ctos = total_ctos_calculado

    logger.info(
        "🧠 Fase 6: topologia física sobre clusterização capacitada (%d HP/CTO, splitter 1x%d → 1x%d).",
        capacidade_hp,
        splitter_inicial,
        splitter_expansao,
    )

    caminho_kml_editado = resolver_arquivo_correcoes(INPUT_DIR, CONFIG)
    posicoes_ctos_manuais = None
    if caminho_kml_editado is not None:
        elementos_editados = ler_kml_corrigido_pelo_usuario(caminho_kml_editado, logger)
        coords = []
        for elemento in elementos_editados:
            nome_upper = elemento["nome"].upper()
            if "CTO" in nome_upper or "SS" in nome_upper:
                coords.append([elemento["lon"], elemento["lat"]])
        if coords:
            posicoes_ctos_manuais = np.asarray(coords, dtype=float)
            logger.info(
                "📍 Modo de correção: %d posições de CTO serão preservadas.",
                len(posicoes_ctos_manuais),
            )

    ctos, pons, ceos, validacao = _criar_modelo_capacitado(
        casas_coords,
        posicoes_ctos_manuais,
        total_ctos,
        logger,
        CONFIG,
    )

    total_ctos = len(ctos)
    hierarquia_real = recalcular_hierarquia_por_ctos(total_ctos, CONFIG)
    if total_pons != hierarquia_real["pons"]:
        logger.warning(
            "⚠️ Quantidade de PONs recalculada: %d → %d.",
            total_pons,
            hierarquia_real["pons"],
        )

    if len(pons) != hierarquia_real["pons"] or len(ceos) != hierarquia_real["ceos"]:
        raise ClusterizacaoError(
            "a hierarquia capacitada não corresponde ao dimensionamento mínimo esperado"
        )

    logger.info(
        "✅ Hierarquia validada: %d HP → %d CTOs → %d PONs → %d CEOs.",
        len(casas_coords),
        len(ctos),
        len(pons),
        len(ceos),
    )

    opcoes_visuais = CONFIG["opcoes_visuais_e_nomes"]
    nomear_auto = opcoes_visuais["nomear_cto_ceo_automaticamente"]
    colorir_cto = opcoes_visuais["colorir_cto_por_pon"]
    colorir_cabos = opcoes_visuais["colorir_cabos_por_pon"]

    # Posiciona CEOs a partir das PONs que realmente pertencem a cada uma.
    for ceo in ceos:
        lon_ceo, lat_ceo = alinhar_ponto_na_rua(
            Point(*ceo["coords_brutas"]),
            malha_viaria,
            distancia_maxima_metros=distancia_maxima_snap,
            logger=logger,
            rotulo=ceo["id"],
        )
        ceo["coords"] = (lon_ceo, lat_ceo)

    lista_olts = []
    if olt_fisica is not None:
        lon_olt, lat_olt = alinhar_ponto_na_rua(
            Point(*olt_fisica["coords_brutas"]),
            malha_viaria,
            distancia_maxima_metros=distancia_maxima_snap,
            logger=logger,
            rotulo=olt_fisica["id"],
        )
        olt_fisica["coords"] = (lon_olt, lat_olt)
        olt_fisica["referencia"] = olt_fisica["nome"]
        lista_olts.append(
            {
                "id": olt_fisica["id"],
                "nome": olt_fisica["nome"],
                "coords": olt_fisica["coords"],
                "icone": "http://maps.google.com/mapfiles/kml/shapes/target.png",
                "descricao": (
                    f"ID interno: {olt_fisica['id']}\n"
                    f"Coordenada configurada: {olt_fisica['coords_brutas'][1]:.7f}, "
                    f"{olt_fisica['coords_brutas'][0]:.7f}"
                ),
            }
        )
        logger.info(
            "🏢 OLT física configurada: %s (%.7f, %.7f).",
            olt_fisica["nome"],
            olt_fisica["coords"][1],
            olt_fisica["coords"][0],
        )
    else:
        logger.warning(
            "⚠️ Coordenadas da OLT não configuradas. O backbone será gerado apenas entre CEOs."
        )

    ceos_ordenadas = _ordenar_ceos_geograficamente(ceos)
    pons_por_id = {p["id"]: p for p in pons}
    ctos_por_id = {c["id"]: c for c in ctos}

    lista_ctos = []
    lista_ceos = []
    lista_cabos_dist = []
    lista_cabos_backbone = []
    lista_excecoes_roteamento = []
    pon_global_counter = 1
    cto_global_counter = 1
    ICONE_CEO = "http://maps.google.com/mapfiles/kml/pushpin/red-pushpin.png"

    for ceo_ordem, ceo in enumerate(ceos_ordenadas, start=1):
        pons_ceo = [pons_por_id[pid] for pid in ceo["pon_ids"]]
        pons_ceo.sort(
            key=lambda p: (
                math.hypot(
                    p["coords_brutas"][0] - ceo["coords_brutas"][0],
                    p["coords_brutas"][1] - ceo["coords_brutas"][1],
                ),
                p["id"],
            )
        )

        pon_inicial = pon_global_counter
        pon_final = pon_inicial + len(pons_ceo) - 1
        tag_sp = (
            f"SP{pon_inicial}-{pon_final}"
            if pon_inicial != pon_final
            else f"SP{pon_inicial}"
        )
        nome_ceo = f"{ceo_ordem:02d}_{no_olt}_{tag_sp}" if nomear_auto else "CEO"
        ceo["nome"] = nome_ceo
        ceo["ordem"] = ceo_ordem
        ceo["referencia"] = nome_ceo if nomear_auto else ceo["id"]
        lista_ceos.append(
            {
                "id": ceo["id"],
                "nome": nome_ceo,
                "coords": ceo["coords"],
                "icone": ICONE_CEO,
                "descricao": (
                    f"ID interno: {ceo['id']}\n"
                    f"PONs: {len(pons_ceo)}/{pons_por_ceo}"
                ),
            }
        )

        ctos_metadata_ceo = []
        for pon in pons_ceo:
            pon_numero = pon_global_counter
            pon["numero"] = pon_numero
            ctos_pon = [ctos_por_id[cid] for cid in pon["cto_ids"]]
            ctos_ordenadas = _ordenar_ctos_por_rota(
                ctos_pon,
                ceo["coords"],
                grafo_ruas,
                distancia_maxima_entre_ctos,
                distancia_maxima_snap,
            )
            pon["cto_ids"] = [c["id"] for c in ctos_ordenadas]

            icone_pon_temp, _ = obter_paleta_pon(pon_numero)
            icone_pon = (
                icone_pon_temp
                if colorir_cto
                else "http://maps.google.com/mapfiles/kml/pushpin/ylw-pushpin.png"
            )

            for ss_local, cto in enumerate(ctos_ordenadas, start=1):
                lon_cto, lat_cto = alinhar_ponto_na_rua(
                    Point(*cto["coords_brutas"]),
                    malha_viaria,
                    distancia_maxima_metros=distancia_maxima_snap,
                    logger=logger,
                    rotulo=cto["id"],
                )
                cto["coords"] = (lon_cto, lat_cto)
                cto["pon_numero"] = pon_numero
                cto["ceo_id"] = ceo["id"]
                cto["hc_estimado_teorico"] = len(cto["hp_indices"]) * penetracao
                nome_cto = (
                    f"{cto_global_counter:03d}_{no_olt}_SP{pon_numero}_SS{ss_local}"
                    if nomear_auto
                    else "CTO"
                )
                cto["nome"] = nome_cto
                cto["referencia"] = nome_cto if nomear_auto else cto["id"]

                descricao = (
                    f"ID interno: {cto['id']}\n"
                    f"HP cobertos: {len(cto['hp_indices'])}/{capacidade_hp}\n"
                    f"HC esperado (teórico): {cto['hc_estimado_teorico']:.1f}\n"
                    f"Splitter inicial: 1x{splitter_inicial}\n"
                    f"Expansão: 1x{splitter_expansao}\n"
                    f"PON: {pon_numero}"
                )
                lista_ctos.append(
                    {
                        "id": cto["id"],
                        "nome": nome_cto,
                        "coords": cto["coords"],
                        "icone": icone_pon,
                        "descricao": descricao,
                    }
                )
                ctos_metadata_ceo.append(cto)
                cto_global_counter += 1

            pon_global_counter += 1

        # Cabeamento de distribuição preserva os grupos PON já capacitados.
        for pon in pons_ceo:
            p_num = pon["numero"]
            ctos_da_pon = [ctos_por_id[cid] for cid in pon["cto_ids"]]
            if not ctos_da_pon:
                continue
            cor_cabo_pon = obter_cor_cabo_pon(p_num, colorir_cabos)
            conectadas = []

            def obter_rota(coord_origem, coord_destino):
                return calcular_rota_detalhada(
                    grafo_ruas,
                    coord_origem,
                    coord_destino,
                    distancia_maxima_snap,
                )

            def registrar_ligacao_dist(
                origem_ref,
                coord_origem,
                destino_ref,
                coord_destino,
                tipo,
                resultado=None,
            ):
                resultado = resultado or obter_rota(coord_origem, coord_destino)
                if resultado.valida:
                    dist_m = resultado.distancia_m
                    alerta = (
                        f" [⚠️ >{distancia_maxima_entre_ctos:.0f}m]"
                        if dist_m > distancia_maxima_entre_ctos
                        else ""
                    )
                    lista_cabos_dist.append(
                        {
                            "nome": (
                                f"Cabo_{tipo}_{origem_ref}_to_{destino_ref} "
                                f"({dist_m:.0f}m){alerta}"
                            ),
                            "coords": resultado.coordenadas,
                            "cor": cor_cabo_pon,
                            "descricao": f"Status de rota: {resultado.status}",
                        }
                    )
                    return resultado

                descricao = (
                    f"Status: {resultado.status}\n"
                    f"Tipo: {tipo}\n"
                    f"Origem: {origem_ref}\n"
                    f"Destino: {destino_ref}\n"
                    f"Detalhe: {resultado.mensagem or 'rota viária indisponível'}"
                )
                excecao = {
                    "status": resultado.status,
                    "tipo": tipo,
                    "origem": origem_ref,
                    "destino": destino_ref,
                    "mensagem": resultado.mensagem,
                    "distancia_origem_malha_m": resultado.distancia_origem_malha_m,
                    "distancia_destino_malha_m": resultado.distancia_destino_malha_m,
                    "coords_referencia": [list(coord_origem), list(coord_destino)],
                }
                lista_excecoes_roteamento.append(excecao)
                lista_excecoes_roteamento[-1]["escopo"] = "distribuicao"
                logger.warning(
                    "⚠️ Rota %s → %s não criada (%s).",
                    origem_ref,
                    destino_ref,
                    resultado.status,
                )
                return resultado

            for i, cto_atual in enumerate(ctos_da_pon):
                coord_atual = cto_atual["coords"]
                if i == 0:
                    registrar_ligacao_dist(
                        ceo["referencia"],
                        ceo["coords"],
                        cto_atual["referencia"],
                        coord_atual,
                        "Feed_Primario",
                    )
                    conectadas.append(cto_atual)
                    continue

                cto_ant = ctos_da_pon[i - 1]
                coord_ant = cto_ant["coords"]
                rota_seq = obter_rota(coord_ant, coord_atual)

                if (
                    rota_seq.valida
                    and rota_seq.distancia_m <= distancia_maxima_entre_ctos
                ):
                    registrar_ligacao_dist(
                        cto_ant["referencia"],
                        coord_ant,
                        cto_atual["referencia"],
                        coord_atual,
                        "Cascata",
                        resultado=rota_seq,
                    )
                    conectadas.append(cto_atual)
                    continue

                melhor = None
                for cto_con in conectadas:
                    rota_cand = obter_rota(cto_con["coords"], coord_atual)
                    if (
                        rota_cand.valida
                        and rota_cand.distancia_m <= distancia_maxima_entre_ctos
                        and (melhor is None or rota_cand.distancia_m < melhor[0])
                    ):
                        melhor = (rota_cand.distancia_m, cto_con, rota_cand)

                if melhor is not None:
                    _, cto_con, rota_cand = melhor
                    registrar_ligacao_dist(
                        cto_con["referencia"],
                        cto_con["coords"],
                        cto_atual["referencia"],
                        coord_atual,
                        "Derivacao",
                        resultado=rota_cand,
                    )
                else:
                    registrar_ligacao_dist(
                        ceo["referencia"],
                        ceo["coords"],
                        cto_atual["referencia"],
                        coord_atual,
                        "Feed_Extra",
                    )
                conectadas.append(cto_atual)

    # Backbone físico: quando a OLT possui coordenadas, ela participa da árvore
    # OLT -> CEOs. Rotas inválidas recebem penalidade para serem usadas somente
    # quando necessárias para conectar componentes e são exportadas como exceção.
    nos_backbone = [
        {
            "id": c["id"],
            "referencia": c["referencia"],
            "coords": c["coords"],
            "tipo": "CEO",
        }
        for c in ceos_ordenadas
    ]
    if olt_fisica is not None:
        nos_backbone.insert(
            0,
            {
                "id": olt_fisica["id"],
                "referencia": olt_fisica["referencia"],
                "coords": olt_fisica["coords"],
                "tipo": "OLT",
            },
        )

    if len(nos_backbone) > 1:
        G_backbone = nx.Graph()
        for no in nos_backbone:
            G_backbone.add_node(no["id"], **no)

        for n1, n2 in itertools.combinations(nos_backbone, 2):
            resultado = calcular_rota_detalhada(
                grafo_ruas,
                n1["coords"],
                n2["coords"],
                distancia_maxima_snap,
            )
            distancia_referencia = calcular_distancia_metros(
                *n1["coords"], *n2["coords"]
            )
            peso = (
                resultado.distancia_m
                if resultado.valida
                else 1_000_000_000.0 + distancia_referencia
            )
            G_backbone.add_edge(
                n1["id"],
                n2["id"],
                weight=peso,
                resultado=resultado,
                no1=n1,
                no2=n2,
            )

        mst_backbone = nx.minimum_spanning_tree(G_backbone, weight="weight")
        for _, _, data in mst_backbone.edges(data=True):
            resultado = data["resultado"]
            n1 = data["no1"]
            n2 = data["no2"]
            tipo = "Feeder_OLT" if "OLT" in (n1["tipo"], n2["tipo"]) else "Backbone"

            if resultado.valida:
                lista_cabos_backbone.append(
                    {
                        "nome": (
                            f"Cabo_{tipo}_{n1['referencia']}_to_{n2['referencia']} "
                            f"({resultado.distancia_m:.0f}m)"
                        ),
                        "coords": resultado.coordenadas,
                        "cor": "ff0000ff",
                        "descricao": f"Status de rota: {resultado.status}",
                    }
                )
            else:
                lista_excecoes_roteamento.append(
                    {
                        "escopo": "backbone",
                        "status": resultado.status,
                        "tipo": tipo,
                        "origem": n1["referencia"],
                        "destino": n2["referencia"],
                        "mensagem": resultado.mensagem,
                        "distancia_origem_malha_m": resultado.distancia_origem_malha_m,
                        "distancia_destino_malha_m": resultado.distancia_destino_malha_m,
                        "coords_referencia": [list(n1["coords"]), list(n2["coords"])],
                    }
                )
                logger.warning(
                    "⚠️ Backbone %s → %s sem rota viária (%s).",
                    n1["referencia"],
                    n2["referencia"],
                    resultado.status,
                )

    # Relatório auditável da alocação capacitada.
    relatorio = {
        "projeto": nome_projeto,
        "olt": (
            {
                "id": olt_fisica["id"],
                "nome": olt_fisica["nome"],
                "coords_configuradas": list(olt_fisica["coords_brutas"]),
                "coords_finais": list(olt_fisica["coords"]),
            }
            if olt_fisica is not None
            else None
        ),
        "roteamento": {
            "nos_malha_viaria": len(grafo_ruas),
            "bbox_consultado": list(bbox_roteamento),
            "cabos_distribuicao_validos": len(lista_cabos_dist),
            "cabos_backbone_validos": len(lista_cabos_backbone),
            "quantidade_excecoes": len(lista_excecoes_roteamento),
            "status": "OK" if not lista_excecoes_roteamento else "COM_EXCECOES",
            "excecoes": lista_excecoes_roteamento,
        },
        "regra_cto": {
            "capacidade_hp": capacidade_hp,
            "splitter_inicial": splitter_inicial,
            "splitter_expansao": splitter_expansao,
            "penetracao_estimada": penetracao,
        },
        "validacao": validacao,
        "ctos": [
            {
                "id": c["id"],
                "nome": c.get("nome", "CTO"),
                "pon_id": c["pon_id"],
                "pon_numero": c.get("pon_numero"),
                "ceo_id": c.get("ceo_id"),
                "hp_atribuidos": len(c["hp_indices"]),
                "hp_indices": c["hp_indices"],
                "coords_brutas": list(c["coords_brutas"]),
                "coords_finais": list(c.get("coords", c["coords_brutas"])),
            }
            for c in ctos
        ],
        "pons": [
            {
                "id": p["id"],
                "numero": p.get("numero"),
                "ceo_id": p["ceo_id"],
                "cto_ids": p["cto_ids"],
            }
            for p in pons
        ],
        "ceos": [
            {
                "id": c["id"],
                "nome": c.get("nome", "CEO"),
                "pon_ids": c["pon_ids"],
                "coords": list(c["coords"]),
            }
            for c in ceos_ordenadas
        ],
    }
    caminho_relatorio = OUTPUT_DIR / f"{nome_projeto} - Alocacao FTTH.json"
    caminho_relatorio.write_text(
        json.dumps(relatorio, ensure_ascii=False, indent=4), encoding="utf-8"
    )

    logger.info("📦 Exportando elementos de rede...")
    caminho_ctos = OUTPUT_DIR / f"{nome_projeto} - Caixas de Terminação Óptica (CTO).kml"
    caminho_ceos = OUTPUT_DIR / f"{nome_projeto} - Caixas de Emenda Óptica (CEO).kml"
    caminho_olts = OUTPUT_DIR / f"{nome_projeto} - OLT.kml"
    caminho_cabos_dist = OUTPUT_DIR / f"{nome_projeto} - Cabos de Distribuição.kml"
    caminho_cabos_backbone = OUTPUT_DIR / f"{nome_projeto} - Cabos de Backbone (OLT-CEOs).kml"
    caminho_excecoes = OUTPUT_DIR / f"{nome_projeto} - Excecoes de Roteamento.kml"

    criar_kml_pontos_dinamico(caminho_ctos, "CTOs Posicionadas", lista_ctos, logger)
    criar_kml_pontos_dinamico(caminho_ceos, "CEOs Posicionadas", lista_ceos, logger)
    if lista_olts:
        criar_kml_pontos_dinamico(caminho_olts, "OLT", lista_olts, logger)
    elif caminho_olts.exists():
        caminho_olts.unlink()
    criar_kml_linhas_dinamico(
        caminho_cabos_dist, "Cabos de Distribuição", lista_cabos_dist, logger
    )
    if lista_cabos_backbone:
        criar_kml_linhas_dinamico(
            caminho_cabos_backbone,
            "Cabos de Backbone e Feeder",
            lista_cabos_backbone,
            logger,
        )
    elif caminho_cabos_backbone.exists():
        caminho_cabos_backbone.unlink()

    if lista_excecoes_roteamento:
        linhas_excecao = []
        for indice, exc in enumerate(lista_excecoes_roteamento, start=1):
            origem, destino = exc["coords_referencia"]
            linhas_excecao.append(
                {
                    "nome": (
                        f"EXCECAO_{indice:03d}_{exc['status']}_"
                        f"{exc['origem']}_to_{exc['destino']}"
                    ),
                    "coords": [tuple(origem), tuple(destino)],
                    "cor": "ff0000ff",
                    "descricao": (
                        "LINHA DE REFERÊNCIA - NÃO É ROTA VÁLIDA\n"
                        f"Escopo: {exc['escopo']}\n"
                        f"Status: {exc['status']}\n"
                        f"Tipo: {exc['tipo']}\n"
                        f"Origem: {exc['origem']}\n"
                        f"Destino: {exc['destino']}\n"
                        f"Detalhe: {exc.get('mensagem') or 'rota não encontrada'}"
                    ),
                }
            )
        criar_kml_linhas_dinamico(
            caminho_excecoes,
            "Exceções de Roteamento - Referência",
            linhas_excecao,
            logger,
            largura=4,
        )
        logger.warning(
            "⚠️ %d ligação(ões) sem rota válida exportadas em %s.",
            len(lista_excecoes_roteamento),
            caminho_excecoes.name,
        )
    else:
        if caminho_excecoes.exists():
            caminho_excecoes.unlink()
        logger.info("✅ Todas as ligações selecionadas possuem rota viária válida.")

    logger.info(
        "✅ Execução concluída: %d HP, %d CTOs, %d PONs, %d CEOs e %d exceção(ões) de rota. Máx. %d HP/CTO.",
        len(casas_coords),
        len(ctos),
        len(pons),
        len(ceos),
        len(lista_excecoes_roteamento),
        validacao["maior_ocupacao_hp_cto"],
    )


def executar():
    try:
        CONFIG = carregar_config()
        arquivo_projeto = resolver_arquivo_projeto(INPUT_DIR, CONFIG)
        resolver_arquivo_correcoes(INPUT_DIR, CONFIG)
    except (ValueError, FileNotFoundError) as exc:
        print(f"❌ Erro de entrada/configuração: {exc}")
        return

    nome_projeto = arquivo_projeto.stem
    logger = configurar_logger(OUTPUT_DIR, nome_projeto)
    logger.info("Iniciando processamento do projeto: %s", nome_projeto)
    logger.info("📄 Arquivo de projeto: %s", arquivo_projeto.name)

    caminho_dados = OUTPUT_DIR / f"{nome_projeto}_dados_calculados.json"
    if not os.path.exists(caminho_dados):
        logger.error(f"Arquivo de cálculos '{caminho_dados}' não encontrado.")
        return

    with open(caminho_dados, "r", encoding="utf-8") as f:
        dados = json.load(f)

    olt = CONFIG["equipamentos"]["nome_olt_padrao"]
    try:
        executar_posicionamento_inteligente(
            str(arquivo_projeto),
            dados["ctos"],
            dados["pons"],
            olt,
            nome_projeto,
            logger,
            CONFIG,
        )
    except (ValueError, FileNotFoundError, ClusterizacaoError) as exc:
        logger.error("❌ Falha no posicionamento: %s", exc)


if __name__ == "__main__":
    executar()
