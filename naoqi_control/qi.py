from __future__ import annotations

import asyncio
import queue
import threading

import qi

# qi connect on a robot is usually a couple of seconds. Past this, the
# broker is not coming back on this attempt.
QI_CONNECT_TIMEOUT_SECS = 15.0
# Sitting down from Stand is the slow posture. A hang must not freeze startup.
QI_PREPARE_TIMEOUT_SECS = 30.0
QI_CLOSE_TIMEOUT_SECS = 15.0
QI_EYE_TIMEOUT_SECS = 5.0
QI_STOP_SPEAKING_TIMEOUT_SECS = 5.0


class QiWorker:
    """One thread for every blocking qi call so they cannot overlap."""

    def __init__(self) -> None:
        self._queue: queue.Queue = queue.Queue()
        self._thread = threading.Thread(target=self._run, name="nao-qi")
        self._thread.daemon = True
        self._thread.start()

    def stop(self) -> None:
        if self._thread.is_alive():
            self._queue.put(None)

    def _run(self) -> None:
        while True:
            item = self._queue.get()
            if item is None:
                return
            fn, args, kwargs, loop, future = item
            if future.cancelled():
                continue
            try:
                result = fn(*args, **kwargs)
            except Exception as exc:
                loop.call_soon_threadsafe(self._finish_future, future, None, exc)
            else:
                loop.call_soon_threadsafe(self._finish_future, future, result, None)

    @staticmethod
    def _finish_future(
        future: asyncio.Future,
        result: object,
        error: BaseException | None,
    ) -> None:
        if future.done():
            return
        if error is not None:
            future.set_exception(error)
        else:
            future.set_result(result)

    async def call(self, fn, *args, timeout: float | None = None, **kwargs):
        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()
        self._queue.put((fn, args, kwargs, loop, future))
        if timeout is None:
            return await future
        return await asyncio.wait_for(future, timeout)


class QiCall:
    """Post a qi method and poll its future without holding the worker."""

    @staticmethod
    def start(obj, method_name: str, *args):
        """Start a qi call without holding the worker until it finishes.

        ``session.service()`` proxies take ``_async=True`` and return a
        ``qi.Future``. Older ``ALProxy`` objects expose the same idea as
        ``post.<method>``. A plain call is the fallback, and it blocks.
        """
        method = getattr(obj, method_name)
        try:
            future = method(*args, _async=True)
        except TypeError:
            future = None
        else:
            if QiCall.is_pending(future):
                return future
            return None

        post = getattr(obj, "post", None)
        post_method = getattr(post, method_name, None) if post is not None else None
        if callable(post_method):
            posted = post_method(*args)
            if QiCall.is_pending(posted):
                return posted
            return None
        method(*args)
        return None

    @staticmethod
    def is_finished(future: object) -> bool:
        is_finished = getattr(future, "isFinished", None)
        if callable(is_finished):
            return bool(is_finished())
        done = getattr(future, "done", None)
        if callable(done):
            return bool(done())
        return True

    @staticmethod
    def is_pending(value: object) -> bool:
        """True for a qi future or a test double that really defines ``isFinished``.

        ``MagicMock`` invents ``isFinished`` on access, so that does not count.
        """
        if isinstance(value, qi.Future):
            return True
        return any("isFinished" in cls.__dict__ for cls in type(value).__mro__)

    @staticmethod
    async def wait(future: object, call_qi, is_closing) -> None:
        """Poll ``future`` without holding the worker between checks."""
        while True:
            if is_closing():
                return
            try:
                finished = await call_qi(
                    QiCall.is_finished,
                    future,
                    timeout=QI_EYE_TIMEOUT_SECS,
                )
            except TimeoutError:
                continue
            if finished:
                return
            await asyncio.sleep(0.05)
