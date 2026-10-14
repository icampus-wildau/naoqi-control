from __future__ import annotations

from typing import Literal

from naoqi_control.log import Log
from naoqi_control.qi import QiCall

Chain = Literal["Head", "LArm", "RArm", "LLeg", "RLeg", "Body"]
Side = Literal["left", "right"]

_HEAD_LIMITS = {
    "HeadPitch": (-0.67, 0.51),
    "HeadYaw": (-2.08, 2.08),
}

_ARM_JOINTS = (
    "ShoulderPitch",
    "ShoulderRoll",
    "ElbowYaw",
    "ElbowRoll",
    "WristYaw",
    "Hand",
)


class Animation:
    """One keyframe move on a NAOqi stiffness chain.

    ``chain`` is the group passed to ``ALMotion.setStiffnesses``: ``Head``,
    ``LArm``, ``RArm``, ``LLeg``, ``RLeg``, or ``Body``. Motion uses that same
    name so two animations on one chain do not run together.

    ``return_to_origin=True`` plays the keyframes and then the pose captured at
    the start, and releases stiffness. ``return_to_origin=False`` stops on the
    last keyframe and leaves the chain at ``stiffness``, so the pose holds.
    """

    # H25 joint names in NAOqi order. HipYawPitch is one motor with two names,
    # so this list has 26 entries for 25 degrees of freedom.
    JOINTS: tuple[str, ...] = (
        "HeadYaw",
        "HeadPitch",
        "LShoulderPitch",
        "LShoulderRoll",
        "LElbowYaw",
        "LElbowRoll",
        "LWristYaw",
        "LHand",
        "LHipYawPitch",
        "LHipRoll",
        "LHipPitch",
        "LKneePitch",
        "LAnklePitch",
        "LAnkleRoll",
        "RHipYawPitch",
        "RHipRoll",
        "RHipPitch",
        "RKneePitch",
        "RAnklePitch",
        "RAnkleRoll",
        "RShoulderPitch",
        "RShoulderRoll",
        "RElbowYaw",
        "RElbowRoll",
        "RWristYaw",
        "RHand",
    )
    CHAINS: tuple[Chain, ...] = ("Head", "LArm", "RArm", "LLeg", "RLeg", "Body")
    HEAD_LIMITS = _HEAD_LIMITS

    def __init__(
        self,
        *,
        name: str,
        chain: Chain,
        joints: list[str],
        keyframes: list[list[float]],
        times: list[list[float]],
        relative: bool = False,
        return_to_origin: bool = True,
        return_secs: float = 1.0,
        stiffness: float = 0.8,
        limits: dict[str, tuple[float, float]] | None = None,
    ) -> None:
        self.name = name
        self.chain = chain
        self.joints = joints
        self.keyframes = keyframes
        self.times = times
        self.relative = relative
        self.return_to_origin = return_to_origin
        self.return_secs = return_secs
        self.stiffness = stiffness
        self.limits = limits

    async def play(self, *, session, call_qi, is_closing, log: Log) -> None:
        """Stiffen ``chain``, post ``angleInterpolation``, then finish the move."""
        started = await call_qi(self._begin, session, is_closing, log)
        if not started:
            return
        future, motion, chain, names, rest, return_secs = started
        try:
            await QiCall.wait(future, call_qi, is_closing)
            if is_closing() or not self.return_to_origin:
                return
            back = await call_qi(
                QiCall.start,
                motion,
                "angleInterpolation",
                names,
                [[angle] for angle in rest],
                [[return_secs] for _ in names],
                True,
            )
            if back is not None:
                await QiCall.wait(back, call_qi, is_closing)
        finally:
            if self.return_to_origin and not is_closing():
                await call_qi(motion.setStiffnesses, chain, 0.0)

    def _begin(self, session, is_closing, log: Log):
        try:
            motion = session.service("ALMotion")
            rest = list(motion.getAngles(self.joints, True))
            if is_closing():
                return None
            angles = self.keyframes
            if self.relative:
                angles = []
                for index, name in enumerate(self.joints):
                    offsets = self.keyframes[index]
                    angles.append(
                        [self._clamp(name, rest[index] + offset) for offset in offsets]
                    )
            motion.setStiffnesses(self.chain, self.stiffness)
            try:
                future = QiCall.start(
                    motion,
                    "angleInterpolation",
                    self.joints,
                    angles,
                    self.times,
                    True,
                )
            except Exception:
                if not is_closing():
                    motion.setStiffnesses(self.chain, 0.0)
                raise
            if future is not None:
                return (future, motion, self.chain, self.joints, rest, self.return_secs)
            if self.return_to_origin:
                try:
                    if not is_closing():
                        QiCall.start(
                            motion,
                            "angleInterpolation",
                            self.joints,
                            [[angle] for angle in rest],
                            [[self.return_secs] for _ in self.joints],
                            True,
                        )
                finally:
                    if not is_closing():
                        motion.setStiffnesses(self.chain, 0.0)
        except Exception as exc:
            log.error(f"{self.name}: {exc}")
        return None

    def _clamp(self, name: str, angle: float) -> float:
        if self.limits is None or name not in self.limits:
            return angle
        low, high = self.limits[name]
        return max(low, min(high, angle))

    @staticmethod
    def wave(side: Side) -> Animation:
        """Build the greeting wave for one arm."""
        chain, prefix, outward = _arm_side(side)
        return Animation(
            name=f"wave_{side}",
            chain=chain,
            joints=[f"{prefix}{joint}" for joint in _ARM_JOINTS],
            keyframes=[
                [-0.3],
                [0.35 * outward],
                [-1.2 * outward],
                [-0.9 * outward],
                [-1.0, 1.0, -1.0, 1.0, -1.0, 1.0],
                [1.0],
            ],
            times=[
                [1.0],
                [1.0],
                [1.0],
                [1.0],
                [1.4, 1.8, 2.2, 2.6, 3.0, 3.4],
                [1.0],
            ],
            return_secs=1.0,
        )

    @staticmethod
    def farewell(side: Side) -> Animation:
        """Build the short farewell lift for one arm."""
        chain, prefix, outward = _arm_side(side)
        return Animation(
            name=f"farewell_{side}",
            chain=chain,
            joints=[f"{prefix}{joint}" for joint in _ARM_JOINTS],
            keyframes=[
                [-0.6],
                [0.2 * outward],
                [-0.6 * outward],
                [-0.45 * outward],
                [0.35, -0.15],
                [0.4],
            ],
            times=[
                [1.0],
                [0.6],
                [0.6],
                [0.6],
                [0.9, 1.2],
                [0.6],
            ],
            return_secs=1.2,
        )

    @staticmethod
    def nod() -> Animation:
        """Build a small yes-nod. Keyframes are offsets from the current pitch."""
        return Animation(
            name="nod",
            chain="Head",
            joints=["HeadPitch"],
            keyframes=[[-0.1, 0.2, 0.0]],
            times=[[0.3, 0.6, 1]],
            relative=True,
            return_secs=0.35,
            limits=dict(_HEAD_LIMITS),
        )

    @staticmethod
    def shake() -> Animation:
        """Build a small no-shake. Keyframes are offsets from the current yaw."""
        return Animation(
            name="shake",
            chain="Head",
            joints=["HeadYaw"],
            keyframes=[[0.28, -0.28, 0.18]],
            times=[[0.5, 0.9, 1.3]],
            relative=True,
            return_secs=0.3,
            limits=dict(_HEAD_LIMITS),
        )


def _arm_side(side: Side) -> tuple[Chain, str, float]:
    if side == "left":
        return "LArm", "L", 1.0
    return "RArm", "R", -1.0
