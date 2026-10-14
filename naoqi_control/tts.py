from __future__ import annotations

import asyncio
from typing import Literal

import qi

from naoqi_control.buttons import Button
from naoqi_control.log import Log
from naoqi_control.qi import QI_STOP_SPEAKING_TIMEOUT_SECS, QiCall

SpeechResult = Literal["finished", "interrupted", "timed_out"]


class Tts:
    """Speech on ``ALTextToSpeech``. ``service`` is the raw qi proxy."""

    def __init__(self, session: qi.Session, call_qi, is_closing, log: Log) -> None:
        self.service = session.service("ALTextToSpeech")
        self._call_qi = call_qi
        self._is_closing = is_closing
        self._log = log

    def say(self, text: str) -> None:
        """Block on ``ALTextToSpeech.say`` until the utterance ends."""
        if self._is_closing():
            return
        self._log.nao(text)
        try:
            self.service.say(text)
        except Exception as exc:
            self._log.error(f"Could not say: {exc}")

    async def say_async(self, text: str, *, timeout: float | None = None) -> None:
        """Post the utterance and wait off the qi worker.

        LEDs and ``stop`` can still run while the robot is talking. ``timeout``
        defaults to :meth:`timeout_for`.
        """
        if timeout is None:
            timeout = self.timeout_for(text)
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        future = await self._call_qi(self._post_say, text, timeout=timeout)
        if future is None:
            return
        remaining = deadline - loop.time()
        if remaining <= 0:
            await self._stop_posted_speech()
            raise TimeoutError
        try:
            await asyncio.wait_for(
                QiCall.wait(future, self._call_qi, self._is_closing),
                remaining,
            )
        except asyncio.CancelledError:
            await self._stop_posted_speech()
            raise
        except TimeoutError:
            await self._stop_posted_speech()
            raise

    async def say_until(
        self,
        text: str,
        *,
        button: Button | None = None,
        stop: asyncio.Event | None = None,
        timeout: float | None = None,
    ) -> SpeechResult:
        """Speak until the utterance ends, a button is pressed, ``stop`` is set, or the timeout elapses.

        A button press or ``stop`` cuts the voice off. The timeout also stops it.
        """
        if timeout is None:
            timeout = self.timeout_for(text)
        speech = asyncio.create_task(self.say_async(text, timeout=timeout))
        signals: list[asyncio.Task] = []
        if button is not None:
            signals.append(asyncio.create_task(button.wait_for_button_press()))
        if stop is not None:
            signals.append(asyncio.create_task(stop.wait()))
        try:
            if not signals:
                try:
                    await speech
                except TimeoutError:
                    return "timed_out"
                return "finished"
            done, _pending = await asyncio.wait(
                [speech, *signals],
                return_when=asyncio.FIRST_COMPLETED,
            )
            if speech not in done:
                return "interrupted"
            if speech.cancelled():
                return "interrupted"
            exc = speech.exception()
            if isinstance(exc, TimeoutError):
                return "timed_out"
            if exc is not None:
                raise exc
            return "finished"
        finally:
            if not speech.done():
                speech.cancel()
            for task in signals:
                if not task.done():
                    task.cancel()
            await asyncio.gather(speech, *signals, return_exceptions=True)

    def stop(self) -> None:
        """Call ``stopAll`` immediately."""
        try:
            self.service.stopAll()
        except Exception as exc:
            self._log.error(f"Could not stop speaking: {exc}")

    async def stop_async(self) -> None:
        """Run :meth:`stop` on the qi worker."""
        await self._call_qi(
            self.stop,
            timeout=QI_STOP_SPEAKING_TIMEOUT_SECS,
            allow_when_closing=True,
        )

    def set_speed(self, speed: int) -> None:
        """Set the TTS speed parameter."""
        self.service.setParameter("speed", speed)

    def set_language(self, language: str) -> None:
        """Set the TTS language, for example ``"German"``."""
        self.service.setLanguage(language)

    def set_volume(self, volume: float) -> None:
        """Set the TTS gain from 0 to 1. The speaker amp stays on :class:`Audio`."""
        self.service.setVolume(volume)

    def set_pitch_shift(self, shift: float) -> None:
        """Set the NAOqi ``pitchShift`` parameter."""
        self.set_parameter("pitchShift", shift)

    def set_parameter(self, name: str, value: int | float | str) -> None:
        """Set any other ``ALTextToSpeech`` parameter."""
        self.service.setParameter(name, value)

    @staticmethod
    def timeout_for(text: str) -> float:
        """Return a timeout from the length of ``text``."""
        length = len(text or "")
        return min(90.0, max(8.0, (length / 12.0) + 8.0))

    def _post_say(self, text: str):
        if self._is_closing():
            return None
        self._log.nao(text)
        try:
            return QiCall.start(self.service, "say", text)
        except Exception as exc:
            self._log.error(f"Could not say: {exc}")
            return None

    async def _stop_posted_speech(self) -> None:
        try:
            await self.stop_async()
        except Exception as exc:
            self._log.error(f"Could not stop speaking: {exc}")
