"""Shared logging helpers for CLI commands and Bedrock calls."""

from __future__ import annotations

import logging

LOGGER_ROOT = "proposal_ingest"


def configure_logging(level: str = "INFO") -> logging.Logger:
    """Configure the package logger once and return it."""
    logger = logging.getLogger(LOGGER_ROOT)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        logger.addHandler(handler)
    logger.setLevel(level.upper())
    logger.propagate = False
    return logger


def get_logger(name: str) -> logging.Logger:
    """Return a child logger under the project namespace."""
    return logging.getLogger(f"{LOGGER_ROOT}.{name}")
