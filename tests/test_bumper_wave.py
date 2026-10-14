from __future__ import annotations

import asyncio
import threading
import unittest
from unittest.mock import MagicMock, call

from naoqi_control.animation import Animation
from naoqi_control.log import _StdLog
from naoqi_control.motion import Motion
from naoqi_control.robot import NaoController
from naoqi_control.tts import Tts


def _controller(motion: MagicMock) -> NaoController:
    nao = NaoController.__new__(NaoController)
    nao.session = MagicMock()
    nao.session.service.return_value = motion
    # MagicMock would invent post.angleInterpolation and skip the blocking path.
    motion.post = None
    nao._closing = False
    nao._log = _StdLog()
    nao._qi_worker = None
    nao.motion = Motion(nao.session, nao.call_qi, nao._is_closing, nao._log)
    return nao


class TestArmGestures(unittest.IsolatedAsyncioTestCase):
    async def test_left_wave_raises_then_returns_and_unstiffens(self) -> None:
        rest = [0.9, 0.1, -0.4, -0.5, 0.2, 0.0]
        motion = MagicMock()
        motion.getAngles.return_value = rest
        nao = _controller(motion)

        await nao.motion.wave_and_wait(["left"])

        animation = Animation.wave("left")
        chain, names, angles, times = (
            animation.chain,
            animation.joints,
            animation.keyframes,
            animation.times,
        )
        motion.getAngles.assert_called_once_with(names, True)
        self.assertEqual(
            motion.setStiffnesses.call_args_list,
            [call(chain, 0.8), call(chain, 0.0)],
        )
        self.assertEqual(
            motion.angleInterpolation.call_args_list,
            [
                call(names, angles, times, True, _async=True),
                call(
                    names,
                    [[angle] for angle in rest],
                    [[animation.return_secs]] * len(names),
                    True,
                    _async=True,
                ),
            ],
        )
        self.assertEqual(names[0], "LShoulderPitch")
        self.assertEqual(chain, "LArm")

    async def test_right_wave_uses_right_arm(self) -> None:
        rest = [0.9, -0.1, 0.4, 0.5, 0.2, 0.0]
        motion = MagicMock()
        motion.getAngles.return_value = rest
        nao = _controller(motion)

        await nao.motion.wave_and_wait(["right"])

        animation = Animation.wave("right")
        names = animation.joints
        motion.getAngles.assert_called_once_with(names, True)
        self.assertEqual(animation.chain, "RArm")
        self.assertEqual(names[0], "RShoulderPitch")
        self.assertEqual(
            motion.setStiffnesses.call_args_list,
            [call("RArm", 0.8), call("RArm", 0.0)],
        )
        motion.angleInterpolation.assert_any_call(
            names, animation.keyframes, animation.times, True, _async=True
        )
        motion.angleInterpolation.assert_called_with(
            names,
            [[angle] for angle in rest],
            [[animation.return_secs]] * len(names),
            True,
            _async=True,
        )

    async def test_second_wave_same_side_is_ignored(self) -> None:
        entered = threading.Event()
        release = threading.Event()

        def get_angles(names, use_sensors):
            entered.set()
            if not release.wait(timeout=2):
                raise TimeoutError("wave was not released")
            return [0.2] * len(names)

        motion = MagicMock()
        motion.getAngles.side_effect = get_angles
        nao = _controller(motion)

        first = asyncio.create_task(nao.motion.wave_and_wait(["left"]))
        self.assertTrue(await asyncio.to_thread(entered.wait, 2))
        await nao.motion.wave_and_wait(["left"])
        self.assertEqual(motion.getAngles.call_count, 1)

        release.set()
        await first
        self.assertEqual(motion.getAngles.call_count, 1)
        self.assertEqual(motion.angleInterpolation.call_count, 2)

    async def test_unstiffens_when_interpolation_fails(self) -> None:
        motion = MagicMock()
        motion.getAngles.return_value = [0.1] * 6
        motion.angleInterpolation.side_effect = RuntimeError("boom")
        nao = _controller(motion)

        await nao.motion.wave_and_wait(["left"])

        self.assertEqual(
            motion.setStiffnesses.call_args_list,
            [call("LArm", 0.8), call("LArm", 0.0)],
        )
        self.assertEqual(motion.angleInterpolation.call_count, 1)

    async def test_farewell_is_shorter_and_returns_to_rest(self) -> None:
        rest = [0.9, 0.1, -0.4, -0.5, 0.2, 0.0]
        motion = MagicMock()
        motion.getAngles.return_value = rest
        nao = _controller(motion)

        await nao.motion.farewell_and_wait(["left"])

        wave = Animation.wave("left")
        farewell = Animation.farewell("left")
        wave_duration = max(max(joint_times) for joint_times in wave.times)
        farewell_duration = max(max(joint_times) for joint_times in farewell.times)
        self.assertLess(farewell_duration, wave_duration)
        self.assertLess(len(farewell.keyframes[4]), len(wave.keyframes[4]))
        self.assertEqual(farewell.joints, wave.joints)
        self.assertEqual(
            motion.angleInterpolation.call_args_list,
            [
                call(farewell.joints, farewell.keyframes, farewell.times, True, _async=True),
                call(
                    farewell.joints,
                    [[angle] for angle in rest],
                    [[farewell.return_secs]] * len(farewell.joints),
                    True,
                    _async=True,
                ),
            ],
        )
        self.assertEqual(
            motion.setStiffnesses.call_args_list,
            [call(farewell.chain, 0.8), call(farewell.chain, 0.0)],
        )

    async def test_both_arms_wave_together(self) -> None:
        motion = MagicMock()
        motion.getAngles.return_value = [0.1] * 6
        nao = _controller(motion)

        nao.motion.wave(["left", "right"])
        await asyncio.gather(*nao.motion._tasks)

        chains = [
            call.args[0]
            for call in motion.setStiffnesses.call_args_list
            if call.args[1] == 0.8
        ]
        self.assertEqual(sorted(chains), ["LArm", "RArm"])
        self.assertEqual(nao.motion._tasks, set())

    async def test_wave_leaves_the_qi_thread_free_for_speech(self) -> None:
        release = threading.Event()
        posted: dict[str, object] = {}

        class MoveFuture:
            def isFinished(self) -> bool:
                return release.is_set()

        class SpeechFuture:
            def isFinished(self) -> bool:
                return release.is_set()

        class MotionService:
            """qi service: ``_async=True`` returns immediately, a plain call blocks."""

            def getAngles(self, names, use_sensors):
                return [0.1] * len(names)

            def setStiffnesses(self, chain, stiffness):
                return None

            def angleInterpolation(self, names, angles, times, is_absolute, _async=False):
                if not _async:
                    if not release.wait(timeout=2):
                        raise TimeoutError("blocking interpolation held the worker")
                    return None
                posted["motion"] = names
                return MoveFuture()

        class Speech:
            def say(self, text, _async=False):
                if not _async:
                    if not release.wait(timeout=2):
                        raise TimeoutError("blocking say held the worker")
                    return None
                posted["say"] = text
                return SpeechFuture()

            def stopAll(self):
                release.set()

        motion = MotionService()
        nao = _controller(motion)  # type: ignore[arg-type]
        nao.tts = Tts.__new__(Tts)
        nao.tts.service = Speech()
        nao.tts._call_qi = nao.call_qi
        nao.tts._is_closing = nao._is_closing
        nao.tts._log = nao._log

        wave = asyncio.create_task(nao.motion.wave_and_wait(["left"]))
        for _ in range(50):
            if "motion" in posted:
                break
            await asyncio.sleep(0.02)
        self.assertIn("motion", posted)

        speech = asyncio.create_task(nao.speak("hallo", timeout=1.0))
        for _ in range(50):
            if posted.get("say") == "hallo":
                break
            await asyncio.sleep(0.02)
        self.assertEqual(posted.get("say"), "hallo")

        release.set()
        await speech
        await wave


if __name__ == "__main__":
    unittest.main()
