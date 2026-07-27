import xml.etree.ElementTree as ET
import math, os, json, sys, overturemaps
from shapely.geometry import Polygon
from shapely import wkb
from pathlib import Path

# 1. Identifica a pasta raiz do projeto de forma dinâmica
# Como o script está em src/, o parent dele é a raiz do projeto
BASE_DIR = Path(__file__).resolve().parent.parent

# 2. Define os caminhos das pastas de dados
INPUT_DIR = BASE_DIR / "data" / "input"
OUTPUT_DIR = BASE_DIR / "data" / "output"

# 3. Busca automaticamente arquivos KML ou KMZ na pasta de entrada
arquivos_kml = list(INPUT_DIR.glob("*.kml")) + list(INPUT_DIR.glob("*.kmz"))

if not arquivos_kml:
    print("Erro: Nenhum arquivo KML ou KMZ encontrado em data/input/")
    sys.exit()

# Seleciona o primeiro arquivo encontrado para processamento
arquivo_projeto = arquivos_kml[0]
nome_projeto = arquivo_projeto.stem # Pega o nome sem a extensão (ex: "Expansão Centro")

# Lê as configurações globais do projeto
CONFIG_FILE = BASE_DIR / "config.json"
with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
    CONFIG = json.load(f)

print(f"Iniciando processamento do projeto: {nome_projeto}")

KML_NS = 'http://www.opengis.net/kml/2.2'
ET.register_namespace('', KML_NS)

# Salva o cache de casas detectadas na pasta de output
CACHE_CASAS = OUTPUT_DIR / f"{nome_projeto}_casas_cache.json"

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

def obter_posicoes_casas(bbox, poly_geom):
    """
    Verifica se já existe o cache local no computador.
    Se não existir, baixa da Overture IA e salva o arquivo JSON e o KML.
    """
    if os.path.exists(CACHE_CASAS):
        print(f"   ⚡ Cache local encontrado ('{CACHE_CASAS}')! Carregando do disco...")
        with open(CACHE_CASAS, 'r', encoding='utf-8') as f:
            pontos = json.load(f)
        return pontos

    print("   🌐 Baixando telhados da nuvem (Overture Maps IA)...")
    pontos_casas = []
    try:
        reader = overturemaps.record_batch_reader("building", bbox=bbox)
        table = reader.read_all()
        df = table.to_pandas()
        
        if not df.empty:
            for geometry_bytes in df['geometry']:
                geom_building = wkb.loads(geometry_bytes)
                centroid = geom_building.centroid
                
                if poly_geom.contains(centroid):
                    pontos_casas.append([round(centroid.x, 6), round(centroid.y, 6)])
                    
        # Salva o arquivo de cache JSON
        with open(CACHE_CASAS, 'w', encoding='utf-8') as f:
            json.dump(pontos_casas, f, indent=2)
        print(f"   💾 Cache criado com sucesso: '{CACHE_CASAS}' ({len(pontos_casas)} casas)")
        
        # Cria também um KML visual das casas para abrir no QGIS/Google Earth
        caminho_kml_casas = OUTPUT_DIR / f"{nome_projeto} - 0.0. Residencias (HP Detectadas).kml"
        gerar_kml_casas(caminho_kml_casas, pontos_casas)
        
        return pontos_casas
    except Exception as e:
        print(f"   ❌ Erro durante o download: {e}")
        return []

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

def calcular_ftth(hp):
    eng = CONFIG['engenharia']
    penetracao = eng['penetracao_estimada']
    cap_cto = eng['capacidade_splitter_cto']
    cap_pon = eng['ctos_por_pon']
    cap_ceo = eng['pons_por_ceo']
    
    hc = math.ceil(hp * penetracao)
    ctos = math.ceil(hc / cap_cto)
    pons = math.ceil(ctos / cap_pon)
    ceos = math.ceil(pons / cap_ceo)
    return hc, ctos, pons, ceos

# --- Execução ---
if __name__ == "__main__":
    # Usa o arquivo KML/KMZ encontrado automaticamente na pasta data/input/
    arquivo_kml = str(arquivo_projeto)
    
    print("🔍 Lendo polígonos do KML...")
    try:
        poligonos = extrair_poligonos_kml(arquivo_kml)
        print(f"Encontrados {len(poligonos)} polígonos no arquivo.\n")
        
        for idx, poli in enumerate(poligonos, start=1):
            print("==========================================")
            print(f"📍 Polígono #{idx}: {poli['nome']}")
            print("==========================================")
            
            casas = obter_posicoes_casas(poli['bbox'], poli['geom'])
            hp = len(casas)
            
            if hp > 0:
                hc, ctos, pons, ceos = calcular_ftth(hp)
                print(f"\n🏠 HP (Telhados detectados por IA): {hp}")
                print(f"🎯 HC (Penetração 50%):             {hc}")
                print(f"📦 CTOs Necessárias (1x8):           {ctos}")
                print(f"⚡ PONs Necessárias:                 {pons}")
                print(f"🔀 CEOs Necessárias:     {ceos}\n")

                # Salva os cálculos para o script de posicionamento ler depois
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
