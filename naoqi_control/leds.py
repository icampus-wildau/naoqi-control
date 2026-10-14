from __future__ import annotations

import logging

import qi

logger = logging.getLogger(__name__)


class Leds:
    """Fade one LED group. Callers choose the color."""

    def __init__(self, session: qi.Session):
        self.session = session
        self.leds = session.service("ALLeds")

    def fade(self, group: str, color: str | int, duration: float = 0.15) -> None:
        if isinstance(color, str):
            rgb_hex = int(color.replace("#", ""), 16)
        else:
            rgb_hex = color

        try:
            self.leds.fadeRGB(group, rgb_hex, duration)
        except Exception as exc:
            logger.error("Could not fade leds: %s", exc)
