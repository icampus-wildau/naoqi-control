from __future__ import annotations

import asyncio
from collections.abc import Sequence

from naoqi_control.animation import Animation, Side
from naoqi_control.log import Log
from naoqi_control.qi import QiCall


class Motion:
    """Posture, stiffness, joint moves, and the named gestures."""

    def __init__(self, session, call_qi, is_closing, log: Log) -> None:
        self.session = session
        self._call_qi = call_qi
        self._is_closing = is_closing
        self._log = log
        self._busy: set[str] = set()
        self._tasks: set[asyncio.Task] = set()
        self._abort = False

    async def get_posture(self) -> str:
        """Return the current posture name."""
        return await self._call_qi(self._get_posture)

    async def go_to_posture(self, name: str, speed: float = 0.5) -> None:
        """Stiffen the body and move to a named posture such as ``"Sit"`` or ``"Stand"``.

        The move is posted. A blocking ``goToPosture`` would hold the qi worker
        for the whole stand or sit, and the link health check would time out
        and drop the session. ``Sit`` and ``SitRelax`` release body stiffness
        once the move has finished.
        """
        future = await self._call_qi(self._begin_posture, name, speed)
        if future is not None:
            await QiCall.wait(future, self._call_qi, self._stopped)
        if self._stopped() or name not in ("Sit", "SitRelax"):
            return
        await self.set_stiffness("Body", 0.0)

    async def set_stiffness(self, names: str | list[str], stiffness: float) -> None:
        """Set stiffness for a joint, a chain, or ``"Body"``."""
        await self._call_qi(self._set_stiffness, names, stiffness)

    async def get_angles(self, names: list[str], use_sensors: bool = True) -> list[float]:
        """Read the current joint angles."""
        angles = await self._call_qi(self._get_angles, names, use_sensors)
        return list(angles)

    async def set_angles(self, names: list[str], angles: list[float], speed: float) -> None:
        """Move those joints to absolute angles and wait until they arrive."""
        future = await self._call_qi(self._begin_set_angles, names, angles, speed)
        if future is None:
            return
        await QiCall.wait(future, self._call_qi, self._stopped)

    async def stop(self) -> None:
        """Stop current body motion with ``ALMotion.stopMove``."""
        await self._call_qi(self._stop_move)

    def play(self, animation: Animation) -> None:
        """Start an animation in the background.

        A second play on a chain that is already moving is ignored.
        """
        self._schedule(self.play_and_wait(animation))

    async def play_and_wait(self, animation: Animation) -> None:
        """Play an animation and wait until it finishes."""
        if self._stopped() or animation.chain in self._busy:
            return
        self._busy.add(animation.chain)
        try:
            await animation.play(
                session=self.session,
                call_qi=self._call_qi,
                is_closing=self._stopped,
                log=self._log,
            )
        finally:
            self._busy.discard(animation.chain)

    def wave(self, sides: Sequence[Side]) -> None:
        """Start a greeting wave in the background."""
        self._schedule(self.wave_and_wait(sides))

    async def wave_and_wait(self, sides: Sequence[Side]) -> None:
        """Wave and wait until every requested arm has returned."""
        await asyncio.gather(*(self.play_and_wait(Animation.wave(side)) for side in sides))

    def farewell(self, sides: Sequence[Side]) -> None:
        """Start a short farewell gesture in the background."""
        self._schedule(self.farewell_and_wait(sides))

    async def farewell_and_wait(self, sides: Sequence[Side]) -> None:
        """Play the farewell and wait until every requested arm has returned."""
        await asyncio.gather(
            *(self.play_and_wait(Animation.farewell(side)) for side in sides)
        )

    def nod(self) -> None:
        """Start a small yes-nod in the background."""
        self._schedule(self.nod_and_wait())

    async def nod_and_wait(self) -> None:
        """Nod and wait until the head has returned."""
        await self.play_and_wait(Animation.nod())

    def shake(self) -> None:
        """Start a small no-shake in the background."""
        self._schedule(self.shake_and_wait())

    async def shake_and_wait(self) -> None:
        """Shake and wait until the head has returned."""
        await self.play_and_wait(Animation.shake())

    async def cancel(self) -> None:
        """Cancel background gestures and wait until the qi worker is idle."""
        self._abort = True
        tasks = [task for task in list(self._tasks) if not task.done()]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        await self._call_qi(lambda: None, allow_when_closing=True)
        self._abort = False

    def _schedule(self, coro) -> None:
        task = asyncio.get_running_loop().create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._on_task_done)

    def _on_task_done(self, task: asyncio.Task) -> None:
        self._tasks.discard(task)
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            self._log.error(f"Gesture failed: {type(exc).__name__}: {exc}")

    def _stopped(self) -> bool:
        return self._abort or self._is_closing()

    def _get_posture(self) -> str:
        return self._posture_service().getPosture()

    def _posture_service(self):
        return self.session.service("ALRobotPosture")

    def _motion_service(self):
        return self.session.service("ALMotion")

    def _begin_posture(self, name: str, speed: float):
        if self._stopped():
            return None
        self._set_stiffness("Body", 1.0)
        return QiCall.start(self._posture_service(), "goToPosture", name, speed)

    def _set_stiffness(self, names: str | list[str], stiffness: float) -> None:
        self._motion_service().setStiffnesses(names, stiffness)

    def _get_angles(self, names: list[str], use_sensors: bool) -> list[float]:
        return list(self._motion_service().getAngles(names, use_sensors))

    def _begin_set_angles(self, names: list[str], angles: list[float], speed: float):
        if self._stopped():
            return None
        return QiCall.start(
            self._motion_service(),
            "angleInterpolationWithSpeed",
            names,
            angles,
            speed,
        )

    def _stop_move(self) -> None:
        self._motion_service().stopMove()
