import xml.etree.ElementTree as ET
import math, os, json, sys, overturemaps, logging
from shapely.geometry import Polygon
from shapely import wkb
from pathlib import Path
from config_validator import ConfigValidator
from logger_config import configurar_logger


# Identifica a pasta raiz do projeto de forma dinâmica
# Como o script está em src/, o parent dele é a raiz do projeto
BASE_DIR = Path(__file__).resolve().parent.parent

# Define os caminhos das pastas de dados
INPUT_DIR = BASE_DIR / "data" / "input"
OUTPUT_DIR = BASE_DIR / "data" / "output"
CONFIG_FILE = BASE_DIR / "config.json"

KML_NS = 'http://www.opengis.net/kml/2.2'
ET.register_namespace('', KML_NS)

def extrair_poligonos_kml(caminho_kml):
    tree = ET.parse(caminho_kml)
    root = tree.getroot()
    ns = {'kml': KML_NS}
    
    poligonos = []
    for placemark in root.findall('.//kml:Placemark', ns):
        nome_elem = placemark.find('kml:name', ns)
        nome = nome_elem.text if nome_elem is not None else "Polígono sem título"
        
        coords_elem = placemark.find('.//kml:coordinates', ns)
        if coords_elem is not None and coords_elem.text:
            raw_coords = coords_elem.text.strip().split()
            lista_lon_lat = []
            
            for pt in raw_coords:
                partes = pt.split(',')
                if len(partes) >= 2:
                    lon, lat = float(partes[0]), float(partes[1])
                    lista_lon_lat.append((lon, lat))
            
            if len(lista_lon_lat) >= 3:
                poly_geom = Polygon(lista_lon_lat)
                poligonos.append({
                    'nome': nome, 
                    'geom': poly_geom, 
                    'bbox': poly_geom.bounds
                })
                
    return poligonos

def obter_posicoes_casas(bbox, poly_geom, nome_projeto, logger, CONFIG):
    """Baixa casas da Overture com tratamento de erro melhorado"""
    cache_file = OUTPUT_DIR / f"{nome_projeto}_casas_cache.json"

    if os.path.exists(cache_file):
        logger.info(f"⚡ Cache local encontrado: {cache_file.name}")
        with open(cache_file, 'r', encoding='utf-8') as f:
            pontos = json.load(f)
        logger.info(f" {len(pontos)} casas carregadas do cache")
        return pontos

    logger.info("🌐 Baixando edificações da nuvem (Overture Maps)...")

    try:
        # Se não achar no config.json, assume 60 segundos por padrão e segue a vida
        reader = overturemaps.record_batch_reader("building", bbox=bbox)
        table = reader.read_all()
        df = table.to_pandas()

        pontos_casas = []
        if not df.empty:
            for geometry_bytes in df['geometry']:
                geom_building = wkb.loads(geometry_bytes)
                centroid = geom_building.centroid

                if poly_geom.contains(centroid):
                    pontos_casas.append([round(centroid.x, 6), round(centroid.y, 6)])

        with open(cache_file, 'w', encoding='utf-8') as f:
            json.dump(pontos_casas, f, indent=2)

        logger.info(f"💾 Cache criado: {len(pontos_casas)} casas detectadas")
        return pontos_casas

    except Exception as e:
        logger.error(f"❌ Erro ao baixar edificações: {e}", exc_info=True)
        raise

def gerar_kml_casas(nome_arquivo, pontos):
    kml = ET.Element(f'{{{KML_NS}}}kml')
    doc = ET.SubElement(kml, f'{{{KML_NS}}}Document')
    folder = ET.SubElement(doc, f'{{{KML_NS}}}Folder')
    nome_folder = ET.SubElement(folder, f'{{{KML_NS}}}name')
    nome_folder.text = "Residências HP (IA)"
    
    for idx, (lon, lat) in enumerate(pontos, start=1):
        pm = ET.SubElement(folder, f'{{{KML_NS}}}Placemark')
        p_name = ET.SubElement(pm, f'{{{KML_NS}}}name')
        p_name.text = f"HP_{idx:03d}"
        
        point = ET.SubElement(pm, f'{{{KML_NS}}}Point')
        coords = ET.SubElement(point, f'{{{KML_NS}}}coordinates')
        coords.text = f"{lon},{lat},0"
        
    tree = ET.ElementTree(kml)
    tree.write(nome_arquivo, encoding='utf-8', xml_declaration=True)
    print(f"   📄 KML com marcadores das casas salvo em: '{nome_arquivo}'")

def calcular_ftth(hp, CONFIG):
    eng = CONFIG['engenharia']
    penetracao = eng['penetracao_estimada']
    cap_cto = eng['capacidade_splitter_cto']
    cap_pon = eng['ctos_por_pon']
    cap_ceo = eng['pons_por_ceo']
    
    hc = math.ceil(hp * penetracao)
    ctos = math.ceil(hc / cap_cto)
    pons = math.ceil(ctos / cap_pon)
    ceos = math.ceil(pons / cap_ceo)
    return {
        "hc": hc,
        "ctos": ctos,
        "pons": pons,
        "ceos": ceos
    }

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

    if len(arquivos_kml) > 1:
        logger.warning(f"⚠️ Encontrados {len(arquivos_kml)} arquivos KML!")
        logger.warning(f"   Usando: {arquivo_projeto.name}")
        logger.warning(f"   Ignorando: {', '.join([f.name for f in arquivos_kml[1:]])}")

    print(f"Iniciando processamento do projeto: {nome_projeto}")

    arquivo_kml = str(arquivo_projeto)
    print("🔍 Lendo polígonos do KML...")
    
    try:
        poligonos = extrair_poligonos_kml(arquivo_kml)
        print(f"Encontrados {len(poligonos)} polígonos no arquivo.\n")
        
        for idx, poli in enumerate(poligonos, start=1):
            print("==========================================")
            print(f"📍 Polígono #{idx}: {poli['nome']}")
            print("==========================================")
            
            # AJUSTE 3: Passando as variáveis criadas aqui dentro para a função lá em cima
            casas = obter_posicoes_casas(poli['bbox'], poli['geom'], nome_projeto, logger, CONFIG)
            hp = len(casas)
            
            if hp > 0:
                # AJUSTE 4: Passando o CONFIG
                dados_calculados = calcular_ftth(hp, CONFIG)
                hc, ctos, pons, ceos = dados_calculados['hc'], dados_calculados['ctos'], dados_calculados['pons'], dados_calculados['ceos']
                print(f"\n🏠 HP (Telhados detectados por IA): {hp}")
                print(f"🎯 HC (Penetração 50%):             {hc}")
                print(f"📦 CTOs Necessárias (1x8):           {ctos}")
                print(f"⚡ PONs Necessárias:                 {pons}")
                print(f"🔀 CEOs Necessárias:     {ceos}\n")

                dados_projeto = {
                    "hp": hp,
                    "hc": hc,
                    "ctos": ctos,
                    "pons": pons,
                    "ceos": ceos
                }
                caminho_dados = OUTPUT_DIR / f"{nome_projeto}_dados_calculados.json"
                with open(caminho_dados, 'w', encoding='utf-8') as f:
                    json.dump(dados_projeto, f, indent=4)

            else:
                print("⚠️ Nenhuma edificação foi detectada dentro deste polígono.\n")
        
    except FileNotFoundError:
        print(f"❌ Arquivo '{arquivo_kml}' não foi encontrado.")

if __name__ == "__main__":
    executar()