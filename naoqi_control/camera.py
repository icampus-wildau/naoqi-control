from __future__ import annotations

import itertools
from dataclasses import dataclass
from typing import Literal

import qi

CameraName = Literal["top", "bottom"]
ResolutionName = Literal["qqvga", "qvga", "vga", "4vga"]
ColorSpaceName = Literal["rgb", "bgr", "yuv422"]

_CAMERAS: dict[CameraName, int] = {"top": 0, "bottom": 1}
_RESOLUTIONS: dict[ResolutionName, int] = {
    "qqvga": 0,
    "qvga": 1,
    "vga": 2,
    "4vga": 3,
}
_COLOR_SPACES: dict[ColorSpaceName, int] = {"yuv422": 9, "rgb": 11, "bgr": 13}
_SUBSCRIBERS = itertools.count(1)


@dataclass(frozen=True)
class CameraImage:
    """One frame. ``data`` is the raw pixel buffer from ``ALVideoDevice``."""

    width: int
    height: int
    color_space: ColorSpaceName
    data: bytes
    camera: CameraName


class Camera:
    """Frames from the NAO's top and bottom cameras."""

    def __init__(self, session: qi.Session, call_qi, is_closing) -> None:
        self._video = session.service("ALVideoDevice")
        self._call_qi = call_qi
        self._is_closing = is_closing

    async def capture(
        self,
        camera: CameraName = "top",
        *,
        resolution: ResolutionName = "vga",
        color_space: ColorSpaceName = "rgb",
    ) -> CameraImage:
        """Subscribe, take one frame, and unsubscribe."""
        async with self.open(camera, resolution=resolution, color_space=color_space) as stream:
            return await stream.read()

    async def capture_top(self, **kwargs) -> CameraImage:
        """Take one frame from the top camera."""
        return await self.capture("top", **kwargs)

    async def capture_bottom(self, **kwargs) -> CameraImage:
        """Take one frame from the bottom camera."""
        return await self.capture("bottom", **kwargs)

    def open(
        self,
        camera: CameraName = "top",
        *,
        resolution: ResolutionName = "vga",
        color_space: ColorSpaceName = "rgb",
        fps: int = 5,
    ) -> CameraStream:
        """Return a stream that subscribes once. Use it as an async context manager."""
        return CameraStream(
            self._video,
            self._call_qi,
            camera=camera,
            resolution=resolution,
            color_space=color_space,
            fps=fps,
        )


class CameraStream:
    """A subscribed camera. ``read`` returns the next frame and ``close`` unsubscribes."""

    def __init__(
        self,
        video,
        call_qi,
        *,
        camera: CameraName,
        resolution: ResolutionName,
        color_space: ColorSpaceName,
        fps: int,
    ) -> None:
        self._video = video
        self._call_qi = call_qi
        self._camera = camera
        self._resolution = resolution
        self._color_space = color_space
        self._fps = fps
        self._subscriber = f"naoqi{next(_SUBSCRIBERS)}"
        self._handle: str | None = None

    async def __aenter__(self) -> CameraStream:
        await self._subscribe()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    async def read(self) -> CameraImage:
        """Return the next frame, subscribing first when the stream is not open yet."""
        if self._handle is None:
            await self._subscribe()
        image = await self._call_qi(self._grab)
        if image is None:
            raise RuntimeError("Could not read a camera frame")
        return image

    async def close(self) -> None:
        """Unsubscribe. A second close does nothing."""
        handle = self._handle
        self._handle = None
        if handle is None:
            return
        await self._call_qi(self._video.unsubscribe, handle)

    async def _subscribe(self) -> None:
        handle = await self._call_qi(self._subscribe_blocking)
        if not handle:
            raise RuntimeError("Could not subscribe to the camera")
        self._handle = handle

    def _subscribe_blocking(self) -> str:
        return self._video.subscribeCamera(
            self._subscriber,
            _CAMERAS[self._camera],
            _RESOLUTIONS[self._resolution],
            _COLOR_SPACES[self._color_space],
            self._fps,
        )

    def _grab(self) -> CameraImage:
        image = self._video.getImageRemote(self._handle)
        return CameraImage(
            width=int(image[0]),
            height=int(image[1]),
            color_space=self._color_space,
            data=_as_bytes(image[6]),
            camera=self._camera,
        )


def _as_bytes(data: object) -> bytes:
    if isinstance(data, bytes):
        return data
    if isinstance(data, bytearray):
        return bytes(data)
    if isinstance(data, memoryview):
        return data.tobytes()
    tobytes = getattr(data, "tobytes", None)
    if callable(tobytes):
        return tobytes()
    return bytes(data)  # type: ignore[arg-type]
