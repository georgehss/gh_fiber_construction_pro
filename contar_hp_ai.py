import xml.etree.ElementTree as ET
import math
import overturemaps
from shapely.geometry import Polygon
from shapely import wkb

def extrair_poligonos_kml(caminho_kml):
    """
    Lê o KML e extrai os polígonos como objetos geométricos do Shapely.
    """
    tree = ET.parse(caminho_kml)
    root = tree.getroot()
    ns = {'kml': 'http://www.opengis.net/kml/2.2'}
    
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
                # bounds -> (min_lon, min_lat, max_lon, max_lat)
                poligonos.append({
                    'nome': nome, 
                    'geom': poly_geom, 
                    'bbox': poly_geom.bounds
                })
                
    return poligonos

def consultar_telhados_ia(bbox, poly_geom):
    """
    Consulta a base global de edificações da Overture usando o SDK oficial.
    """
    print("   🌐 Baixando telhados da nuvem (Overture Maps IA)...")
    try:
        # Consulta oficial filtrando pelo retângulo (bbox)
        reader = overturemaps.record_batch_reader("building", bbox=bbox)
        table = reader.read_all()
        df = table.to_pandas()
        
        if df.empty:
            return 0
        
        casas_dentro = 0
        for geometry_bytes in df['geometry']:
            geom_building = wkb.loads(geometry_bytes)
            centroid = geom_building.centroid
            
            # Filtra estritamente as edificações dentro do perímetro do seu polígono
            if poly_geom.contains(centroid):
                casas_dentro += 1
                
        return casas_dentro
    except Exception as e:
        print(f"   ❌ Erro durante o download: {e}")
        return 0

def calcular_ftth(hp):
    """
    Dimensionamento GPON FTTH.
    """
    penetracao = 0.50
    hc = math.ceil(hp * penetracao)
    ctos = math.ceil(hc / 8)          # 1 CTO (8 portas) para cada 8 HCs
    pons = math.ceil(ctos / 8)        # 1 PON (Splitter 1x8) para cada 8 CTOs
    ceos = math.ceil(pons / 2)        # 1 CEO para cada 2 PONs
    return hc, ctos, pons, ceos

# --- Execução ---
if __name__ == "__main__":
    arquivo_kml = "Expansão BHS.kml"
    
    print("🔍 Lendo polígonos do KML...")
    try:
        poligonos = extrair_poligonos_kml(arquivo_kml)
        print(f"Encontrados {len(poligonos)} polígonos no arquivo.\n")
        
        for idx, poli in enumerate(poligonos, start=1):
            print("==========================================")
            print(f"📍 Polígono #{idx}: {poli['nome']}")
            print("==========================================")
            
            hp = consultar_telhados_ia(poli['bbox'], poli['geom'])
            
            if hp > 0:
                hc, ctos, pons, ceos = calcular_ftth(hp)
                print(f"🏠 HP (Telhados detectados por IA): {hp}")
                print(f"🎯 HC (Penetração 50%):             {hc}")
                print(f"📦 CTOs Necessárias (1x8):           {ctos}")
                print(f"⚡ PONs Necessárias:                 {pons}")
                print(f"🔀 CEOs Necessárias (2 PONs/CEO):     {ceos}\n")
            else:
                print("⚠️ Nenhuma edificação foi detectada dentro deste polígono.\n")
                
    except FileNotFoundError:
        print(f"❌ Arquivo '{arquivo_kml}' não foi encontrado.")
