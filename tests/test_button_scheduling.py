import asyncio
import threading
import unittest
from unittest.mock import MagicMock

from naoqi_control.buttons import Button


def _mock_session():
    session = MagicMock()
    memory = MagicMock()
    subscriber = MagicMock()
    memory.subscriber.return_value = subscriber
    session.service.return_value = memory
    return session


class ButtonSchedulingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.loop = asyncio.get_running_loop()
        self.button = Button(_mock_session(), subscriber_name="TestButton")

    async def _wait_for(self, event: asyncio.Event, timeout: float = 1.0):
        await asyncio.wait_for(event.wait(), timeout=timeout)

    async def test_pressed_callback_runs_on_event_loop_from_foreign_thread(self):
        done = asyncio.Event()
        seen_loop = None

        async def on_pressed():
            nonlocal seen_loop
            seen_loop = asyncio.get_running_loop()
            done.set()

        self.button.on_pressed(on_pressed)

        thread = threading.Thread(target=self.button._handler, args=(True,))
        thread.start()
        thread.join()

        await self._wait_for(done)
        self.assertIs(seen_loop, self.loop)

    async def test_released_callback_runs_on_event_loop_from_foreign_thread(self):
        self.button.is_pressed = True

        done = asyncio.Event()
        seen_loop = None

        async def on_released():
            nonlocal seen_loop
            seen_loop = asyncio.get_running_loop()
            done.set()

        self.button.on_released(on_released)

        thread = threading.Thread(target=self.button._handler, args=(False,))
        thread.start()
        thread.join()

        await self._wait_for(done)
        self.assertIs(seen_loop, self.loop)


if __name__ == "__main__":
    unittest.main()
