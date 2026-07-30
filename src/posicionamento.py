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

# Busca automaticamente arquivos KML ou KMZ na pasta de entrada
arquivos_kml = list(INPUT_DIR.glob("*.kml")) + list(INPUT_DIR.glob("*.kmz"))

if not arquivos_kml:
    print("❌ Erro: Nenhum arquivo KML/KMZ em data/input/")
    sys.exit(1)

# Seleciona o primeiro arquivo encontrado para processamento
arquivo_projeto = arquivos_kml[0]
nome_projeto = arquivo_projeto.stem # Pega o nome sem a extensão (ex: "Expansão Centro")

# Configurar logging PRIMEIRO
logger = configurar_logger(OUTPUT_DIR, nome_projeto)

# Validar config com ConfigValidator
CONFIG_FILE = BASE_DIR / "config.json"
try:
    CONFIG = ConfigValidator.validar(CONFIG_FILE)
except (ValueError, FileNotFoundError) as e:
    logger.error(f"❌ Erro na configuração: {e}")
    sys.exit(1)

logger.info(f"Iniciando processamento do projeto: {nome_projeto}")

# Avisar se houver múltiplos KMLs
if len(arquivos_kml) > 1:
    logger.warning(f"⚠️ Encontrados {len(arquivos_kml)} arquivos KML!")
    logger.warning(f"   Usando: {arquivo_projeto.name}")
    logger.warning(f"   Ignorando: {', '.join([f.name for f in arquivos_kml[1:]])}")

KML_NS = 'http://www.opengis.net/kml/2.2'
ET.register_namespace('', KML_NS)

# Salva o cache de casas detectadas na pasta de output
CACHE_CASAS = OUTPUT_DIR / f"{nome_projeto}_casas_cache.json"

def carregar_casas_cache():
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
    """Cria sessão HTTP com retry automático"""
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


def baixar_linhas_ruas(bbox):
    """Com timeout, retry e query otimizada"""
    logger.info("🛣️ Obtendo malha viária...")

    min_lon, min_lat, max_lon, max_lat = bbox
    
    # ✅ QUERY CORRIGIDA:
    # - Timeout aumentado para 60s (era 30s)
    # - Parênteses ao redor da query
    # - Múltiplas formas de rua para melhor cobertura
    overpass_query = f"""
[out:json][timeout:60];
(
  way["highway"]({min_lat},{min_lon},{max_lat},{max_lon});
  way["junction"]({min_lat},{min_lon},{max_lat},{max_lon});
);
out geom;
"""

    url = "https://overpass-api.de/api/interpreter"
    timeout = CONFIG['api']['overpass_timeout_segundos']
    headers = {
        'User-Agent': 'FTTH_Snapper/2.0',
        'Accept': 'application/json'
    }

    linhas_ruas = []

    try:
        # Usar sessão com retry
        sessao = criar_sessao_com_retry()
        logger.debug(f"📤 Enviando query Overpass com timeout={timeout}s")
        
        res = sessao.post(
            url, 
            data={'data': overpass_query}, 
            headers=headers,
            timeout=timeout + 5  # Timeout do requests um pouco maior que da query
        )
        res.raise_for_status()  # Verificar status HTTP

        data = res.json()
        elemento_count = len(data.get('elements', []))
        logger.info(f"✅ {elemento_count} elementos de via encontrados")

        for elem in data.get('elements', []):
            geom = elem.get('geometry', [])
            if len(geom) >= 2:
                coords = [(pt['lon'], pt['lat']) for pt in geom]
                linhas_ruas.append(LineString(coords))

        return MultiLineString(linhas_ruas) if linhas_ruas else None

    except requests.exceptions.Timeout:
        logger.warning("⚠️ Timeout na API Overpass (>60s)")
        logger.info("   Dica: Aumentar 'overpass_timeout_segundos' em config.json")
        logger.info("   Continuando com centróides das quadras")
        return None

    except requests.exceptions.HTTPError as e:
        logger.warning(f"⚠️ Erro HTTP ao obter vias: {e}")
        if res.status_code == 400:
            logger.info("   Status 400 (Bad Request) - possível problema na query")
            logger.debug(f"   Query enviada: {overpass_query}")
        logger.info("   Continuando com centróides das quadras")
        return None

    except requests.exceptions.RequestException as e:
        logger.warning(f"⚠️ Erro ao obter vias: {e}")
        logger.info("   Continuando com centróides das quadras")
        return None


def alinhar_ponto_na_rua(ponto, malha_viaria):
    if malha_viaria is None:
        return ponto.x, ponto.y
    pt_proximo = nearest_points(malha_viaria, ponto)[0]
    return pt_proximo.x, pt_proximo.y

