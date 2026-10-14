# naoqi-control

Laptop-side control of a NAO over NAOqi. One `NaoController` tries ports 9559 (older NAO versions) and 9561 (newer NAO versions) until one accepts, owns the worker thread that serializes blocking qi calls, and holds the pieces a caller usually wants:

- `tts`: say, async say, say-until-button, stop, speed, language, pitch.
- `audio`: master speaker volume.
- `motion`: posture, stiffness, joint moves, and named gestures (wave, farewell, nod, shake). Gestures are `Animation` keyframes.
- `camera`: one frame or a stream from the top or bottom camera.
- `buttons`: head, bumper, and hand events as async press and release callbacks.
- `leds`: `Leds.fade` for one group. Conversation colors stay in the app that owns them.

Pass `log=` to `NaoController` when the caller wants spoken lines and failures on its own log. The object needs `error`, `verbose`, and `nao` methods. Without it, those lines go to the `naoqi_control` logger.

The package requires Python 3.12. On Windows, use the Dev Container, since `qi` has no Windows wheels.

```python
from naoqi_control import NaoController

nao = NaoController("192.168.2.50", log=my_log)
await nao.prepare(volume=80, speech_speed=90, posture="Sit")
await nao.speak("Hallo.", timeout=8)
nao.motion.wave(["left"])
frame = await nao.camera.capture("top")
```
