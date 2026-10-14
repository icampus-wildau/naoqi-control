from __future__ import annotations

import asyncio
import functools
import inspect
from collections.abc import Sequence

import qi

from naoqi_control.audio import Audio
from naoqi_control.buttons import Buttons
from naoqi_control.camera import Camera
from naoqi_control.leds import Leds
from naoqi_control.log import Log, _StdLog
from naoqi_control.motion import Motion
from naoqi_control.qi import (
    QI_CLOSE_TIMEOUT_SECS,
    QI_CONNECT_TIMEOUT_SECS,
    QI_EYE_TIMEOUT_SECS,
    QI_PREPARE_TIMEOUT_SECS,
    QI_STOP_SPEAKING_TIMEOUT_SECS,
    QiWorker,
)
from naoqi_control.tts import Tts

__all__ = [
    "QI_CLOSE_TIMEOUT_SECS",
    "QI_CONNECT_TIMEOUT_SECS",
    "QI_EYE_TIMEOUT_SECS",
    "QI_PREPARE_TIMEOUT_SECS",
    "QI_STOP_SPEAKING_TIMEOUT_SECS",
    "NaoController",
    "QiWorker",
    "run_nao_call",
    "say_timeout_secs",
    "speak_text",
]

DEFAULT_NAO_PORTS: tuple[int, ...] = (9559, 9561)


def _connection_refused(exc: BaseException) -> bool:
    return "connection refused" in str(exc).lower()


def _close_session(session: qi.Session) -> None:
    close = getattr(session, "close", None)
    if close is None:
        return
    try:
        close()
    except Exception:
        pass


def _normalize_ports(ports: int | Sequence[int] | None) -> list[int]:
    if ports is None:
        return list(DEFAULT_NAO_PORTS)
    if isinstance(ports, int):
        values = [ports]
    else:
        values = [int(port) for port in ports]
    if not values:
        raise ValueError("ports")
    return values


def _connect_session(ip: str, ports: Sequence[int], log: Log) -> tuple[qi.Session, int]:
    """Try each NAOqi port until one accepts. Connection refused moves to the next."""
    last_exc: BaseException | None = None
    for port in ports:
        session = qi.Session()
        url = f"tcp://{ip}:{port}"
        try:
            session.connect(url)
        except Exception as exc:
            _close_session(session)
            if _connection_refused(exc):
                log.verbose(f"NAOqi refused {url}")
                last_exc = exc
                continue
            raise
        log.verbose(f"Connected to NAOqi at {url}")
        return session, port

    tried = ", ".join(str(port) for port in ports)
    raise RuntimeError(
        f"Connect error: connection refused on {ip} (tried {tried})"
    ) from last_exc


