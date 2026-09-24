import inspect
import json
import xml.etree.ElementTree as ET
from pathlib import Path

from shapely import wkb

from .cache_manager import carregar_cache_casas, salvar_cache_casas
from .config import carregar_config
from .dimensionamento import calcular_dimensionamento_ftth
from .geo_io import extrair_poligonos, resolver_arquivo_projeto
from .logger_config import configurar_logger

BASE_DIR = Path(__file__).resolve().parent.parent
INPUT_DIR = BASE_DIR / "data" / "input"
OUTPUT_DIR = BASE_DIR / "data" / "output"
KML_NS = "http://www.opengis.net/kml/2.2"
ET.register_namespace("", KML_NS)


def extrair_poligonos_kml(caminho_kml):
    """Compatibilidade com a API anterior; agora aceita KML e KMZ."""
    return extrair_poligonos(Path(caminho_kml))


def criar_reader_overture(overturemaps_module, bbox, timeout_segundos, logger=None):
    """Cria o reader Overture aplicando timeout quando a versão suporta."""

    kwargs = {"bbox": bbox}
    parametros_timeout = []

    try:
        assinatura = inspect.signature(overturemaps_module.record_batch_reader)
        for parametro in ("connect_timeout", "request_timeout"):
            if parametro in assinatura.parameters:
                kwargs[parametro] = timeout_segundos
                parametros_timeout.append(parametro)
    except (TypeError, ValueError):
        pass

    if logger is not None:
        if parametros_timeout:
            logger.debug(
                "Timeout Overture aplicado (%ss) em: %s",
                timeout_segundos,
                ", ".join(parametros_timeout),
            )
        else:
            logger.warning(
                "⚠️ A versão instalada de overturemaps não expõe parâmetros "
                "de timeout em record_batch_reader; o limite configurado não "
                "pode ser aplicado por esta API."
            )

    return overturemaps_module.record_batch_reader("building", **kwargs)


def _consultar_posicoes_poligono(bbox, poly_geom, logger, config):
    """Consulta edificações Overture e devolve centroides dentro do polígono."""

    import overturemaps

    timeout_overture = config["api"]["overture_timeout_segundos"]
    reader = criar_reader_overture(overturemaps, bbox, timeout_overture, logger=logger)
    table = reader.read_all()

    pontos = []
    if table.num_rows == 0:
        return pontos

    # Evita conversão integral para DataFrame; a geometria já está disponível
    # como coluna Arrow e pode ser convertida diretamente para objetos Python.
    try:
        geometrias = table.column("geometry").to_pylist()
    except (KeyError, ValueError):
        # Mantém compatibilidade com versões/tabelas que só expõem to_pandas().
        df = table.to_pandas()
        geometrias = [] if df.empty else df["geometry"].tolist()

    for geometry_bytes in geometrias:
        if geometry_bytes is None:
            continue
        try:
            geom_building = wkb.loads(geometry_bytes)
        except Exception:
            logger.debug("Geometria Overture inválida ignorada.", exc_info=True)
            continue

        centroid = geom_building.centroid
        if poly_geom.covers(centroid):
            pontos.append([round(centroid.x, 6), round(centroid.y, 6)])

    return pontos


def obter_posicoes_casas_projeto(poligonos, nome_projeto, logger, config):
    """Obtém HPs de todos os polígonos com cache validado por geometria/versão."""

    cache = carregar_cache_casas(
        OUTPUT_DIR, nome_projeto, poligonos, config, logger=logger
    )
    if cache is not None:
        return cache

    logger.info("🌐 Baixando edificações da nuvem (Overture Maps)...")
    pontos_unicos = {}
    resumo_poligonos = []

    try:
        for indice, poligono in enumerate(poligonos, start=1):
            logger.info(
                "🔎 Consultando polígono %d/%d: %s",
                indice,
                len(poligonos),
                poligono["nome"],
            )
            pontos_poligono = _consultar_posicoes_poligono(
                poligono["bbox"], poligono["geom"], logger, config
            )
            for lon, lat in pontos_poligono:
                pontos_unicos[(lon, lat)] = [lon, lat]

            resumo_poligonos.append(
                {
                    "indice": indice,
                    "nome": poligono["nome"],
                    "bbox": [round(v, 8) for v in poligono["bbox"]],
                    "hp_detectados": len(pontos_poligono),
                }
            )

        pontos = list(pontos_unicos.values())
        caminho_cache = salvar_cache_casas(
            OUTPUT_DIR,
            nome_projeto,
            poligonos,
            pontos,
            resumo_poligonos,
            config,
        )
        logger.info(
            "💾 Cache criado: %d edificações únicas em %s",
            len(pontos),
            caminho_cache.name,
        )
        return pontos, resumo_poligonos

    except Exception as exc:
        logger.error("❌ Erro ao consultar/processar edificações: %s", exc, exc_info=True)
        raise


def obter_posicoes_casas(bbox, poly_geom, nome_projeto, logger, CONFIG):
    """Compatibilidade com a função anterior para um único polígono."""
    pontos, _ = obter_posicoes_casas_projeto(
        [{"nome": nome_projeto, "bbox": bbox, "geom": poly_geom}],
        nome_projeto,
        logger,
        CONFIG,
    )
    return pontos


