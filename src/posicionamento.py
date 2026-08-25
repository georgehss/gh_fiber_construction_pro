import xml.etree.ElementTree as ET
import math, json, os, requests, itertools
from shapely.geometry import Polygon, Point, MultiLineString, LineString
from shapely.ops import nearest_points
from sklearn.cluster import KMeans
import numpy as np
from pathlib import Path
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from config_validator import ConfigValidator
from logger_config import configurar_logger
import networkx as nx

# Identifica a pasta raiz do projeto de forma dinâmica
BASE_DIR = Path(__file__).resolve().parent.parent

INPUT_DIR = BASE_DIR / "data" / "input"
OUTPUT_DIR = BASE_DIR / "data" / "output"
CONFIG_FILE = BASE_DIR / "config.json"

KML_NS = 'http://www.opengis.net/kml/2.2'
ET.register_namespace('', KML_NS)

def carregar_casas_cache(nome_projeto, logger):
    CACHE_CASAS = OUTPUT_DIR / f"{nome_projeto}_casas_cache.json"
    if not os.path.exists(CACHE_CASAS):
        raise FileNotFoundError(f"❌ Cache '{CACHE_CASAS}' não encontrado! Rode primeiro o script 'contagem_hp_ai.py'.")
    with open(CACHE_CASAS, 'r', encoding='utf-8') as f:
        pontos = json.load(f)
    return np.array(pontos)

def extrair_bbox_poligono(caminho_kml):
    tree = ET.parse(caminho_kml)
    root = tree.getroot()
    ns = {'kml': KML_NS}
    placemark = root.find('.//kml:Placemark', ns)
    coords_elem = placemark.find('.//kml:coordinates', ns)
    raw_coords = coords_elem.text.strip().split()
    lista_lon_lat = []
    for pt in raw_coords:
        partes = pt.split(',')
        if len(partes) >= 2:
            lista_lon_lat.append((float(partes[0]), float(partes[1])))
    poly = Polygon(lista_lon_lat)
    return poly.bounds

def criar_sessao_com_retry():
    sessao = requests.Session()
    retry_strategy = Retry(
        total=3, 
        backoff_factor=1, 
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["HEAD", "GET", "POST"] 
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    sessao.mount("http://", adapter)
    sessao.mount("https://", adapter)
    return sessao

def baixar_linhas_ruas(bbox, logger, CONFIG):
    logger.info("🛣️ Obtendo malha viária...")
    min_lon, min_lat, max_lon, max_lat = bbox
    overpass_query = f"""
[out:json][timeout:60];
(way["highway"]({min_lat},{min_lon},{max_lat},{max_lon});
 way["junction"]({min_lat},{min_lon},{max_lat},{max_lon}););
out geom;
"""
    url = "https://overpass-api.de/api/interpreter"
    timeout = CONFIG['api'].get('overpass_timeout_segundos', 60)
    headers = {'User-Agent': 'FTTH_Snapper/2.0', 'Accept': 'application/json'}
    linhas_ruas = []
    try:
        sessao = criar_sessao_com_retry()
        res = sessao.post(url, data={'data': overpass_query}, headers=headers, timeout=timeout + 5)
        res.raise_for_status()
        data = res.json()
        for elem in data.get('elements', []):
            geom = elem.get('geometry', [])
            if len(geom) >= 2:
                coords = [(pt['lon'], pt['lat']) for pt in geom]
                linhas_ruas.append(LineString(coords))
        return MultiLineString(linhas_ruas) if linhas_ruas else None
    except requests.exceptions.RequestException as e:
        logger.warning(f"⚠️ Erro ao obter vias: {e}")
        return None

def alinhar_ponto_na_rua(ponto, malha_viaria):
    if malha_viaria is None:
        return ponto.x, ponto.y
    pt_proximo = nearest_points(malha_viaria, ponto)[0]
    return pt_proximo.x, pt_proximo.y

def construir_grafo_ruas(malha_viaria):
    G = nx.Graph()
    if malha_viaria is None:
        return G
    linhas = malha_viaria.geoms if hasattr(malha_viaria, 'geoms') else [malha_viaria]
    for linha in linhas:
        coords = list(linha.coords)
        for i in range(len(coords) - 1):
            p1, p2 = coords[i], coords[i+1]
            dist = math.hypot(p2[0] - p1[0], p2[1] - p1[1])
            G.add_edge(p1, p2, weight=dist)
    return G

def calcular_rota_pela_rua(G, pt_origem, pt_destino):
    if len(G.nodes) == 0:
        return [pt_origem, pt_destino] 
    nodes = list(G.nodes)
    no_origem = min(nodes, key=lambda n: math.hypot(n[0]-pt_origem[0], n[1]-pt_origem[1]))
    no_destino = min(nodes, key=lambda n: math.hypot(n[0]-pt_destino[0], n[1]-pt_destino[1]))
    try:
        caminho = nx.shortest_path(G, source=no_origem, target=no_destino, weight='weight')
        rota_completa = [pt_origem] + caminho + [pt_destino]
        rota_limpa = []
        for p in rota_completa:
            if not rota_limpa or p != rota_limpa[-1]:
                rota_limpa.append(p)
        return rota_limpa
    except nx.NetworkXNoPath:
        return [pt_origem, pt_destino]

def calcular_distancia_metros(lon1, lat1, lon2, lat2):
    R = 6371000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = math.sin(delta_phi/2.0)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda/2.0)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    return R * c