def criar_kml_pontos(nome_arquivo, pasta_nome, pontos):
    kml = ET.Element(f'{{{KML_NS}}}kml')
    doc = ET.SubElement(kml, f'{{{KML_NS}}}Document')
    folder = ET.SubElement(doc, f'{{{KML_NS}}}Folder')
    nome_folder = ET.SubElement(folder, f'{{{KML_NS}}}name')
    nome_folder.text = pasta_nome
    
    for nome, lon, lat in pontos:
        pm = ET.SubElement(folder, f'{{{KML_NS}}}Placemark')
        p_name = ET.SubElement(pm, f'{{{KML_NS}}}name')
        p_name.text = nome
        
        point = ET.SubElement(pm, f'{{{KML_NS}}}Point')
        coords = ET.SubElement(point, f'{{{KML_NS}}}coordinates')
        coords.text = f"{lon},{lat},0"
        
    tree = ET.ElementTree(kml)
    tree.write(nome_arquivo, encoding='utf-8', xml_declaration=True)
    logger.info(f"KML '{nome_arquivo}' gerado com sucesso!")

def executar_posicionamento_inteligente(kml_poligono, total_ctos=46, total_pons=6, no_olt="N70"):
    """Com melhor nomeação e validação"""

    casas_coords = carregar_casas_cache()
    bbox = extrair_bbox_poligono(kml_poligono)
    malha_viaria = baixar_linhas_ruas(bbox)

    # Validar K-Means
    if len(casas_coords) < total_ctos:
        logger.warning(f"⚠️ Casas ({len(casas_coords)}) < CTOs ({total_ctos})")
        logger.info("   Ajustando número de CTOs...")
        total_ctos = max(1, len(casas_coords) // 2)

    logger.info(f"🧠 K-Means: {len(casas_coords)} casas → {total_ctos} CTOs")

    kmeans = KMeans(n_clusters=total_ctos, random_state=42, n_init=20)
    kmeans.fit(casas_coords)
    centros_grupos = kmeans.cluster_centers_

    # Melhor alocação
    lista_ctos = []

    for idx_cto, (centro_x, centro_y) in enumerate(centros_grupos):
        pon_num = (idx_cto // 8) + 1  # Qual PON
        ss_num = (idx_cto % 8) + 1     # Qual SubSlot

        lon_rua, lat_rua = alinhar_ponto_na_rua(
            Point(centro_x, centro_y), 
            malha_viaria
        )

        nome_cto = f"{(idx_cto+1):03d}_{no_olt}_SP{pon_num}_SS{ss_num}"
        lista_ctos.append((nome_cto, round(lon_rua, 6), round(lat_rua, 6)))
        logger.debug(f"  CTO {nome_cto}: ({lon_rua:.4f}, {lat_rua:.4f})")


    # 4. Aloca CEOs
    total_ceos = math.ceil(total_pons / 2)
    cto_pts = np.array([(c[1], c[2]) for c in lista_ctos])
    
    kmeans_ceos = KMeans(n_clusters=total_ceos, random_state=42, n_init=10)
    kmeans_ceos.fit(cto_pts)
    centros_ceos = kmeans_ceos.cluster_centers_
    
    lista_ceos = []
    for idx_ceo in range(total_ceos):
        sp_ini = (idx_ceo * 2) + 1
        sp_fim = min(sp_ini + 1, total_pons)
        tag_sp = f"SP{sp_ini}-{sp_fim}" if sp_ini != sp_fim else f"SP{sp_ini}"
        
        nome_ceo = f"{(idx_ceo + 1):02d}_{no_olt}_{tag_sp}"
        c_x, c_y = centros_ceos[idx_ceo]
        lon_rua, lat_rua = alinhar_ponto_na_rua(Point(c_x, c_y), malha_viaria)
        lista_ceos.append((nome_ceo, round(lon_rua, 6), round(lat_rua, 6)))

    # Exportar os KMLs
    logger.info("📦 Exportando elementos de rede...")
    caminho_ctos = OUTPUT_DIR / f"{nome_projeto} - Caixas de Terminação Óptica (CTO).kml"
    caminho_ceos = OUTPUT_DIR / f"{nome_projeto} - Caixas de Emenda Óptica (CEO).kml"

    criar_kml_pontos(caminho_ctos, "CTOs Posicionadas", lista_ctos)
    criar_kml_pontos(caminho_ceos, "CEOs Posicionadas", lista_ceos)
    
    logger.info(f"✅ {len(lista_ctos)} CTOs posicionadas com sucesso")


if __name__ == "__main__":
    caminho_dados = OUTPUT_DIR / f"{nome_projeto}_dados_calculados.json"
    
    if not os.path.exists(caminho_dados):
        logger.error(f"Arquivo de cálculos '{caminho_dados}' não encontrado.")
        logger.info("Execute 'contagem_hp_ai.py' primeiro!")
        sys.exit(1)
        
    with open(caminho_dados, 'r', encoding='utf-8') as f:
        dados = json.load(f)
        
    olt = CONFIG['equipamentos']['nome_olt_padrao']
        
    logger.info(f"Lendo parâmetros calculados: {dados['ctos']} CTOs e {dados['pons']} PONs.")
    
    executar_posicionamento_inteligente(
        str(arquivo_projeto), 
        total_ctos=dados['ctos'], 
        total_pons=dados['pons'],
        no_olt=olt
    )