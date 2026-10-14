from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from naoqi_control.log import _StdLog
from naoqi_control.motion import Motion
from naoqi_control.qi import QiWorker
from naoqi_control.robot import NaoController
from naoqi_control.tts import Tts


def _make_controller(
    *,
    posture: str = "Stand",
) -> tuple[NaoController, MagicMock, MagicMock, MagicMock, MagicMock, MagicMock]:
    nao = NaoController.__new__(NaoController)
    nao.session = MagicMock()
    nao._log = _StdLog()
    nao._closing = False
    nao._qi_worker = QiWorker()
    nao._previous_life_state = None

    life = MagicMock()
    life.getState.return_value = "solitary"
    motion = MagicMock()
    robot_posture = MagicMock()
    robot_posture.getPosture.return_value = posture
    audio = MagicMock()
    tts_service = MagicMock()

    def service(name: str) -> MagicMock:
        if name == "ALAutonomousLife":
            return life
        if name == "ALMotion":
            return motion
        if name == "ALRobotPosture":
            return robot_posture
        raise AssertionError(f"unexpected service {name}")

    nao.session.service.side_effect = service
    nao.audio = MagicMock()
    nao.audio.service = audio
    nao.tts = Tts.__new__(Tts)
    nao.tts.service = tts_service
    nao.motion = Motion(nao.session, nao.call_qi, nao._is_closing, nao._log)
    return nao, life, motion, robot_posture, audio, tts_service


class TestPrepare(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self) -> None:
        worker = getattr(self, "_worker", None)
        if worker is not None:
            worker.stop()

    async def test_disables_life_and_sits_from_stand(self) -> None:
        nao, life, motion, robot_posture, audio, tts = _make_controller(posture="Stand")
        self._worker = nao._qi_worker

        await nao.prepare(volume=70, speech_speed=110, posture="Sit")

        life.getState.assert_called_once()
        life.setState.assert_called_once_with("disabled")
        motion.wakeUp.assert_not_called()
        motion.rest.assert_not_called()
        motion.setStiffnesses.assert_called_once_with("Body", 1.0)
        robot_posture.goToPosture.assert_called_once_with("Sit", 0.5)
        audio.setOutputVolume.assert_called_once_with(70)
        tts.setParameter.assert_called_once_with("speed", 110)

    async def test_skips_posture_when_already_sitting(self) -> None:
        nao, life, motion, robot_posture, audio, tts = _make_controller(posture="Sit")
        self._worker = nao._qi_worker

        await nao.prepare(volume=80, speech_speed=90)

        life.setState.assert_called_once_with("disabled")
        motion.setStiffnesses.assert_not_called()
        robot_posture.goToPosture.assert_not_called()
        audio.setOutputVolume.assert_called_once_with(80)
        tts.setParameter.assert_called_once_with("speed", 90)


class TestRestore(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self) -> None:
        worker = getattr(self, "_worker", None)
        if worker is not None:
            worker.stop()

    async def test_restores_saved_life_state(self) -> None:
        nao, life, *_ = _make_controller()
        self._worker = nao._qi_worker
        nao._previous_life_state = "solitary"

        await nao.restore()

        life.setState.assert_called_once_with("solitary")
        self.assertIsNone(nao._previous_life_state)


if __name__ == "__main__":
    unittest.main()