def calcular_metragem_rota(rota):
    distancia = 0
    for i in range(len(rota) - 1):
        distancia += calcular_distancia_metros(rota[i][0], rota[i][1], rota[i+1][0], rota[i+1][1])
    return distancia

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
        
        style = ET.SubElement(pm, f'{{{KML_NS}}}Style')
        line_style = ET.SubElement(style, f'{{{KML_NS}}}LineStyle')
        color = ET.SubElement(line_style, f'{{{KML_NS}}}color')
        color.text = linha.get('cor', 'ff00ffff') # Default amarelo
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


def executar_posicionamento_inteligente(kml_poligono, total_ctos, total_pons, no_olt, nome_projeto, logger, CONFIG):
    casas_coords = carregar_casas_cache(nome_projeto, logger)
    bbox = extrair_bbox_poligono(kml_poligono)
    malha_viaria = baixar_linhas_ruas(bbox, logger, CONFIG)
    grafo_ruas = construir_grafo_ruas(malha_viaria)

    if len(casas_coords) < total_ctos:
        logger.warning(f"⚠️ Casas ({len(casas_coords)}) < CTOs ({total_ctos})")
        total_ctos = max(1, len(casas_coords) // 2)

    logger.info(f"🧠 IA Nível 1: Mapeando {total_ctos} posições brutas para CTOs")
    kmeans_ctos = KMeans(n_clusters=total_ctos, random_state=42, n_init=20)
    kmeans_ctos.fit(casas_coords)
    posicoes_ctos_brutas = kmeans_ctos.cluster_centers_

    ctos_por_pon = CONFIG['engenharia'].get('ctos_por_pon', 8)
    pons_por_ceo = CONFIG['engenharia'].get('pons_por_ceo', 2)
    total_ceos = math.ceil(total_pons / pons_por_ceo)

    logger.info(f"🧠 IA Nível 2: Mapeando {total_ceos} Zonas de Cobertura de CEOs")
    if total_ceos > 1:
        kmeans_ceos = KMeans(n_clusters=total_ceos, random_state=42, n_init=20)
        labels_ceos = kmeans_ceos.fit_predict(posicoes_ctos_brutas)
    else:
        labels_ceos = np.zeros(total_ctos, dtype=int)

    # ==========================================================
    # PRÉ-PROCESSAMENTO: ORDENAÇÃO GEOGRÁFICA DAS ZONAS DE CEO
    # ==========================================================
    zonas_ceos_brutas = []
    for ceo_idx in range(total_ceos):
        ctos_desta_zona = posicoes_ctos_brutas[labels_ceos == ceo_idx]
        if len(ctos_desta_zona) == 0: 
            continue
            
        media_lon = sum(c[0] for c in ctos_desta_zona) / len(ctos_desta_zona)
        media_lat = sum(c[1] for c in ctos_desta_zona) / len(ctos_desta_zona)
        lon_ceo, lat_ceo = alinhar_ponto_na_rua(Point(media_lon, media_lat), malha_viaria)
        
        zonas_ceos_brutas.append({
            "coords": (lon_ceo, lat_ceo),
            "ctos_brutas": ctos_desta_zona
        })
        
    zonas_ordenadas = []
    if len(zonas_ceos_brutas) > 0:
        # Pega a zona mais a Noroeste como ponto de partida
        atual = min(zonas_ceos_brutas, key=lambda z: (z['coords'][0], -z['coords'][1]))
        zonas_ordenadas.append(atual)
        zonas_ceos_brutas.remove(atual)
        
        # Conecta geograficamente a CEO mais próxima na sequência
        while zonas_ceos_brutas:
            mais_proximo = min(zonas_ceos_brutas, key=lambda z: math.hypot(z['coords'][0]-atual['coords'][0], z['coords'][1]-atual['coords'][1]))
            zonas_ordenadas.append(mais_proximo)
            zonas_ceos_brutas.remove(mais_proximo)
            atual = mais_proximo

    lista_ctos = []
    lista_ceos = []
    lista_cabos_dist = []
    lista_cabos_backbone = []
    
    pon_global_counter = 1
    cto_global_counter = 1
    ICONE_CEO = "http://maps.google.com/mapfiles/kml/pushpin/red-pushpin.png"

    # ==========================================================
    # PROCESSAMENTO POR ZONA DE COBERTURA ORDENADA
    # ==========================================================
    for ceo_idx, zona in enumerate(zonas_ordenadas):
        ctos_desta_zona = zona['ctos_brutas']
        coord_ceo = zona['coords']
        
        pons_nesta_ceo = math.ceil(len(ctos_desta_zona) / ctos_por_pon)
        pon_inicial = pon_global_counter
        pon_final = pon_inicial + pons_nesta_ceo - 1
        
        tag_sp = f"SP{pon_inicial}-{pon_final}" if pon_inicial != pon_final else f"SP{pon_inicial}"
        nome_ceo = f"{(ceo_idx + 1):02d}_{no_olt}_{tag_sp}"
        lista_ceos.append({"nome": nome_ceo, "coords": coord_ceo, "icone": ICONE_CEO})

        # ==========================================================
        # CONSTRUTOR DE PON BASEADO NAS RUAS (A Mágica da Sequência)
        # ==========================================================
        ctos_pendentes = [tuple(p) for p in ctos_desta_zona]
        pon_atual = pon_inicial
        ctos_nesta_pon = []
        ctos_metadata = []

        while ctos_pendentes:
            if not ctos_nesta_pon:
                # 1. A CTO 01 da PON sempre será a fisicamente mais próxima da CEO pelas ruas
                atual = min(ctos_pendentes, key=lambda p: calcular_metragem_rota(calcular_rota_pela_rua(grafo_ruas, coord_ceo, p)))
                ctos_nesta_pon.append(atual)
                ctos_pendentes.remove(atual)
            else:
                ultima_cto = ctos_nesta_pon[-1]
                melhor_cand, menor_dist = None, float('inf')
                
                # 2. Busca a próxima CTO seguindo a rua (Daisy-Chain)
                for cand in ctos_pendentes:
                    rota = calcular_rota_pela_rua(grafo_ruas, ultima_cto, cand)
                    dist = calcular_metragem_rota(rota)
                    if dist < menor_dist:
                        menor_dist = dist; melhor_cand = cand
                
                if menor_dist <= 150:
                    ctos_nesta_pon.append(melhor_cand)
                    ctos_pendentes.remove(melhor_cand)
                else:
                    # 3. Derivação de emergência durante a criação do agrupamento
                    melhor_cand_deriv, menor_dist_deriv = None, float('inf')
                    for c_in_pon in ctos_nesta_pon:
                        for cand in ctos_pendentes:
                            rota = calcular_rota_pela_rua(grafo_ruas, c_in_pon, cand)
                            dist = calcular_metragem_rota(rota)
                            if dist < menor_dist_deriv:
                                menor_dist_deriv = dist; melhor_cand_deriv = cand
                    
                    if menor_dist_deriv <= 150:
                        ctos_nesta_pon.append(melhor_cand_deriv)
                        ctos_pendentes.remove(melhor_cand_deriv)
                    else:
                        # 4. Falha de Isolamento: Força a adição para que a regra de CEO crie um Feed_Extra depois
                        ctos_nesta_pon.append(melhor_cand)
                        ctos_pendentes.remove(melhor_cand)
                        
            # Se a PON encheu ou acabaram as caixas, exporta e numera
            if len(ctos_nesta_pon) == ctos_por_pon or not ctos_pendentes:
                icone_pon, cor_cabo_pon = obter_paleta_pon(pon_atual)
                
                for idx_local, (cx, cy) in enumerate(ctos_nesta_pon):
                    lon_cto, lat_cto = alinhar_ponto_na_rua(Point(cx, cy), malha_viaria)
                    nome_cto = f"{cto_global_counter:03d}_{no_olt}_SP{pon_atual}_SS{idx_local + 1}"
                    
                    lista_ctos.append({"nome": nome_cto, "coords": (lon_cto, lat_cto), "icone": icone_pon})
                    ctos_metadata.append({"nome": nome_cto, "pon": pon_atual, "lon": lon_cto, "lat": lat_cto})
                    cto_global_counter += 1
                    
                pon_atual += 1
                ctos_nesta_pon = []
            
        # ==========================================================
        # LÓGICA DE CABEAMENTO FÍSICO COM CORES
        # ==========================================================
        for p_num in range(pon_inicial, pon_final + 1):
            ctos_da_pon = [c for c in ctos_metadata if c['pon'] == p_num]
            if not ctos_da_pon: continue
            
            _, cor_cabo_pon = obter_paleta_pon(p_num)
            conectadas = []
            
            def adicionar_cabo_dist(origem_nome, coord_origem, destino_nome, coord_destino, tipo):
                rota = calcular_rota_pela_rua(grafo_ruas, coord_origem, coord_destino)
                dist_m = calcular_metragem_rota(rota)
                alerta = " [⚠️ >150m]" if dist_m > 150 else ""
                nome_cabo = f"Cabo_{tipo}_{origem_nome}_to_{destino_nome} ({dist_m:.0f}m){alerta}"
                lista_cabos_dist.append({"nome": nome_cabo, "coords": rota, "cor": cor_cabo_pon})

            for i, cto_atual in enumerate(ctos_da_pon):
                coord_atual = (cto_atual['lon'], cto_atual['lat'])
                if i == 0:
                    adicionar_cabo_dist(nome_ceo, coord_ceo, cto_atual['nome'], coord_atual, "Feed_Primario")
                    conectadas.append(cto_atual)
                else:
                    cto_ant = ctos_da_pon[i-1]
                    coord_ant = (cto_ant['lon'], cto_ant['lat'])
                    rota_seq = calcular_rota_pela_rua(grafo_ruas, coord_ant, coord_atual)
                    dist_seq = calcular_metragem_rota(rota_seq)

                    if dist_seq <= 150:
                        nome_cabo = f"Cabo_Cascata_{cto_ant['nome']}_to_{cto_atual['nome']} ({dist_seq:.0f}m)"
                        lista_cabos_dist.append({"nome": nome_cabo, "coords": rota_seq, "cor": cor_cabo_pon})
                        conectadas.append(cto_atual)
                    else:
                        melhor_derivacao, menor_dist_derivacao, melhor_rota = None, float('inf'), None
                        for cto_con in conectadas:
                            coord_con = (cto_con['lon'], cto_con['lat'])
                            rota_cand = calcular_rota_pela_rua(grafo_ruas, coord_con, coord_atual)
                            dist_cand = calcular_metragem_rota(rota_cand)
                            if dist_cand <= 150 and dist_cand < menor_dist_derivacao:
                                menor_dist_derivacao, melhor_derivacao, melhor_rota = dist_cand, cto_con, rota_cand

                        if melhor_derivacao:
                            nome_cabo = f"Cabo_Derivacao_{melhor_derivacao['nome']}_to_{cto_atual['nome']} ({menor_dist_derivacao:.0f}m)"
                            lista_cabos_dist.append({"nome": nome_cabo, "coords": melhor_rota, "cor": cor_cabo_pon})
                            conectadas.append(cto_atual)
                        else:
                            adicionar_cabo_dist(nome_ceo, coord_ceo, cto_atual['nome'], coord_atual, "Feed_Extra")
                            conectadas.append(cto_atual)

        pon_global_counter += pons_nesta_ceo

    # ==========================================================
    # INTERLIGAÇÃO DAS CEOs (BACKBONE COM COR ÚNICA)
    # ==========================================================
    if len(lista_ceos) > 1:
        G_backbone = nx.Graph()
        for c1, c2 in itertools.combinations(lista_ceos, 2):
            rota = calcular_rota_pela_rua(grafo_ruas, c1['coords'], c2['coords'])
            dist_real = calcular_metragem_rota(rota)
            G_backbone.add_edge(c1['nome'], c2['nome'], weight=dist_real, coord1=c1['coords'], coord2=c2['coords'])
            
        mst_backbone = nx.minimum_spanning_tree(G_backbone, weight='weight')
        for u, v, data in mst_backbone.edges(data=True):
            rota = calcular_rota_pela_rua(grafo_ruas, data['coord1'], data['coord2'])
            dist_real = calcular_metragem_rota(rota)
            lista_cabos_backbone.append({
                "nome": f"Cabo_Backbone_{u}_to_{v} ({dist_real:.0f}m)",
                "coords": rota,
                "cor": "ff0000ff" # Vermelho intenso exclusivo para Backbone
            })

    logger.info("📦 Exportando elementos de rede...")
    
    caminho_ctos = OUTPUT_DIR / f"{nome_projeto} - Caixas de Terminação Óptica (CTO).kml"
    caminho_ceos = OUTPUT_DIR / f"{nome_projeto} - Caixas de Emenda Óptica (CEO).kml"
    caminho_cabos_dist = OUTPUT_DIR / f"{nome_projeto} - Cabos de Distribuição.kml"
    caminho_cabos_backbone = OUTPUT_DIR / f"{nome_projeto} - Cabos de Backbone (CEOs).kml"

    criar_kml_pontos_dinamico(caminho_ctos, "CTOs Posicionadas", lista_ctos, logger)
    criar_kml_pontos_dinamico(caminho_ceos, "CEOs Posicionadas", lista_ceos, logger)
    
    criar_kml_linhas_dinamico(caminho_cabos_dist, "Cabos de Distribuição", lista_cabos_dist, logger)
    if lista_cabos_backbone:
        criar_kml_linhas_dinamico(caminho_cabos_backbone, "Cabos de Backbone", lista_cabos_backbone, logger)
    
    logger.info(f"✅ Execução Concluída! {len(lista_ctos)} CTOs e {len(lista_ceos)} CEOs posicionadas.")

def executar():
    try:
        CONFIG = ConfigValidator.validar(CONFIG_FILE)
    except (ValueError, FileNotFoundError) as e:
        print(f"❌ Erro na configuração: {e}")
        return
    arquivos_kml = list(INPUT_DIR.glob("*.kml")) + list(INPUT_DIR.glob("*.kmz"))
    if not arquivos_kml:
        print("❌ Erro: Nenhum arquivo KML/KMZ em data/input/")
        return

    arquivo_projeto = arquivos_kml[0]
    nome_projeto = arquivo_projeto.stem
    logger = configurar_logger(OUTPUT_DIR, nome_projeto)
    logger.info(f"Iniciando processamento do projeto: {nome_projeto}")
    
    caminho_dados = OUTPUT_DIR / f"{nome_projeto}_dados_calculados.json"
    if not os.path.exists(caminho_dados):
        logger.error(f"Arquivo de cálculos '{caminho_dados}' não encontrado.")
        return 
        
    with open(caminho_dados, 'r', encoding='utf-8') as f:
        dados = json.load(f)
        
    olt = CONFIG['equipamentos']['nome_olt_padrao']
    executar_posicionamento_inteligente(str(arquivo_projeto), dados['ctos'], dados['pons'], olt, nome_projeto, logger, CONFIG)

if __name__ == "__main__":
    executar()