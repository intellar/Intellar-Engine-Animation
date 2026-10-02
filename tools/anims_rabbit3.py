"""Writes the rabbit3 animations (tools/animations/rabbit3.json).

    python tools/anims_rabbit3.py --rig tools/rigs/rabbit3.json \
        --out tools/animations/rabbit3.json

The animations are **written here, not in Blender**: the values are deltas from
the rest pose of the rig, in screen pixels and degrees (positive = clockwise).
This is deliberate -- timing (a 90 ms bounce, an 80 ms blink) is tuned far faster
in a table than in a timeline, and the result is versionable and testable.

Two animations are produced:

* `idle_loop`  : breathing + a wind balance (the legs follow the torso), perfectly
  looping (the pose at t=0 and the one at t=duration are identical), with a blink
  and ears that trail the sway with a delay and inertia; the upper part of each
  leg follows the torso.
* `peek`       : one-shot -- the rabbit is off screen, leaps into the panel, looks
  left then right, does a small hop in place, and dives back down.

Pose conventions (dict of bone name -> deltas):

    dx, dy  : translation in pixels (positive dy = downwards on screen)
    rot     : rotation in degrees, clockwise on screen
    sx, sy  : scale applied to the part (1.0 = normal size); the scale is not
              inherited by child bones (see docs/FORMAT.md)

A bone missing from a pose keeps its rest position. Keys are sorted by increasing
time and deltas sharing the same time are merged.
"""
from __future__ import annotations

import argparse
import json
import math
import os

import iska_common as iska

TAU = 2.0 * math.pi

# `footL`/`footR` hang from `root`, not from the `torso`, so they move only if
# they are keyed: this is the fraction of the torso's shift they inherit. The
# upper part of the legs then follows the body while the feet stay near the
# ground (a rigid follow, 1.0, would lift them off it).
LEG_FOLLOW = 0.6


def merge(keys: dict, t: float, deltas: dict) -> None:
    """Adds a partial pose at time `t` (merged per bone)."""
    slot = keys.setdefault(int(round(t)), {})
    for bone, delta in deltas.items():
        slot.setdefault(bone, {}).update(delta)


def ear_angle(t, omega, phase, drive, resonance, damping) -> float:
    """Local angle of a passive ear answering the sway `drive * sin(omega*t+phase)`.

    The ear does not copy the head: it hangs and *answers* it. Modelled as a
    driven damped oscillator (`theta'' + 2.z.w0.theta' + w0^2.theta = w0^2.drive`),
    its steady state -- the transients are long gone by the time the loop starts
    -- is a sinusoid **of the same period** (so the loop still joins up), but
    delayed by `atan2(2.z.w0.w, w0^2 - w^2)` and scaled by the resonance. The delay
    is what the eye reads as "following"; the gain (the ear is driven near its
    resonance) is the inertia that lets it swing further and later than the body
    carrying it.
    """
    w0_sq = resonance * resonance
    gain = w0_sq / math.sqrt((w0_sq - omega * omega) ** 2
                             + (2.0 * damping * resonance * omega) ** 2)
    lag = math.atan2(2.0 * damping * resonance * omega, w0_sq - omega * omega)
    return drive * gain * math.sin(omega * t + phase - lag)


