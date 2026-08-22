import xml.etree.ElementTree as ET
import math, json, os, requests, sys, logging
from shapely.geometry import Polygon, Point, MultiLineString, LineString
from shapely.ops import nearest_points
from sklearn.cluster import KMeans
import numpy as np
from pathlib import Path
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from config_validator import ConfigValidator
from logger_config import configurar_logger

# Identifica a pasta raiz do projeto de forma dinâmica
BASE_DIR = Path(__file__).resolve().parent.parent

# Define os caminhos das pastas de dados
INPUT_DIR = BASE_DIR / "data" / "input"
OUTPUT_DIR = BASE_DIR / "data" / "output"
CONFIG_FILE = BASE_DIR / "config.json"

KML_NS = 'http://www.opengis.net/kml/2.2'
ET.register_namespace('', KML_NS)


def carregar_casas_cache(nome_projeto, logger):
    CACHE_CASAS = OUTPUT_DIR / f"{nome_projeto}_casas_cache.json"
    
    if not os.path.exists(CACHE_CASAS):
        raise FileNotFoundError(f"❌ Cache '{CACHE_CASAS}' não encontrado! Rode primeiro o script 'contagem_hp_ai.py'.")
    
    logger.info(f"⚡ Carregando casas do cache local: {CACHE_CASAS.name}")
    with open(CACHE_CASAS, 'r', encoding='utf-8') as f:
        pontos = json.load(f)
    logger.info(f"✅ {len(pontos)} casas carregadas instantaneamente.")
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
(
  way["highway"]({min_lat},{min_lon},{max_lat},{max_lon});
  way["junction"]({min_lat},{min_lon},{max_lat},{max_lon});
);
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
        logger.info(f"✅ {len(data.get('elements', []))} elementos de via encontrados")

        for elem in data.get('elements', []):
            geom = elem.get('geometry', [])
            if len(geom) >= 2:
                coords = [(pt['lon'], pt['lat']) for pt in geom]
                linhas_ruas.append(LineString(coords))

        return MultiLineString(linhas_ruas) if linhas_ruas else None

    except requests.exceptions.RequestException as e:
        logger.warning(f"⚠️ Erro ao obter vias: {e}")
        logger.info("   Continuando com centróides das quadras")
        return None

def alinhar_ponto_na_rua(ponto, malha_viaria):
    if malha_viaria is None:
        return ponto.x, ponto.y
    pt_proximo = nearest_points(malha_viaria, ponto)[0]
    return pt_proximo.x, pt_proximo.y

# --- FUNÇÃO CORRIGIDA: Ordenar caixas geograficamente ---
def ordenar_por_proximidade(pontos):
    if len(pontos) == 0: return pontos
    
    # A MÁGICA AQUI: Converte as matrizes do NumPy para tuplas padrão do Python
    pontos_lista = [tuple(p) for p in pontos]
    
    # Inicia pela caixa mais ao Noroeste (menor longitude, maior latitude)
    atual = min(pontos_lista, key=lambda p: (p[0], -p[1]))
    ordenados = [atual]
    pontos_lista.remove(atual)

    # Vai conectando na caixa mais próxima sucessivamente
    while pontos_lista:
        mais_proximo = min(pontos_lista, key=lambda p: math.hypot(p[0]-atual[0], p[1]-atual[1]))
        ordenados.append(mais_proximo)
        pontos_lista.remove(mais_proximo)
        atual = mais_proximo

    return ordenados

# --- Função KML suportando ícones coloridos ---
def criar_kml_pontos(nome_arquivo, pasta_nome, pontos, logger, url_icone=None):
    kml = ET.Element(f'{{{KML_NS}}}kml')
    doc = ET.SubElement(kml, f'{{{KML_NS}}}Document')
    
    # Define o estilo visual (Tachão Colorido)
    if url_icone:
        style = ET.SubElement(doc, f'{{{KML_NS}}}Style', id="estiloPersonalizado")
        icon_style = ET.SubElement(style, f'{{{KML_NS}}}IconStyle')
        scale = ET.SubElement(icon_style, f'{{{KML_NS}}}scale')
        scale.text = "1.2" # Um pouco maior pra destacar
        icon = ET.SubElement(icon_style, f'{{{KML_NS}}}Icon')
        href = ET.SubElement(icon, f'{{{KML_NS}}}href')
        href.text = url_icone

    folder = ET.SubElement(doc, f'{{{KML_NS}}}Folder')
    nome_folder = ET.SubElement(folder, f'{{{KML_NS}}}name')
    nome_folder.text = pasta_nome
    
    for nome, lon, lat in pontos:
        pm = ET.SubElement(folder, f'{{{KML_NS}}}Placemark')
        p_name = ET.SubElement(pm, f'{{{KML_NS}}}name')
        p_name.text = nome
        
        # Aplica a cor
        if url_icone:
            style_url = ET.SubElement(pm, f'{{{KML_NS}}}styleUrl')
            style_url.text = "#estiloPersonalizado"
        
        point = ET.SubElement(pm, f'{{{KML_NS}}}Point')
        coords = ET.SubElement(point, f'{{{KML_NS}}}coordinates')
        coords.text = f"{lon},{lat},0"
        
    tree = ET.ElementTree(kml)
    tree.write(nome_arquivo, encoding='utf-8', xml_declaration=True)
    logger.info(f"KML '{nome_arquivo}' gerado com sucesso!")


