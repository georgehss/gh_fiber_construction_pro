import zipfile
from pathlib import Path

import pytest

from src.geo_io import (
    bbox_total,
    extrair_poligonos,
    extrair_pontos,
    resolver_arquivo_correcoes,
    resolver_arquivo_projeto,
)

KML_MULTI = '''<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <Placemark>
      <name>Ponto que não é polígono</name>
      <Point><coordinates>-44.30,-2.50,0</coordinates></Point>
    </Placemark>
    <Placemark>
      <name>Setores</name>
      <MultiGeometry>
        <Polygon>
          <outerBoundaryIs><LinearRing><coordinates>
            -44.40,-2.60,0 -44.30,-2.60,0 -44.30,-2.50,0 -44.40,-2.50,0 -44.40,-2.60,0
          </coordinates></LinearRing></outerBoundaryIs>
        </Polygon>
        <Polygon>
          <outerBoundaryIs><LinearRing><coordinates>
            -44.20,-2.40,0 -44.10,-2.40,0 -44.10,-2.30,0 -44.20,-2.30,0 -44.20,-2.40,0
          </coordinates></LinearRing></outerBoundaryIs>
          <innerBoundaryIs><LinearRing><coordinates>
            -44.18,-2.38,0 -44.16,-2.38,0 -44.16,-2.36,0 -44.18,-2.36,0 -44.18,-2.38,0
          </coordinates></LinearRing></innerBoundaryIs>
        </Polygon>
      </MultiGeometry>
    </Placemark>
  </Document>
</kml>
'''

KML_PONTOS = '''<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2"><Document>
  <Placemark><name>CTO 01</name><Point><coordinates>-44.3,-2.5,0</coordinates></Point></Placemark>
  <Placemark><name>CEO 01</name><Point><coordinates>-44.2,-2.4,0</coordinates></Point></Placemark>
</Document></kml>
'''


def test_parser_ignora_point_e_le_multigeometry(tmp_path):
    caminho = tmp_path / "projeto.kml"
    caminho.write_text(KML_MULTI, encoding="utf-8")

    poligonos = extrair_poligonos(caminho)

    assert len(poligonos) == 2
    assert all(item["nome"].startswith("Setores") for item in poligonos)
    assert bbox_total(poligonos) == pytest.approx((-44.40, -2.60, -44.10, -2.30))
    # O segundo polígono preserva o buraco interno.
    assert len(poligonos[1]["geom"].interiors) == 1


def test_kmz_real_e_suportado(tmp_path):
    caminho = tmp_path / "projeto.kmz"
    with zipfile.ZipFile(caminho, "w") as zf:
        zf.writestr("files/outro.txt", "x")
        zf.writestr("doc.kml", KML_MULTI)

    poligonos = extrair_poligonos(caminho)

    assert len(poligonos) == 2


def test_kmz_sem_kml_e_rejeitado(tmp_path):
    caminho = tmp_path / "invalido.kmz"
    with zipfile.ZipFile(caminho, "w") as zf:
        zf.writestr("readme.txt", "sem kml")

    with pytest.raises(ValueError, match="não contém nenhum arquivo KML"):
        extrair_poligonos(caminho)


def test_extrai_pontos_de_kmz_de_correcao(tmp_path):
    caminho = tmp_path / "Projeto Corrigido.kmz"
    with zipfile.ZipFile(caminho, "w") as zf:
        zf.writestr("doc.kml", KML_PONTOS)

    pontos = extrair_pontos(caminho)

    assert pontos == [
        {"nome": "CTO 01", "lat": -2.5, "lon": -44.3},
        {"nome": "CEO 01", "lat": -2.4, "lon": -44.2},
    ]


def test_resolvedor_exclui_arquivo_de_correcao(tmp_path):
    projeto = tmp_path / "Area.kml"
    projeto.write_text(KML_MULTI, encoding="utf-8")
    correcao = tmp_path / "Area Corrigida.kml"
    correcao.write_text(KML_PONTOS, encoding="utf-8")
    config = {"entrada": {"arquivo_projeto": None, "arquivo_correcoes": None}}

    assert resolver_arquivo_projeto(tmp_path, config) == projeto
    assert resolver_arquivo_correcoes(tmp_path, config) == correcao


def test_multiplos_projetos_exigem_configuracao_explicita(tmp_path):
    (tmp_path / "A.kml").write_text(KML_MULTI, encoding="utf-8")
    (tmp_path / "B.kml").write_text(KML_MULTI, encoding="utf-8")
    config = {"entrada": {"arquivo_projeto": None, "arquivo_correcoes": None}}

    with pytest.raises(ValueError, match="Mais de um arquivo de projeto"):
        resolver_arquivo_projeto(tmp_path, config)


def test_arquivo_explicito_remove_ambiguidade(tmp_path):
    (tmp_path / "A.kml").write_text(KML_MULTI, encoding="utf-8")
    escolhido = tmp_path / "B.kml"
    escolhido.write_text(KML_MULTI, encoding="utf-8")
    config = {"entrada": {"arquivo_projeto": "B.kml", "arquivo_correcoes": None}}

    assert resolver_arquivo_projeto(tmp_path, config) == escolhido
