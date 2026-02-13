from __future__ import annotations

import sys

from loguru import logger


def setup_logging() -> None:
    logger.remove()
    logger.add(
        sys.stdout,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>",
        level="INFO",
    )
    logger.add("logs/trading_bot_{time:YYYY-MM-DD}.log", rotation="1 day", retention="30 days", level="DEBUG")
