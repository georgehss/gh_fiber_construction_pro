#!/usr/bin/env python3
"""Validação manual do config.json usando a mesma regra da aplicação."""

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.config import carregar_config
CONFIG_FILE = ROOT_DIR / "config.json"


def main() -> int:
    print(f"Validando: {CONFIG_FILE}")
    try:
        carregar_config(CONFIG_FILE)
    except (FileNotFoundError, ValueError) as exc:
        print(f"ERRO: {exc}")
        return 1

    print("OK: configuração válida.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
