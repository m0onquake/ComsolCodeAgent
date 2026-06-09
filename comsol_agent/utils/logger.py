"""Logging utilities for COMSOL Agent."""

from __future__ import annotations

import logging
import sys
from pathlib import Path


def setup_logger(
    name: str = "comsol_agent",
    level: int = logging.INFO,
    log_file: Path | None = None,
) -> logging.Logger:
    """Set up and return a logger.

    Args:
        name: Logger name.
        level: Log level.
        log_file: Optional path to write logs to.

    Returns:
        Configured logger.
    """
    logger = logging.getLogger(name)

    if logger.handlers:
        return logger

    logger.setLevel(level)

    # Console handler with minimal formatting
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setLevel(logging.WARNING)
    console_fmt = logging.Formatter(
        "%(levelname)s: %(message)s"
    )
    console_handler.setFormatter(console_fmt)
    logger.addHandler(console_handler)

    # File handler with detailed formatting
    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(level)
        file_fmt = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s:%(lineno)d: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        file_handler.setFormatter(file_fmt)
        logger.addHandler(file_handler)

    return logger


# Default logger instance
log = setup_logger()
