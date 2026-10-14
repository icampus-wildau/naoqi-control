from __future__ import annotations

import logging
from typing import Protocol

logger = logging.getLogger(__name__)


class Log(Protocol):
    """What ``NaoController`` writes to. ``SessionLog`` in the app matches this."""

    def error(self, message: str) -> None: ...

    def verbose(self, message: str) -> None: ...

    def nao(self, message: str) -> None: ...


class _StdLog:
    """Stdlib stand-in when the caller does not pass its own log."""

    def error(self, message: str) -> None:
        logger.error("%s", message)

    def verbose(self, message: str) -> None:
        logger.info("%s", message)

    def nao(self, message: str) -> None:
        logger.info("NAO: %s", message)