def idle_loop() -> dict:
    """Breathing + a wind balance, with trailing ears: a 2400 ms loop, seamless.

    The sines have periods that divide the duration (2400 ms and 1200 ms), so the
    pose at t=2400 is strictly identical to the one at t=0: the loop does not
    jump. The blink is placed inside the loop.

    `root` is left perfectly at rest and never appears in a key. The balance is
    carried by the `torso` (and everything it carries: head, ears, eyes, arms),
    which breathes (dy + a pinch of squash) and leans into the wind (dx + rot).
    The ears do not follow that lean rigidly: each answers it with a delay and its
    own inertia (`ear_angle`), so they trail the head. The legs, hung off `root`
    rather than the torso, are given `LEG_FOLLOW` of the torso's shift: the upper
    part follows the body, the feet only drift.

    The blink keys are added **on the breathing grid**: a key that only mentioned
    the eyes would let the body snap back to rest for the length of a blink (the
    bug was caught by comparing hashes between the C++ runtime and the Python
    tooling).
    """
    duration = 2400
    blink = [(1440, 0.0), (1520, 0.92), (1600, 0.92), (1660, 0.0)]
    times = sorted(set(range(0, duration + 1, 100)) | {t for t, _ in blink})

    breath_w = TAU / duration        # 1 cycle: inhale / exhale
    sway_w = TAU / 1200.0            # 2 cycles: the wind

    keys = {}
    for t in times:
        breath = math.sin(breath_w * t)
        sway = math.sin(sway_w * t)
        merge(keys, t, {
            # the balance lives in the torso (`root` untouched): everything the
            # torso carries -- head, ears, eyes, arms -- follows it
            "torso": {"dx": round(2.4 * sway, 3),
                      "rot": round(1.7 * sway, 2),
                      "dy": round(-2.6 * breath, 3),
                      "sx": round(1.0 + 0.022 * breath, 4),
                      "sy": round(1.0 - 0.038 * breath, 4)},
            # the legs hang off `root`, so they inherit nothing: they are keyed
            # with a fraction of the torso's shift -- the upper part of the legs
            # follows the body, the feet only drift
            "footL": {"dx": round(LEG_FOLLOW * 2.4 * sway, 3),
                      "dy": round(LEG_FOLLOW * -2.6 * breath, 3)},
            "footR": {"dx": round(LEG_FOLLOW * 2.4 * sway, 3),
                      "dy": round(LEG_FOLLOW * -2.6 * breath, 3)},
            "head": {"dy": round(-1.1 * math.sin(breath_w * t - 0.6), 3),
                     "rot": round(1.2 * math.sin(sway_w * t - 0.5), 2)},
            # the ears trail the sway: a quarter of a beat behind (earL, driven at
            # its resonance) and a touch quicker (earR, above resonance)
            "earL": {"rot": round(ear_angle(t, sway_w, 0.0, 3.5,
                                            1.00 * sway_w, 0.28), 2)},
            "earR": {"rot": round(ear_angle(t, sway_w, 0.0, 2.6,
                                            1.18 * sway_w, 0.34), 2)},
            "armL": {"rot": round(2.6 * math.sin(sway_w * t - 0.9), 2)},
            "armR": {"rot": round(-2.6 * math.sin(sway_w * t - 0.9), 2)},
        })

    # blink: the eyes squash onto themselves (their pivot is their centre)
    for t, closed in blink:
        merge(keys, t, {"eyeL": {"sy": round(1.0 - closed, 4)},
                        "eyeR": {"sy": round(1.0 - closed, 4)}})

    ordered = [{"t": t, "pose": keys[t]} for t in sorted(keys)]
    return {"loop": True, "duration": duration, "keys": ordered}


