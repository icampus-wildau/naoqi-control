from __future__ import annotations

import qi


class Audio:
    """Master speaker volume on ``ALAudioDevice``."""

    def __init__(self, session: qi.Session, call_qi) -> None:
        self.service = session.service("ALAudioDevice")
        self._call_qi = call_qi

    async def set_output_volume(self, volume: int) -> None:
        """Set the master speaker volume."""
        await self._call_qi(self.service.setOutputVolume, int(volume))

    async def get_output_volume(self) -> int:
        """Read the master speaker volume."""
        return int(await self._call_qi(self.service.getOutputVolume))
