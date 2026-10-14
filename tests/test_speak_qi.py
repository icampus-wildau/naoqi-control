"""Speech must not hold the qi worker for the whole utterance."""

from __future__ import annotations

import asyncio
import threading
import unittest
from unittest.mock import MagicMock

from naoqi_control.log import _StdLog
from naoqi_control.qi import QiWorker
from naoqi_control.robot import NaoController
from naoqi_control.tts import Tts


class _SpeechFuture:
    def __init__(self) -> None:
        self._done = threading.Event()

    def isFinished(self) -> bool:
        return self._done.is_set()

    def finish(self) -> None:
        self._done.set()


class _Post:
    def __init__(self, tts: "_TTS") -> None:
        self._tts = tts

    def say(self, text: str) -> _SpeechFuture:
        self._tts.posted.append(text)
        self._tts.started.set()
        return self._tts.future


class _TTS:
    """Blocking ``say`` plus a non-blocking ``post.say``, like NAOqi."""

    def __init__(self) -> None:
        self.posted: list[str] = []
        self.blocking_calls: list[str] = []
        self.stopped = 0
        self.started = threading.Event()
        self.future = _SpeechFuture()
        self.post = _Post(self)
        self._release = threading.Event()

    def say(self, text: str) -> None:
        self.blocking_calls.append(text)
        self.started.set()
        if not self._release.wait(timeout=2):
            raise TimeoutError("blocking say held the worker")

    def stopAll(self) -> None:
        self.stopped += 1
        self.future.finish()
        self._release.set()


def _controller(service: _TTS) -> NaoController:
    nao = NaoController.__new__(NaoController)
    nao._closing = False
    nao._log = _StdLog()
    nao._qi_worker = QiWorker()
    nao.tts = Tts.__new__(Tts)
    nao.tts.service = service
    nao.tts._call_qi = nao.call_qi
    nao.tts._is_closing = nao._is_closing
    nao.tts._log = nao._log
    return nao


class SpeakQiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self) -> None:
        worker = getattr(self, "_worker", None)
        if worker is not None:
            worker.stop()

    async def test_eye_call_runs_while_speech_is_in_progress(self) -> None:
        tts = _TTS()
        nao = _controller(tts)
        self._worker = nao._qi_worker

        speech = asyncio.create_task(nao.speak("hallo", timeout=1.0))
        self.assertTrue(await asyncio.to_thread(tts.started.wait, 1))

        marker: list[str] = []
        await asyncio.wait_for(
            nao.call_qi(lambda: marker.append("eyes"), timeout=0.3),
            timeout=0.5,
        )
        self.assertEqual(marker, ["eyes"])
        self.assertEqual(tts.blocking_calls, [])

        tts.future.finish()
        await asyncio.wait_for(speech, timeout=1)

    async def test_speech_timeout_stops_the_utterance(self) -> None:
        tts = _TTS()
        nao = _controller(tts)
        self._worker = nao._qi_worker

        with self.assertRaises(TimeoutError):
            await nao.speak("hallo", timeout=0.15)

        self.assertGreaterEqual(tts.stopped, 1)
        eyes_done = asyncio.Event()
        await asyncio.wait_for(
            nao.call_qi(eyes_done.set, timeout=0.5),
            timeout=1,
        )
        self.assertTrue(eyes_done.is_set())

    async def test_say_until_button_stops_the_utterance(self) -> None:
        tts = _TTS()
        nao = _controller(tts)
        self._worker = nao._qi_worker
        pressed = asyncio.Event()

        class Button:
            async def wait_for_button_press(self) -> bool:
                await pressed.wait()
                return True

        speech = asyncio.create_task(
            nao.tts.say_until("hallo", button=Button(), timeout=2.0)  # type: ignore[arg-type]
        )
        self.assertTrue(await asyncio.to_thread(tts.started.wait, 1))
        pressed.set()
        self.assertEqual(await speech, "interrupted")
        self.assertGreaterEqual(tts.stopped, 1)

    def test_pitch_shift_sets_the_parameter(self) -> None:
        tts = Tts.__new__(Tts)
        tts.service = MagicMock()
        tts.set_pitch_shift(1.2)
        tts.service.setParameter.assert_called_once_with("pitchShift", 1.2)
        tts.set_parameter("speed", 80)
        tts.service.setParameter.assert_any_call("speed", 80)


if __name__ == "__main__":
    unittest.main()