class NaoController:
    """qi session, worker, and the speech, motion, camera, touch, and LED objects."""

    def __init__(
        self,
        ip: str = "192.168.2.50",
        ports: int | Sequence[int] | None = None,
        loop: asyncio.AbstractEventLoop | None = None,
        *,
        log: Log | None = None,
    ) -> None:
        self.ip = ip
        self.ports = _normalize_ports(ports)
        self._log: Log = log if log is not None else _StdLog()
        if loop is None:
            loop = asyncio.get_running_loop()
        self._owner_loop = loop
        self._closing = False
        self._qi_worker: QiWorker | None = None
        self._previous_life_state: str | None = None

        self.session, self.port = _connect_session(self.ip, self.ports, self._log)

        self.robot_name: str | None = None
        try:
            system = self.session.service("ALSystem")
            self.robot_name = system.robotName()
            self._log.verbose(f"Robot name: {self.robot_name}")
        except Exception as exc:
            raise Exception(f"Connected, but could not query ALSystem: {exc}") from exc

        self._log.verbose(f"Initializing NaoController for robot: {self.robot_name}")
        system = self.session.service("ALSystem")
        self._log.verbose(f"NAOqi version: {system.systemVersion()}")
        life = self.session.service("ALAutonomousLife")
        self._log.verbose(f"Life state: {life.getState()}")
        self._log.verbose(f"Focused activity: {life.focusedActivity()}")

        behaviors = list(self.session.service("ALBehaviorManager").getRunningBehaviors())
        if behaviors:
            self._log.verbose("Running behaviors: " + ", ".join(behaviors))
        else:
            self._log.verbose("Running behaviors: (none)")

        self._qi_worker = QiWorker()
        self.tts = Tts(self.session, self.call_qi, self._is_closing, self._log)
        self.audio = Audio(self.session, self.call_qi)
        self.motion = Motion(self.session, self.call_qi, self._is_closing, self._log)
        self.camera = Camera(self.session, self.call_qi, self._is_closing)
        self.leds = Leds(self.session)
        self.buttons = Buttons(self.session, loop)

    def _is_closing(self) -> bool:
        return bool(getattr(self, "_closing", False))

    def _ensure_worker(self) -> QiWorker:
        worker = getattr(self, "_qi_worker", None)
        if worker is None:
            worker = QiWorker()
            self._qi_worker = worker
        return worker

    async def call_qi(
        self,
        fn,
        *args,
        timeout: float | None = None,
        allow_when_closing: bool = False,
        **kwargs,
    ):
        """Run one blocking callable on the shared qi worker."""
        if self._is_closing() and not allow_when_closing:
            return None
        return await self._ensure_worker().call(fn, *args, timeout=timeout, **kwargs)

    @staticmethod
    async def run(
        nao,
        fn,
        *args,
        timeout: float | None = None,
        allow_when_closing: bool = False,
        **kwargs,
    ):
        """Run ``fn`` on ``nao``'s qi worker when it has one, otherwise on a thread."""
        call_qi = getattr(nao, "call_qi", None)
        if inspect.iscoroutinefunction(call_qi):
            return await call_qi(
                fn,
                *args,
                timeout=timeout,
                allow_when_closing=allow_when_closing,
                **kwargs,
            )
        partial = functools.partial(fn, *args, **kwargs)
        if timeout is None:
            return await asyncio.to_thread(partial)
        return await asyncio.wait_for(asyncio.to_thread(partial), timeout)

    async def prepare(
        self,
        *,
        volume: int,
        speech_speed: int,
        posture: str = "Sit",
    ) -> None:
        """Disable autonomous life, go to ``posture`` when not already sitting, then set volume and TTS speed."""
        await self.call_qi(self._prepare, volume, speech_speed, posture)

    def _prepare(self, volume: int, speech_speed: int, posture: str) -> None:
        applied_posture: str | None = None
        try:
            life = self.session.service("ALAutonomousLife")
            self._previous_life_state = life.getState()
            life.setState("disabled")
        except Exception as exc:
            self._log.error(f"prepare (autonomous life): {exc}")

        try:
            robot_posture = self.session.service("ALRobotPosture")
            current = robot_posture.getPosture()
            if current in ("Sit", "SitRelax"):
                applied_posture = current
            else:
                self.session.service("ALMotion").setStiffnesses("Body", 1.0)
                robot_posture.goToPosture(posture, 0.5)
                applied_posture = posture
        except Exception as exc:
            self._log.error(f"prepare (posture): {exc}")

        try:
            self.audio.service.setOutputVolume(volume)
        except Exception as exc:
            self._log.error(f"prepare (volume): {exc}")

        try:
            self.tts.set_speed(speech_speed)
        except Exception as exc:
            self._log.error(f"prepare (TTS speed): {exc}")

        self._log.verbose(
            f"Setup: posture={applied_posture}, volume={volume}, speech_speed={speech_speed}"
        )

    async def restore(self) -> None:
        """Put autonomous life back to the state saved by :meth:`prepare`."""
        await self.call_qi(self._restore, allow_when_closing=True)

    def _restore(self) -> None:
        if self._previous_life_state is None:
            return
        previous = self._previous_life_state
        self._previous_life_state = None
        try:
            life = self.session.service("ALAutonomousLife")
            life.setState(previous)
        except Exception as exc:
            self._log.error(f"restore: {exc}")

    def say(self, text: str) -> None:
        """Block until ``text`` has been spoken. Forward to :meth:`Tts.say`."""
        self.tts.say(text)

    async def speak(self, text: str, *, timeout: float) -> None:
        """Speak ``text`` without holding the qi worker. Forward to :meth:`Tts.say_async`."""
        await self.tts.say_async(text, timeout=timeout)

    def stop_speaking(self) -> None:
        """Stop the current utterance. Forward to :meth:`Tts.stop`."""
        self.tts.stop()

    async def close(self) -> None:
        """Stop speech, cancel in-flight gestures, and close the session."""
        self._closing = True
        tts = getattr(self, "tts", None)
        if tts is not None:
            try:
                await tts.stop_async()
            except Exception as exc:
                self._log.error(f"Could not stop speaking: {exc}")
        motion = getattr(self, "motion", None)
        if motion is not None:
            try:
                await motion.cancel()
            except Exception as exc:
                self._log.error(f"Could not cancel motion: {exc}")
        try:
            await self.call_qi(
                self.session.close,
                allow_when_closing=True,
                timeout=QI_CLOSE_TIMEOUT_SECS,
            )
        except Exception as exc:
            self._log.error(f"Could not close NAO session: {exc}")
        worker = getattr(self, "_qi_worker", None)
        if worker is not None:
            worker.stop()


async def run_nao_call(
    nao,
    fn,
    *args,
    timeout: float | None = None,
    allow_when_closing: bool = False,
    **kwargs,
):
    """Run ``fn`` on the controller's qi worker when it has one."""
    return await NaoController.run(
        nao,
        fn,
        *args,
        timeout=timeout,
        allow_when_closing=allow_when_closing,
        **kwargs,
    )


def say_timeout_secs(text: str) -> float:
    """Bound a spoken line to roughly the utterance length plus a margin."""
    return Tts.timeout_for(text)


async def speak_text(nao, text: str, *, timeout: float) -> None:
    """Speak ``text`` and wait until it finishes or ``timeout`` elapses.

    ``NaoController.speak`` posts the utterance and waits off the qi worker, so
    eye updates and ``stop`` can still run. Objects without ``speak`` keep
    the blocking ``say`` path.
    """
    speak = getattr(nao, "speak", None)
    if inspect.iscoroutinefunction(speak):
        await speak(text, timeout=timeout)
        return
    await run_nao_call(nao, nao.say, text, timeout=timeout)
