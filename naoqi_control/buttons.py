from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable, Coroutine, Any

import qi

logger = logging.getLogger(__name__)


def _log_task_result(task: asyncio.Task) -> None:
    """Retrieve a button-callback failure so asyncio does not drop it."""
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.error("Button callback failed", exc_info=exc)


class Buttons:
    def __init__(self, session: qi.Session, loop: asyncio.AbstractEventLoop):
        self.session = session
        self.front_head = Button(
            session, subscriber_name="FrontTactilTouched", loop=loop
        )
        self.middle_head = Button(
            session, subscriber_name="MiddleTactilTouched", loop=loop
        )
        self.back_head = Button(
            session, subscriber_name="RearTactilTouched", loop=loop
        )
        self.left_bumper = Button(
            session, subscriber_name="LeftBumperPressed", loop=loop
        )
        self.right_bumper = Button(
            session, subscriber_name="RightBumperPressed", loop=loop
        )
        self.left_hand = Button(
            session, subscriber_name="HandLeftBackTouched", loop=loop
        )
        self.right_hand = Button(
            session, subscriber_name="HandRightBackTouched", loop=loop
        )


class Button:
    def __init__(
        self,
        session: qi.Session,
        subscriber_name: str,
        loop: asyncio.AbstractEventLoop | None = None,
    ):
        self._subscriber_name = subscriber_name

        self._memory_service = session.service("ALMemory")

        # NaoController passes the asyncio loop when this runs off that thread.
        self._loop = loop if loop is not None else asyncio.get_running_loop()

        self._subsriber_button = self._memory_service.subscriber(
            f"{self._subscriber_name}")
        self._subsriber_button.signal.connect(self._handler)
        self.is_pressed = False
        self._was_pressed = False
        self._was_released = False

        self._pressed_event = asyncio.Event()
        self._released_event = asyncio.Event()

        self._on_pressed_callbacks: list[Callable[[
        ], Coroutine[Any, Any, None]]] = []
        self._on_released_callbacks: list[Callable[[
        ], Coroutine[Any, Any, None]]] = []

    def on_pressed(self, callback: Callable[[], Coroutine[Any, Any, None]]):
        self._on_pressed_callbacks.append(callback)

    def on_released(self, callback: Callable[[], Coroutine[Any, Any, None]]):
        self._on_released_callbacks.append(callback)

    def _schedule(self, callback):
        def _start():
            task = self._loop.create_task(callback())
            task.add_done_callback(_log_task_result)

        self._loop.call_soon_threadsafe(_start)

    def _handler(self, value: bool):
        # print(f"Button {self._subscriber_name} pressed: {value}")

        if self.is_pressed == value:
            return

        self.is_pressed = value
        if value:
            self._loop.call_soon_threadsafe(self._pressed_event.set)
            for callback in self._on_pressed_callbacks:
                self._schedule(callback)
        else:
            self._loop.call_soon_threadsafe(self._released_event.set)
            for callback in self._on_released_callbacks:
                self._schedule(callback)

    async def wait_for_button_press(self):
        self._pressed_event.clear()
        await self._pressed_event.wait()
        return True

    async def wait_for_button_release(self):
        self._released_event.clear()
        await self._released_event.wait()
        return True