def peek() -> dict:
    """2700 ms one-shot: off screen -> leap -> glances -> hop -> dive back down.

    `below` moves the rabbit below the panel: the topmost part (the ears) sits
    ~95 px from the top of the panel, so at least 225 px are needed for it to
    disappear. 240 px of margin are used.
    """
    below = 240
    keys = {}

    def at(t, **bones):
        merge(keys, t, bones)

    # -- hidden, then anticipation ------------------------------------------
    at(0, root={"dy": below}, torso={"sy": 1.05, "sx": 0.97},
       earL={"rot": -22}, earR={"rot": 22}, head={"dy": 4},
       armL={"rot": 14}, armR={"rot": -14})
    at(120, root={"dy": below + 6}, torso={"sy": 1.08, "sx": 0.95},
       earL={"rot": -26}, earR={"rot": 26}, head={"dy": 6},
       armL={"rot": 18}, armR={"rot": -18})
    # -- burst out (vertical stretch) ---------------------------------------
    at(240, root={"dy": 60}, torso={"sy": 1.12, "sx": 0.93},
       earL={"rot": -16}, earR={"rot": 16}, armL={"rot": 10}, armR={"rot": -10})
    at(330, root={"dy": -18}, torso={"sy": 1.07, "sx": 0.96},
       earL={"rot": -8}, earR={"rot": 8}, armL={"rot": 4}, armR={"rot": -4})
    at(430, root={"dy": 0}, torso={"sy": 1.0, "sx": 1.0},
       earL={"rot": 0}, earR={"rot": 0}, armL={"rot": 0}, armR={"rot": 0})
    # -- squash on landing ---------------------------------------------------
    at(520, root={"dy": 5}, torso={"sy": 0.92, "sx": 1.06},
       earL={"rot": 12}, earR={"rot": -12}, armL={"rot": -8}, armR={"rot": 8})
    at(640, root={"dy": 0}, torso={"sy": 1.0, "sx": 1.0},
       earL={"rot": 0}, earR={"rot": 0}, armL={"rot": 0}, armR={"rot": 0})

    # -- glance left ---------------------------------------------------------
    at(780, root={"dx": -12, "dy": 2}, torso={"rot": 4.0},
       head={"rot": -3.0}, eyeL={"dx": -1.8}, eyeR={"dx": -1.8},
       earL={"rot": -12}, earR={"rot": 8}, armL={"rot": -6}, armR={"rot": 6})
    at(980, root={"dx": -14, "dy": 2}, torso={"rot": 4.5},
       head={"rot": -2.0}, eyeL={"dx": -2.0}, eyeR={"dx": -2.0},
       earL={"rot": -8}, earR={"rot": 10})
    # -- glance right (quick pass through the centre) ------------------------
    at(1080, root={"dx": 0, "dy": 0}, torso={"rot": 0.0}, head={"rot": 0.0},
       eyeL={"dx": 0.0}, eyeR={"dx": 0.0}, earL={"rot": 4}, earR={"rot": -4})
    at(1180, root={"dx": 12, "dy": 2}, torso={"rot": -4.0},
       head={"rot": 3.0}, eyeL={"dx": 2.0}, eyeR={"dx": 2.0},
       earL={"rot": 10}, earR={"rot": -12}, armL={"rot": 6}, armR={"rot": -6})
    at(1400, root={"dx": 14, "dy": 2}, torso={"rot": -4.5},
       head={"rot": 2.0}, eyeL={"dx": 2.2}, eyeR={"dx": 2.2},
       earL={"rot": 8}, earR={"rot": -8})
    at(1600, root={"dx": 0, "dy": 0}, torso={"rot": 0.0}, head={"rot": 0.0},
       eyeL={"dx": 0.0}, eyeR={"dx": 0.0}, earL={"rot": 0}, earR={"rot": 0},
       armL={"rot": 0}, armR={"rot": 0})

    # -- small hop in place --------------------------------------------------
    at(1760, root={"dy": 9}, torso={"sy": 0.93, "sx": 1.05},
       earL={"rot": 10}, earR={"rot": -10}, armL={"rot": -10}, armR={"rot": 10})
    at(1880, root={"dy": -32}, torso={"sy": 1.07, "sx": 0.96},
       footL={"dy": -9}, footR={"dy": -9},
       earL={"rot": -16}, earR={"rot": 16}, armL={"rot": 16}, armR={"rot": -16})
    at(1990, root={"dy": -8}, torso={"sy": 1.0, "sx": 1.0},
       footL={"dy": -3}, footR={"dy": -3}, earL={"rot": -6}, earR={"rot": 6})
    at(2060, root={"dy": 4}, torso={"sy": 0.90, "sx": 1.07},
       footL={"dy": 0}, footR={"dy": 0},
       earL={"rot": 14}, earR={"rot": -14}, armL={"rot": -6}, armR={"rot": 6})
    at(2200, root={"dy": 0}, torso={"sy": 1.0, "sx": 1.0},
       earL={"rot": 0}, earR={"rot": 0}, armL={"rot": 0}, armR={"rot": 0})

    # -- dive back down ------------------------------------------------------
    at(2380, root={"dy": 96}, torso={"sy": 1.04, "sx": 0.98},
       earL={"rot": -16}, earR={"rot": 16}, armL={"rot": 12}, armR={"rot": -12})
    at(2700, root={"dy": below}, torso={"sy": 1.0, "sx": 1.0},
       earL={"rot": -6}, earR={"rot": 6}, armL={"rot": 0}, armR={"rot": 0})

    ordered = [{"t": t, "pose": keys[t]} for t in sorted(keys)]
    return {"loop": False, "duration": 2700, "keys": ordered}


