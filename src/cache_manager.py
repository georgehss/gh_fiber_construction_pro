"""Cache versionado das edificações detectadas para um projeto."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Optional, Sequence, Tuple

from .geo_io import hash_geometria_projeto

CACHE_SCHEMA_VERSION = 2


def caminho_cache_casas(output_dir: Path, nome_projeto: str) -> Path:
    return Path(output_dir) / f"{nome_projeto}_casas_cache.json"


def _agora_utc() -> datetime:
    return datetime.now(timezone.utc)


def _parse_data_iso(valor: str) -> datetime:
    data = datetime.fromisoformat(valor.replace("Z", "+00:00"))
    if data.tzinfo is None:
        data = data.replace(tzinfo=timezone.utc)
    return data


def carregar_cache_casas(
    output_dir: Path,
    nome_projeto: str,
    poligonos: Sequence[Dict[str, object]],
    config: Dict,
    logger=None,
) -> Optional[Tuple[list, list]]:
    """Carrega cache somente se versão, geometria e validade coincidirem."""

    caminho = caminho_cache_casas(output_dir, nome_projeto)
    if not caminho.exists():
        return None

    try:
        payload = json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        if logger:
            logger.warning("⚠️ Cache inválido (%s); será recriado.", exc)
        return None

    if not isinstance(payload, dict) or "metadata" not in payload or "pontos" not in payload:
        if logger:
            logger.info("ℹ️ Cache legado detectado; será recriado no formato da Fase 3.")
        return None

    metadata = payload.get("metadata", {})
    esperado_hash = hash_geometria_projeto(poligonos)
    esperado_versao = str(config["cache"]["versao"])

    motivos = []
    if metadata.get("schema_version") != CACHE_SCHEMA_VERSION:
        motivos.append("schema")
    if str(metadata.get("cache_version")) != esperado_versao:
        motivos.append("versão")
    if metadata.get("geometry_hash") != esperado_hash:
        motivos.append("geometria")

    try:
        expirado = _parse_data_iso(metadata["expires_at"]) <= _agora_utc()
    except (KeyError, TypeError, ValueError):
        expirado = True
    if expirado:
        motivos.append("expiração")

    if motivos:
        if logger:
            logger.info(
                "ℹ️ Cache desatualizado (%s); edificações serão consultadas novamente.",
                ", ".join(motivos),
            )
        return None

    pontos = payload.get("pontos", [])
    resumo_poligonos = payload.get("poligonos", [])
    if logger:
        logger.info("⚡ Cache válido encontrado: %s", caminho.name)
        logger.info("🏠 %d edificações carregadas do cache", len(pontos))
    return pontos, resumo_poligonos


def salvar_cache_casas(
    output_dir: Path,
    nome_projeto: str,
    poligonos: Sequence[Dict[str, object]],
    pontos: list,
    resumo_poligonos: list,
    config: Dict,
) -> Path:
    caminho = caminho_cache_casas(output_dir, nome_projeto)
    caminho.parent.mkdir(parents=True, exist_ok=True)

    agora = _agora_utc()
    expiracao = agora + timedelta(days=config["cache"]["expirar_dias"])
    payload = {
        "metadata": {
            "schema_version": CACHE_SCHEMA_VERSION,
            "cache_version": str(config["cache"]["versao"]),
            "created_at": agora.isoformat(),
            "expires_at": expiracao.isoformat(),
            "geometry_hash": hash_geometria_projeto(poligonos),
            "source": "overturemaps/building",
        },
        "poligonos": resumo_poligonos,
        "pontos": pontos,
    }
    caminho.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return caminho
