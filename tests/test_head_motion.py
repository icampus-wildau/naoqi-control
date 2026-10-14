from __future__ import annotations

import asyncio
import threading
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, call

from naoqi_control.animation import Animation
from naoqi_control.log import _StdLog
from naoqi_control.motion import Motion
from naoqi_control.robot import NaoController


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


class HeadMotionTests(unittest.IsolatedAsyncioTestCase):
    async def test_nod_dips_pitch_then_returns_and_unstiffens(self) -> None:
        motion = MagicMock()
        motion.getAngles.return_value = [0.05]
        nao = _controller(motion)

        await nao.motion.nod_and_wait()

        animation = Animation.nod()
        names = animation.joints
        offsets = animation.keyframes
        times = animation.times
        return_secs = animation.return_secs
        targets = [[0.05 + offset for offset in offsets[0]]]
        motion.getAngles.assert_called_once_with(["HeadPitch"], True)
        self.assertEqual(
            motion.angleInterpolation.call_args_list,
            [
                call(names, targets, times, True, _async=True),
                call(names, [[0.05]], [[return_secs]], True, _async=True),
            ],
        )
        self.assertEqual(
            motion.setStiffnesses.call_args_list,
            [call("Head", 0.8), call("Head", 0.0)],
        )
        self.assertNotIn("HeadYaw", names)

    async def test_shake_turns_yaw_both_ways(self) -> None:
        motion = MagicMock()
        motion.getAngles.return_value = [-0.1]
        nao = _controller(motion)

        await nao.motion.shake_and_wait()

        animation = Animation.shake()
        names = animation.joints
        offsets = animation.keyframes
        times = animation.times
        return_secs = animation.return_secs
        targets = [[-0.1 + offset for offset in offsets[0]]]
        self.assertEqual(names, ["HeadYaw"])
        self.assertGreater(max(targets[0]), 0)
        self.assertLess(min(targets[0]), 0)
        motion.angleInterpolation.assert_any_call(
            names, targets, times, True, _async=True
        )
        motion.angleInterpolation.assert_called_with(
            names, [[-0.1]], [[return_secs]], True, _async=True
        )
        self.assertEqual(motion.setStiffnesses.call_args_list[-1], call("Head", 0.0))

    async def test_second_head_gesture_is_ignored(self) -> None:
        entered = threading.Event()
        release = threading.Event()

        def get_angles(names, use_sensors):
            entered.set()
            if not release.wait(timeout=2):
                raise TimeoutError("head gesture was not released")
            return [0.0] * len(names)

        motion = MagicMock()
        motion.getAngles.side_effect = get_angles
        nao = _controller(motion)

        first = asyncio.create_task(nao.motion.nod_and_wait())
        self.assertTrue(await asyncio.to_thread(entered.wait, 2))
        await nao.motion.shake_and_wait()
        self.assertEqual(motion.getAngles.call_count, 1)

        release.set()
        await first
        self.assertEqual(motion.getAngles.call_count, 1)

    async def test_unstiffens_when_interpolation_fails(self) -> None:
        motion = MagicMock()
        motion.getAngles.return_value = [0.0]
        motion.angleInterpolation.side_effect = RuntimeError("boom")
        nao = _controller(motion)

        await nao.motion.nod_and_wait()

        self.assertEqual(
            motion.setStiffnesses.call_args_list,
            [call("Head", 0.8), call("Head", 0.0)],
        )

    async def test_hold_pose_skips_the_return_and_stays_stiff(self) -> None:
        motion = MagicMock()
        motion.getAngles.return_value = [0.2]
        nao = _controller(motion)
        animation = Animation(
            name="hold",
            chain="Head",
            joints=["HeadPitch"],
            keyframes=[[0.1]],
            times=[[0.4]],
            return_to_origin=False,
        )

        await nao.motion.play_and_wait(animation)

        motion.angleInterpolation.assert_called_once_with(
            ["HeadPitch"], [[0.1]], [[0.4]], True, _async=True
        )
        motion.setStiffnesses.assert_called_once_with("Head", 0.8)

    async def test_cancel_finishes_before_close(self) -> None:
        entered = threading.Event()

        def get_angles(names, use_sensors):
            entered.set()
            time.sleep(0.25)
            return [0.0] * len(names)

        motion = MagicMock()
        motion.getAngles.side_effect = get_angles
        nao = _controller(motion)
        nao.tts = MagicMock()
        nao.tts.stop_async = AsyncMock()

        nao.motion.nod()
        self.assertTrue(await asyncio.to_thread(entered.wait, 2))
        await nao.motion.cancel()

        self.assertFalse(nao._closing)
        self.assertEqual(motion.angleInterpolation.call_count, 0)
        service_calls = nao.session.service.call_count
        await asyncio.sleep(0.05)
        self.assertEqual(nao.session.service.call_count, service_calls)
        await nao.close()
        nao.session.close.assert_called()

    def test_joint_catalog_lists_the_h25_body(self) -> None:
        self.assertEqual(Animation.JOINTS[0], "HeadYaw")
        self.assertEqual(Animation.JOINTS[-1], "RHand")
        self.assertEqual(len(Animation.JOINTS), 26)
        self.assertEqual(Animation.CHAINS, ("Head", "LArm", "RArm", "LLeg", "RLeg", "Body"))


if __name__ == "__main__":
    unittest.main()