def validate(skeleton: iska.Skeleton, name: str, anim: dict) -> None:
    """Checks the bone names, the key ordering and whether the loop joins up.

    The loop is checked after applying the bone-carrying rule
    (`iska_common.carry_keys`): this is exactly the pose the runtime will play.
    """
    last_t = None
    for key in anim["keys"]:
        if last_t is not None and key["t"] <= last_t:
            raise SystemExit(f"{name}: t={key['t']} after t={last_t}")
        last_t = key["t"]
    try:
        poses = iska.carry_keys(skeleton, anim["keys"])
    except KeyError as exc:
        raise SystemExit(f"{name}: {exc.args[0]}") from None
    if anim["loop"] and poses[0][1] != poses[-1][1]:
        raise SystemExit(f"{name}: loop does not join up (the pose at t=0 and the "
                         f"one at t={last_t} differ)")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--rig", default="tools/rigs/rabbit3.json")
    ap.add_argument("--out", default="tools/animations/rabbit3.json")
    args = ap.parse_args()

    with open(args.rig, encoding="utf-8") as fh:
        rig = json.load(fh)
    skeleton = iska.Skeleton(rig)

    animations = {"idle_loop": idle_loop(), "peek": peek()}
    for name, anim in animations.items():
        validate(skeleton, name, anim)

    doc = {
        "character": rig.get("id", "rabbit3"),
        "rig": os.path.relpath(os.path.abspath(args.rig),
                               os.path.dirname(os.path.abspath(args.out))).replace("\\", "/"),
        "notes": ["dx/dy in screen pixels (dy downwards), rot in clockwise degrees,",
                  "sx/sy = scale of the part (not inherited by children)."],
        "animations": animations,
    }

    out_path = os.path.abspath(args.out)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2, ensure_ascii=False)
        fh.write("\n")

    print(f"[anims] {len(animations)} animations -> {out_path} ; rig {args.rig}")
    for name, anim in animations.items():
        spans = {"dx": 0.0, "dy": 0.0, "rot": 0.0, "scale": 1.0}
        for key in anim["keys"]:
            for delta in key["pose"].values():
                spans["dx"] = max(spans["dx"], abs(delta.get("dx", 0.0)))
                spans["dy"] = max(spans["dy"], abs(delta.get("dy", 0.0)))
                spans["rot"] = max(spans["rot"], abs(delta.get("rot", 0.0)))
                for axis in ("sx", "sy"):
                    spans["scale"] = max(spans["scale"],
                                         abs(delta.get(axis, 1.0) - 1.0) + 1.0)
        print(f"[anims]   {name:10s} duration={anim['duration']:5d} ms "
              f"loop={str(anim['loop']):5s} keys={len(anim['keys']):3d} "
              f"|dx|<={spans['dx']:.0f} |dy|<={spans['dy']:.0f} "
              f"|rot|<={spans['rot']:.1f} scale<={spans['scale']:.2f}")


if __name__ == "__main__":
    main()
