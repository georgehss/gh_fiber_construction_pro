import xml.etree.ElementTree as ET
import math
import json
import os
import requests
from shapely.geometry import Polygon, Point, MultiLineString, LineString
from shapely.ops import nearest_points
from sklearn.cluster import KMeans
import numpy as np

KML_NS = 'http://www.opengis.net/kml/2.2'
ET.register_namespace('', KML_NS)

CACHE_CASAS = "casas_detectadas_cache.json"

def carregar_casas_cache():
    if not os.path.exists(CACHE_CASAS):
        raise FileNotFoundError(f"❌ Cache '{CACHE_CASAS}' não encontrado! Rode primeiro o script 'contagem_hp_ai.py'.")
    
    print(f"   ⚡ Carregando casas do cache local ('{CACHE_CASAS}')...")
    with open(CACHE_CASAS, 'r', encoding='utf-8') as f:
        pontos = json.load(f)
    print(f"   🏠 {len(pontos)} casas carregadas instantaneamente.")
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

def baixar_linhas_ruas(bbox):
    print("   🛣️ Obtenção da malha viária (vias/ruas) para alinhamento nos postes...")
    min_lon, min_lat, max_lon, max_lat = bbox
    overpass_query = f"""
    [out:json][timeout:30];
    way["highway"]({min_lat},{min_lon},{max_lat},{max_lon});
    out geometry;
    """
    url = "https://overpass-api.de/api/interpreter"
    headers = {'User-Agent': 'FTTH_Snapper/1.0'}
    
    linhas_ruas = []
    try:
        res = requests.post(url, data={'data': overpass_query}, headers=headers)
        if res.status_code == 200:
            data = res.json()
            for elem in data.get('elements', []):
                geom = elem.get('geometry', [])
                if len(geom) >= 2:
                    coords = [(pt['lon'], pt['lat']) for pt in geom]
                    linhas_ruas.append(LineString(coords))
    except Exception as e:
        print(f"   ⚠️ Erro ao obter vias ({e}). CTOs ficarão no centro das quadras.")
        
    return MultiLineString(linhas_ruas) if linhas_ruas else None

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
    print(f"✅ Arquivo '{nome_arquivo}' gerado com sucesso!")

def executar_posicionamento_inteligente(kml_poligono, total_ctos=46, total_pons=6, no_olt="N70"):
    # 1. Carrega casas do cache gerado pelo 'contagem_hp_ai.py'
    casas_coords = carregar_casas_cache()
    bbox = extrair_bbox_poligono(kml_poligono)
    malha_viaria = baixar_linhas_ruas(bbox)
    
    print(f"\n   🧠 Agrupando {len(casas_coords)} casas ➔ {total_ctos} CTOs via K-Means...")
    
    # 2. Agrupamento K-Means
    kmeans = KMeans(n_clusters=total_ctos, random_state=42, n_init=10)
    kmeans.fit(casas_coords)
    centros_grupos = kmeans.cluster_centers_
    
    # 3. Aloca CTOs nas ruas/postes
    lista_ctos = []
    cto_counter = 1
    
    for pon in range(total_pons):
        sp_num = pon + 1
        for ss in range(1, 9):
            if len(lista_ctos) < total_ctos:
                idx = len(lista_ctos)
                centro_x, centro_y = centros_grupos[idx]
                
                lon_rua, lat_rua = alinhar_ponto_na_rua(Point(centro_x, centro_y), malha_viaria)
                nome_cto = f"{cto_counter:03d}_{no_olt}_SP{sp_num}_SS{ss}"
                lista_ctos.append((nome_cto, round(lon_rua, 6), round(lat_rua, 6)))
                cto_counter += 1

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
    print("\n📦 Exportando elementos de rede...")
    criar_kml_pontos("Caixas de Terminação Óptica (CTO).kml", "CTOs Posicionadas", lista_ctos)
    criar_kml_pontos("Caixas de Emenda Óptica (CEO).kml", "CEOs Posicionadas", lista_ceos)

if __name__ == "__main__":
    executar_posicionamento_inteligente("Expansão BHS.kml", total_ctos=46, total_pons=6)