def executar_posicionamento_inteligente(kml_poligono, total_ctos, total_pons, no_olt, nome_projeto, logger, CONFIG):
    casas_coords = carregar_casas_cache(nome_projeto, logger)
    bbox = extrair_bbox_poligono(kml_poligono)
    malha_viaria = baixar_linhas_ruas(bbox, logger, CONFIG)

    if len(casas_coords) < total_ctos:
        logger.warning(f"⚠️ Casas ({len(casas_coords)}) < CTOs ({total_ctos})")
        total_ctos = max(1, len(casas_coords) // 2)

    logger.info(f"🧠 K-Means: {len(casas_coords)} casas → {total_ctos} CTOs")
    
    # 1. Gera os agrupamentos desordenados
    kmeans = KMeans(n_clusters=total_ctos, random_state=42, n_init=20)
    kmeans.fit(casas_coords)
    centros_grupos = kmeans.cluster_centers_

    # 2. Ordena os agrupamentos criando um caminho lógico no mapa
    centros_ordenados = ordenar_por_proximidade(centros_grupos)

    lista_ctos = []
    lista_ctos_metadata = [] # Para nos ajudar a centralizar as CEOs depois
    ctos_por_pon = CONFIG['engenharia'].get('ctos_por_pon', 8)
    pons_por_ceo = CONFIG['engenharia'].get('pons_por_ceo', 2)

    for idx_cto, (centro_x, centro_y) in enumerate(centros_ordenados):
        pon_num = (idx_cto // ctos_por_pon) + 1  
        ss_num = (idx_cto % ctos_por_pon) + 1     

        lon_rua, lat_rua = alinhar_ponto_na_rua(Point(centro_x, centro_y), malha_viaria)
        nome_cto = f"{(idx_cto+1):03d}_{no_olt}_SP{pon_num}_SS{ss_num}"
        
        lista_ctos.append((nome_cto, round(lon_rua, 6), round(lat_rua, 6)))
        lista_ctos_metadata.append({"pon": pon_num, "lon": lon_rua, "lat": lat_rua})
        logger.debug(f"  CTO {nome_cto}: ({lon_rua:.4f}, {lat_rua:.4f})")

    # 3. Posicionamento Estratégico das CEOs
    total_ceos = math.ceil(total_pons / pons_por_ceo)
    lista_ceos = []
    
    for idx_ceo in range(total_ceos):
        pon_inicial = (idx_ceo * pons_por_ceo) + 1
        pon_final = min(pon_inicial + pons_por_ceo - 1, total_pons)
        
        # Filtra apenas as CTOs que esta CEO vai alimentar
        ctos_da_ceo = [c for c in lista_ctos_metadata if pon_inicial <= c['pon'] <= pon_final]
        
        if not ctos_da_ceo:
            continue
            
        # O centro da CEO agora é o centro geométrico exato das suas CTOs
        media_lon = sum(c['lon'] for c in ctos_da_ceo) / len(ctos_da_ceo)
        media_lat = sum(c['lat'] for c in ctos_da_ceo) / len(ctos_da_ceo)
        
        lon_rua, lat_rua = alinhar_ponto_na_rua(Point(media_lon, media_lat), malha_viaria)
        
        tag_sp = f"SP{pon_inicial}-{pon_final}" if pon_inicial != pon_final else f"SP{pon_inicial}"
        nome_ceo = f"{(idx_ceo + 1):02d}_{no_olt}_{tag_sp}"
        
        lista_ceos.append((nome_ceo, round(lon_rua, 6), round(lat_rua, 6)))

    logger.info("📦 Exportando elementos de rede...")
    
    # --- Cores dos Ícones do Google Earth ---
    ICONE_CTO = "http://maps.google.com/mapfiles/kml/pushpin/green-pushpin.png"
    ICONE_CEO = "http://maps.google.com/mapfiles/kml/pushpin/red-pushpin.png"

    caminho_ctos = OUTPUT_DIR / f"{nome_projeto} - Caixas de Terminação Óptica (CTO).kml"
    caminho_ceos = OUTPUT_DIR / f"{nome_projeto} - Caixas de Emenda Óptica (CEO).kml"

    # Criando os arquivos KML enviando a respectiva cor de ícone
    criar_kml_pontos(caminho_ctos, "CTOs Posicionadas", lista_ctos, logger, url_icone=ICONE_CTO)
    criar_kml_pontos(caminho_ceos, "CEOs Posicionadas", lista_ceos, logger, url_icone=ICONE_CEO)
    
    logger.info(f"✅ {len(lista_ctos)} CTOs e {len(lista_ceos)} CEOs posicionadas com sucesso!")


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
    
    if len(arquivos_kml) > 1:
        logger.warning(f"⚠️ Encontrados {len(arquivos_kml)} arquivos KML!")
        logger.warning(f"   Usando: {arquivo_projeto.name}")
        logger.warning(f"   Ignorando: {', '.join([f.name for f in arquivos_kml[1:]])}")
    
    caminho_dados = OUTPUT_DIR / f"{nome_projeto}_dados_calculados.json"
    
    if not os.path.exists(caminho_dados):
        logger.error(f"Arquivo de cálculos '{caminho_dados}' não encontrado.")
        logger.info("Execute 'contagem_hp_ai.py' primeiro!")
        return 
        
    with open(caminho_dados, 'r', encoding='utf-8') as f:
        dados = json.load(f)
        
    olt = CONFIG['equipamentos']['nome_olt_padrao']
    logger.info(f"Lendo parâmetros calculados: {dados['ctos']} CTOs e {dados['pons']} PONs.")
    
    executar_posicionamento_inteligente(
        kml_poligono=str(arquivo_projeto), 
        total_ctos=dados['ctos'], 
        total_pons=dados['pons'],
        no_olt=olt,
        nome_projeto=nome_projeto,
        logger=logger,
        CONFIG=CONFIG
    )

if __name__ == "__main__":
    executar()