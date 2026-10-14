from __future__ import annotations

import unittest

from naoqi_control.camera import Camera


class _Video:
    def __init__(self) -> None:
        self.subscribed: list[tuple] = []
        self.unsubscribed: list[str] = []

    def subscribeCamera(self, name, index, resolution, color, fps):
        self.subscribed.append((name, index, resolution, color, fps))
        return name

    def getImageRemote(self, handle):
        return [4, 2, 3, 11, 0, 0, b"abcdefghijkl", 0, 0.0, 0.0]

    def unsubscribe(self, handle):
        self.unsubscribed.append(handle)


def _camera(video: _Video) -> Camera:
    camera = Camera.__new__(Camera)
    camera._video = video

    async def call_qi(fn, *args, timeout=None, allow_when_closing=False, **kwargs):
        return fn(*args, **kwargs)

    camera._call_qi = call_qi
    camera._is_closing = lambda: False
    return camera


class CameraTests(unittest.IsolatedAsyncioTestCase):
    async def test_capture_subscribes_reads_and_unsubscribes(self) -> None:
        video = _Video()
        camera = _camera(video)

        image = await camera.capture("top", resolution="qvga", color_space="rgb")

        self.assertEqual(image.width, 4)
        self.assertEqual(image.height, 2)
        self.assertEqual(image.data, b"abcdefghijkl")
        self.assertEqual(image.camera, "top")
        self.assertEqual(image.color_space, "rgb")
        name, index, resolution, color, fps = video.subscribed[0]
        self.assertEqual(index, 0)
        self.assertEqual(resolution, 1)
        self.assertEqual(color, 11)
        self.assertEqual(fps, 5)
        self.assertEqual(video.unsubscribed, [name])

    async def test_stream_reuses_one_subscription(self) -> None:
        video = _Video()
        camera = _camera(video)

        async with camera.open("bottom", resolution="vga", color_space="bgr", fps=10) as stream:
            first = await stream.read()
            second = await stream.read()

        self.assertEqual(len(video.subscribed), 1)
        self.assertEqual(video.subscribed[0][1], 1)
        self.assertEqual(video.subscribed[0][2], 2)
        self.assertEqual(video.subscribed[0][3], 13)
        self.assertEqual(video.subscribed[0][4], 10)
        self.assertEqual(first.camera, "bottom")
        self.assertEqual(second.color_space, "bgr")
        self.assertEqual(video.unsubscribed, [video.subscribed[0][0]])

    async def test_capture_bottom_uses_the_bottom_camera(self) -> None:
        video = _Video()
        camera = _camera(video)

        image = await camera.capture_bottom(resolution="qqvga")

        self.assertEqual(image.camera, "bottom")
        self.assertEqual(video.subscribed[0][1], 1)
        self.assertEqual(video.subscribed[0][2], 0)


if __name__ == "__main__":
    unittest.main()