def gerar_kml_casas(nome_arquivo, pontos):
    kml = ET.Element(f"{{{KML_NS}}}kml")
    doc = ET.SubElement(kml, f"{{{KML_NS}}}Document")
    folder = ET.SubElement(doc, f"{{{KML_NS}}}Folder")
    nome_folder = ET.SubElement(folder, f"{{{KML_NS}}}name")
    nome_folder.text = "Edificações consideradas como HP"

    for idx, (lon, lat) in enumerate(pontos, start=1):
        pm = ET.SubElement(folder, f"{{{KML_NS}}}Placemark")
        p_name = ET.SubElement(pm, f"{{{KML_NS}}}name")
        p_name.text = f"HP_{idx:03d}"

        point = ET.SubElement(pm, f"{{{KML_NS}}}Point")
        coords = ET.SubElement(point, f"{{{KML_NS}}}coordinates")
        coords.text = f"{lon},{lat},0"

    ET.ElementTree(kml).write(nome_arquivo, encoding="utf-8", xml_declaration=True)


def calcular_ftth(hp, CONFIG):
    """Compatibilidade com a API histórica; delega ao módulo de dimensionamento."""
    return calcular_dimensionamento_ftth(hp, CONFIG)


def executar():
    try:
        config = carregar_config()
        arquivo_projeto = resolver_arquivo_projeto(INPUT_DIR, config)
    except (ValueError, FileNotFoundError) as exc:
        print(f"❌ Erro de entrada/configuração: {exc}")
        return

    nome_projeto = arquivo_projeto.stem
    logger = configurar_logger(OUTPUT_DIR, nome_projeto)
    logger.info("Iniciando processamento do projeto: %s", nome_projeto)
    logger.info("📄 Arquivo de projeto: %s", arquivo_projeto.name)

    try:
        print("🔍 Lendo polígonos do projeto...")
        poligonos = extrair_poligonos(arquivo_projeto)
        print(f"Encontrados {len(poligonos)} polígonos válidos.\n")

        pontos, resumo_poligonos = obter_posicoes_casas_projeto(
            poligonos, nome_projeto, logger, config
        )
        hp = len(pontos)

        for resumo in resumo_poligonos:
            print(
                f"📍 Polígono #{resumo['indice']}: {resumo['nome']} "
                f"→ {resumo['hp_detectados']} edificações"
            )

        if hp == 0:
            print("\n⚠️ Nenhuma edificação foi detectada dentro da área do projeto.")
            return

        dados_calculados = calcular_ftth(hp, config)
        hc = dados_calculados["hc"]
        ctos = dados_calculados["ctos"]
        pons = dados_calculados["pons"]
        ceos = dados_calculados["ceos"]
        dim = dados_calculados["dimensionamento"]

        eng = config["engenharia"]
        penetracao_pct = eng["penetracao_estimada"] * 100
        reserva_pct = dim["reserva_capacidade_percentual"] * 100

        print(f"\n🏠 HP (edificações Overture únicas): {hp}")
        print(f"🎯 HC esperado (Penetração {penetracao_pct:g}%): {hc}")
        print(
            f"📐 Regra física da CTO: até {dim['capacidade_hp_por_cto']} HP "
            f"por caixa"
        )
        print(
            f"🔌 Splitter CTO: inicial 1x{dim['splitter_cto_inicial']} "
            f"→ expansão 1x{dim['splitter_cto_expansao']}"
        )
        print(
            f"🛡️ Reserva física: {reserva_pct:g}% → "
            f"{dim['demanda_hp_planejada']} HP planejados"
        )
        print(
            f"📦 CTOs Necessárias: {ctos} | cobertura instalada: "
            f"{dim['capacidade_hp_instalada']} HP"
        )
        print(
            f"👥 Capacidade HC inicial: {dim['capacidade_hc_inicial']} | "
            f"após expansão: {dim['capacidade_hc_expansao']}"
        )
        if dim["expansao_splitter_necessaria_no_cenario_estimado"]:
            print(
                f"⚠️ O HC estimado excede em {dim['deficit_hc_inicial']} a capacidade "
                "dos splitters iniciais; haverá necessidade de expansão."
            )
        print(f"⚡ PONs Necessárias: {pons}")
        print(f"🔀 CEOs Necessárias: {ceos}\n")

        dados_projeto = {
            "projeto": nome_projeto,
            "arquivo_entrada": arquivo_projeto.name,
            "quantidade_poligonos": len(poligonos),
            "poligonos": resumo_poligonos,
            "hp": hp,
            "hc": hc,
            "ctos": ctos,
            "pons": pons,
            "ceos": ceos,
            "dimensionamento": dados_calculados["dimensionamento"],
        }
        caminho_dados = OUTPUT_DIR / f"{nome_projeto}_dados_calculados.json"
        caminho_dados.write_text(
            json.dumps(dados_projeto, ensure_ascii=False, indent=4), encoding="utf-8"
        )

        caminho_hps = OUTPUT_DIR / f"{nome_projeto} - Residências HP.kml"
        gerar_kml_casas(caminho_hps, pontos)
        logger.info("📄 KML de HPs salvo em: %s", caminho_hps.name)

    except (ValueError, FileNotFoundError) as exc:
        logger.error("❌ Falha ao processar o projeto: %s", exc)
        print(f"❌ {exc}")


if __name__ == "__main__":
    executar()
