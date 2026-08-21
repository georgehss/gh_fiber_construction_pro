# src/logger_config.py
import logging
from pathlib import Path
from datetime import datetime

def configurar_logger(output_dir: Path, nome_projeto: str) -> logging.Logger:
    """
    Configura logging estruturado
    """
    # Criar diretório de logs se não existir
    log_dir = output_dir / "logs"
    log_dir.mkdir(exist_ok=True)

    # Nome do arquivo de log com timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = log_dir / f"{nome_projeto}_{timestamp}.log"

    # Criar logger
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.DEBUG)

    # AJUSTE: Limpar handlers antigos se existirem, para evitar duplicação!
    if logger.hasHandlers():
        logger.handlers.clear()

    # Handler para arquivo
    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_handler.setLevel(logging.DEBUG)

    # Handler para console
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)

    # Formato detalhado
    formatter = logging.Formatter(
        '%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    logger.info(f"📝 Logging iniciado para projeto: {nome_projeto}")
    logger.info(f"📁 Arquivo de log: {log_file}")

    return logger