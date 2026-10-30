"""Standing and sitting must not hold the qi worker for the whole move."""

from __future__ import annotations

import asyncio
import threading
import unittest

from naoqi_control.log import _StdLog
from naoqi_control.motion import Motion
from naoqi_control.qi import QiWorker
from naoqi_control.robot import NaoController


class _PostureFuture:
    def __init__(self) -> None:
        self._done = threading.Event()

    def isFinished(self) -> bool:
        return self._done.is_set()

    def finish(self) -> None:
        self._done.set()


class _Posture:
    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.started = threading.Event()
        self.future = _PostureFuture()

    def goToPosture(self, name: str, speed: float, _async: bool = False):
        self.calls.append((name, speed, _async))
        self.started.set()
        if not _async:
            raise AssertionError("goToPosture held the worker")
        return self.future


class _Motion:
    def __init__(self) -> None:
        self.stiffness: list[tuple] = []

    def setStiffnesses(self, names, stiffness: float) -> None:
        self.stiffness.append((names, stiffness))


def _controller(posture: _Posture, motion: _Motion) -> NaoController:
    nao = NaoController.__new__(NaoController)
    nao._closing = False
    nao._log = _StdLog()
    nao._qi_worker = QiWorker()

    def service(name: str):
        if name == "ALRobotPosture":
            return posture
        if name == "ALMotion":
            return motion
        raise AssertionError(name)

    nao.session = type("Session", (), {"service": staticmethod(service)})()
    nao.motion = Motion(nao.session, nao.call_qi, nao._is_closing, nao._log)
    return nao


class PostureTests(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self) -> None:
        worker = getattr(self, "_worker", None)
        if worker is not None:
            worker.stop()

    async def test_stand_leaves_the_worker_free(self) -> None:
        posture = _Posture()
        motion = _Motion()
        nao = _controller(posture, motion)
        self._worker = nao._qi_worker

        standing = asyncio.create_task(nao.motion.go_to_posture("Stand"))
        self.assertTrue(await asyncio.to_thread(posture.started.wait, 1))

        marker: list[str] = []
        await asyncio.wait_for(
            nao.call_qi(lambda: marker.append("health"), timeout=0.5),
            timeout=1,
        )
        self.assertEqual(marker, ["health"])
        self.assertEqual(posture.calls, [("Stand", 0.5, True)])
        self.assertEqual(motion.stiffness, [("Body", 1.0)])

        posture.future.finish()
        await asyncio.wait_for(standing, timeout=1)
        self.assertEqual(motion.stiffness, [("Body", 1.0)])

    async def test_sit_releases_stiffness_after_the_move(self) -> None:
        posture = _Posture()
        motion = _Motion()
        nao = _controller(posture, motion)
        self._worker = nao._qi_worker

        sitting = asyncio.create_task(nao.motion.go_to_posture("Sit"))
        self.assertTrue(await asyncio.to_thread(posture.started.wait, 1))
        self.assertEqual(motion.stiffness, [("Body", 1.0)])

        posture.future.finish()
        await asyncio.wait_for(sitting, timeout=1)
        self.assertEqual(posture.calls, [("Sit", 0.5, True)])
        self.assertEqual(motion.stiffness, [("Body", 1.0), ("Body", 0.0)])
