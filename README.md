# naoqi-control

*Speak, move, and read a NAO from Python.*

![PyPI](https://img.shields.io/pypi/v/naoqi-control?style=flat-square)
![Python](https://img.shields.io/badge/python-3.12-blue?style=flat-square)
![CI](https://img.shields.io/github/actions/workflow/status/icampus-wildau/naoqi-control/pypi.yml?style=flat-square&label=CI)
![License: Apache 2.0](https://img.shields.io/badge/license-Apache%20License%202.0-blue)


Async control of a NAO from Python. `NaoController` connects to NAOqi, runs blocking qi calls, exposes speech, speaker volume, motion, cameras, touch, and LEDs.

Use it when a program on the laptop should:

- let the NAO speek
- move the NAO
- watch for button events

Note: Microphone-Stream is not natively available vai NAOqi. Use [nao-websocket-bridge-client](https://github.com/icampus-wildau/nao-websocket-bridge-client) for streaming use cases.

## Installation:

```bash
uv add naoqi-control
```

You can also install it into an activated Python 3.12 environment:

```bash
python -m pip install naoqi-control
```

## Requirements

Use Python 3.12. The `qi` wheel on PyPI is Linux x86-64 only.

> [!WARNING]
> Confirm the machine is Linux x86-64 before you install. On Windows, use Windows Subsystem for Linux (WSL) or the [Dev Container](#dev-container).

## Dev Container

[`.devcontainer/`](.devcontainer/) is the editor environment for this repository, and a template for a project that installs `naoqi-control`. The image is Python 3.12 on Debian, with `uv`. The container uses the host network so it can reach NAOqi on ports 9559 and 9561.

Open this repository and run **Dev Containers: Reopen in Container**. On start the container runs `uv sync --locked`. The terminal is inside the container. Python is `/opt/venv/bin/python`.

Copy `.devcontainer/` into your own checkout to reuse it. That project needs `pyproject.toml` and `uv.lock` (`uv lock` writes the lockfile). On Docker Desktop 4.34 or newer, enable **Settings → Resources → Network → Enable host networking**, then apply and restart. Host networking does not work with Enhanced Container Isolation.

## Usage

### Connect and speak

Construct the controller inside a running event loop. It tries port 9559, then 9561, and keeps the first port that accepts.

```python
import asyncio
from naoqi_control import NaoController

async def main() -> None:
    nao = NaoController("192.168.2.50")
    try:
        await nao.prepare(volume=80, speech_speed=90, posture="Sit")
        await nao.speak("Hallo.", timeout=8)
        await nao.motion.wave_and_wait(["left"])
        image = await nao.camera.capture("top")
        print(image.width, image.height, len(image.data))
    finally:
        await nao.restore()
        await nao.close()

asyncio.run(main())
```

`prepare` turns autonomous life off. If the current posture is `Sit` or `SitRelax`, that posture stays. Otherwise the robot moves to `posture`. After a sit, body stiffness is released. Then it sets the speaker volume and speech speed. A speed of 100 is normal NAO speech. `restore` puts autonomous life back. `close` stops speech and the session.

Pass `ports=` to try a different list, for example `ports=(9561,)`. Pass `log=` an object with `error`, `verbose`, and `nao` methods. Without it, those lines go to the `naoqi_control.log` logger.

The following snippets use the `nao` from above.

### Speech

```python
# Waits, but LEDs and stop_speaking can still run.
await nao.speak("Hallo.", timeout=8)
# Blocks until the utterance ends.
nao.say("Hallo.")
nao.stop_speaking()

# Stops early on a button press or when stop is set.
# Returns "finished", "interrupted", or "timed_out".
result = await nao.tts.say_until("Hallo.", button=nao.buttons.front_head)

nao.tts.set_language("German")
# TTS gain from 0 to 1. The speaker amp is audio.
nao.tts.set_volume(0.8)
# 100 is normal NAO speech.
nao.tts.set_speed(100)
# NAOqi pitchShift.
nao.tts.set_pitch_shift(1.2)
# Any other ALTextToSpeech parameter.
nao.tts.set_parameter("speed", 90)
```

### Audio

```python
# Speaker amp, separate from tts.set_volume.
await nao.audio.set_output_volume(80)
volume = await nao.audio.get_output_volume()
```

### Motion

```python
from naoqi_control import Animation

posture = await nao.motion.get_posture()
# Named posture, such as "Sit" or "Stand".
# Sit and SitRelax release body stiffness when the move finishes.
await nao.motion.go_to_posture("Sit", speed=0.5)

# Stiffness accepts a joint name or a chain.
# Chains: Head, LArm, RArm, LLeg, RLeg, Body.
await nao.motion.set_stiffness("Body", 1.0)

# Joints: HeadYaw, HeadPitch,
# LShoulderPitch, LShoulderRoll, LElbowYaw, LElbowRoll, LWristYaw, LHand,
# LHipYawPitch, LHipRoll, LHipPitch, LKneePitch, LAnklePitch, LAnkleRoll,
# RHipYawPitch, RHipRoll, RHipPitch, RKneePitch, RAnklePitch, RAnkleRoll,
# RShoulderPitch, RShoulderRoll, RElbowYaw, RElbowRoll, RWristYaw, RHand.
# LHipYawPitch and RHipYawPitch are one motor with two names.
angles = await nao.motion.get_angles(["HeadYaw"], use_sensors=True)
await nao.motion.set_angles(["HeadYaw"], [0.0], speed=0.2)

# ALMotion.stopMove.
await nao.motion.stop()

# There are two predefined arm maving and a head nodding and a head shaking movement.
# Returns immediately. Sides are "left" and "right".
nao.motion.wave(["left"])

# The same motions are all available as awaitable functions
await nao.motion.wave_and_wait(["left", "right"])
await nao.motion.farewell_and_wait(["right"])
await nao.motion.nod_and_wait()
await nao.motion.shake_and_wait()

# play returns immediately. play_and_wait does not.
nao.motion.play(Animation.wave("left"))
await nao.motion.play_and_wait(Animation.nod())
# Stop a gesture that is still running.
await nao.motion.cancel()
```

### Camera

```python
# "top" or "bottom". One frame, then unsubscribe.
image = await nao.camera.capture("top")
# resolution: qqvga, qvga, vga (default), 4vga.
# color_space: rgb (default), bgr, yuv422.
image = await nao.camera.capture("bottom", resolution="qvga", color_space="bgr")
image = await nao.camera.capture_top()

# fps defaults to 5. Stays subscribed.
async with nao.camera.open("top", fps=5) as stream:
    # frame.width, frame.height, frame.color_space, frame.data, frame.camera
    frame = await stream.read()
```

### Buttons

```python
# Also: middle_head, back_head, left_bumper, right_bumper, left_hand, right_hand.

async def on_front() -> None:
    await nao.speak("Ja.", timeout=8)

# Async callback. on_released is the same shape.
nao.buttons.front_head.on_pressed(on_front)
await nao.buttons.front_head.wait_for_button_press()
await nao.buttons.front_head.wait_for_button_release()
pressed = nao.buttons.front_head.is_pressed
```

### LEDs

```python
# duration defaults to 0.15 seconds.
nao.leds.fade("FaceLeds", 0x0066FF)
# Color is an int or a hex string.
nao.leds.fade("FaceLeds", "#0066FF", 0.3)
```

## Call another NAOqi service

`call_qi` runs one blocking callable on the shared `qi` worker. This example reads the NAOqi version from the system service (`ALSystem`).

```python
def read_version() -> str:
    system = nao.session.service("ALSystem")
    return system.systemVersion()

version = await nao.call_qi(read_version)
```

## Local development

With this checkout next to the app:

```bash
uv add --editable ../naoqi-control
```

Restore that project's `pyproject.toml` and lockfile before committing. The committed dependency stays the PyPI release.
