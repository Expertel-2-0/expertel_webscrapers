"""
Logging configuration for the web scrapers application
"""

import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional


def build_run_log_path(logs_dir: str = "logs", now: Optional[datetime] = None) -> Path:
    """
    Build the absolute path for the current run's log file.

    Files are named scraper_run_YYYY-MM-DD_HH-MM-SS.log so each execution
    produces a separate, sortable file.
    """
    timestamp = (now or datetime.now()).strftime("%Y-%m-%d_%H-%M-%S")
    base = Path(logs_dir)
    if not base.is_absolute():
        base = Path(os.getcwd()) / base
    return base / f"scraper_run_{timestamp}.log"


def setup_logging(log_level: str = "INFO", log_file: Optional[str] = None) -> logging.Logger:
    """
    Setup logging configuration for the application.

    Configures the ROOT logger so all loggers (including scraper class names
    like ATTPDFInvoiceScraperStrategy) inherit the configuration.

    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file: Optional log file path. If provided, missing parent
            directories are created automatically.

    Returns:
        Configured logger instance
    """
    level = getattr(logging, log_level.upper())

    formatter = logging.Formatter(
        fmt="%(asctime)s - %(name)s - %(levelname)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )

    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    root_logger.handlers.clear()

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)

    return logging.getLogger("web_scrapers")


def get_logger(name: str = "web_scrapers") -> logging.Logger:
    """
    Get logger instance.

    Args:
        name: Logger name

    Returns:
        Logger instance
    """
    base = "web_scrapers"
    full_name = base if name in (None, "", base) else f"{base}.{name}"
    return logging.getLogger(full_name)
