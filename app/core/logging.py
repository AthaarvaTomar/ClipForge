"""Structured logging configuration for ClipForge AI (Task A13)."""

from __future__ import annotations

import logging
import sys

from app.config import settings


def setup_logging() -> None:
    """Configure root and application loggers."""
    log_level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)

    log_format = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"

    logging.basicConfig(
        level=log_level,
        format=log_format,
        datefmt=date_format,
        handlers=[logging.StreamHandler(sys.stdout)],
        force=True,
    )

    # Silence overly verbose third-party loggers if not in DEBUG mode
    if not settings.DEBUG:
        logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
        logging.getLogger("celery").setLevel(logging.INFO)


logger = logging.getLogger("clipforge")
