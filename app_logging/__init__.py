"""
App logging: rotating app.log for server/runtime events.
Use this logger across all modules.
"""
import os
import logging
from logging.handlers import RotatingFileHandler
import config


def get_logger(name: str = "app") -> logging.Logger:
    """
    Returns a logger that writes to logging/app.log.
    Format: [timestamp] [LEVEL] [module] message
    """
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)

    log_dir = config.get_log_dir()
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, "app.log")

    # Rotating: 10 MB per file, keep 5 backups
    handler = RotatingFileHandler(
        log_path,
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    handler.setLevel(logging.DEBUG)

    fmt = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler.setFormatter(fmt)
    logger.addHandler(handler)

    # Also print to stdout
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(fmt)
    logger.addHandler(console)

    return logger
