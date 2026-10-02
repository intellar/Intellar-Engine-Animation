"""Checks the whole round trip: JSON -> Blender -> JSON -> .iska -> pixels.

    python tools/anim_roundtrip.py                 # rabbit3, everything automatic
    python tools/anim_roundtrip.py --keep          # keeps build/roundtrip/ for eyes

The animation JSON is the reference. This script plays it *through Blender*:

    1. `blender_bind.py`      planes bound to their bones, rest pose, scale rules
    2. `blender_import_anims.py`  the JSON poses -> Blender actions (one key per JSON
                                  key, LINEAR)
    3. `blender_bake_anims.py`    the actions -> a new JSON (sparse, snapped)

and then compares the two, twice:

    * **values**: every key of every animation, component by component, through the
      runtime's own interpolation (`iska_common.sample_pose`): the curves must come
      back within `--tolerance` (one wire step by default);
    * **pixels**: both JSONs are packed into a `.iska` and every 10 ms frame is
      rendered with the shared blitter (`iska_common.blit_part`, the Python twin of
      the C++ renderer). The count of *raw* differences is large and means nothing on
      its own: pixel art drawn with a nearest-neighbour blit flips thousands of texel
      edges when the pose changes by half a pixel, which is unavoidable since every
      stored value is a whole pixel / a tenth of a degree. What counts is the number
      of pixels that stay wrong **even allowing a 1-pixel shift** (measured on rabbit3:
      ~140 for `idle_loop`, ~220 for `peek`, out of the ~13 000 painted pixels, all of
      them neighbouring shades at texel seams); a real mistake (a part in the wrong
      place, a missing part, a wrong scale) is worth thousands.

It is the safety net of the editing workflow: if it is green, then whatever you see
in Blender is what the panel will show, and editing an action by hand is safe.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys

import iska_common as iska
import open_blender

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
WORK = os.path.join("build", "roundtrip")


def load_json(path: str):
    """The file is opened from the repository root, like every other tool."""
    with open(os.path.join(ROOT, path), encoding="utf-8") as fh:
        return json.load(fh)


def run(command: list, quiet: bool = False) -> str:
    """Runs one step; returns its output (echoed unless `quiet`)."""
    if not quiet:
        print(f"[roundtrip] $ {' '.join(command)}")
    result = subprocess.run(command, cwd=ROOT, text=True, capture_output=quiet)
    if result.returncode != 0:
        raise SystemExit(f"[roundtrip] step failed: {command[0]}\n"
                         f"{(result.stdout or '')[-2000:]}")
    return result.stdout or ""


def blender(blender_exe: str, blend: str, script: str, *arguments: str) -> str:
    return run([blender_exe, "-b", blend, "--python", os.path.join(HERE, script),
                "--", *arguments], quiet=True)


def pack(rig: str, anims: str, out: str) -> None:
    run([sys.executable, os.path.join(HERE, "iska_pack.py"), "--rig", rig,
         "--anims", anims, "--out", out], quiet=True)


# --------------------------------------------------------------------------- #
# Comparison
# --------------------------------------------------------------------------- #

def compare_values(skeleton, first: dict, second: dict) -> tuple:
    """Max |error| per component, with where it happens and how often.

    Returns `(worst, where, counts)`: `worst[component]` is the biggest difference
    seen on that component over every frame of every animation, `where[component]`
    the `(animation, t, bone)` that produced it, and `counts[component]` how many
    samples exceeded the tolerance.
    """
    worst = [0.0] * 5
    where = [None] * 5
    counts = [0] * 5
    tolerance = (1.0, 1.0, 0.1, 0.0001, 0.0001)
    for name, anim in first["animations"].items():
        other = second["animations"].get(name)
        if other is None:
            raise SystemExit(f"[roundtrip] animation {name} is missing from the bake")
        clip_a = {"name": name, "keys": iska.carry_keys(skeleton, anim["keys"]),
                  "loop": anim.get("loop", False), "duration": anim["duration"]}
        clip_b = {"name": name, "keys": iska.carry_keys(skeleton, other["keys"]),
                  "loop": other.get("loop", False), "duration": other["duration"]}
        for t_ms in range(0, int(clip_a["duration"]) + 1, 10):
            pose_a = iska.sample_pose(clip_a, iska.anim_time(clip_a, t_ms))
            pose_b = iska.sample_pose(clip_b, iska.anim_time(clip_b, t_ms))
            for index in range(len(pose_a)):
                for component in range(5):
                    error = abs(pose_a[index][component] - pose_b[index][component])
                    if error > tolerance[component]:
                        counts[component] += 1
                    if error > worst[component]:
                        worst[component] = error
                        where[component] = (name, t_ms, skeleton.bones[index]["name"])
    return worst, where, counts


def strict_difference(buf_a, buf_b, width: int, height: int) -> int:
    """Pixels of A that B cannot explain **even allowing a 1-pixel shift**.

    Pixel art + nearest-neighbour blit + poses differing by half a pixel: edges move,
    and the raw count of differing pixels is huge for a perfectly good bake. A real
    mistake (a part in the wrong place, a wrong sprite, a wrong scale) does not
    disappear when the comparison is allowed to look at the neighbouring pixels of
    B, so this is the number the verdict uses.
    """
    if buf_a == buf_b:
        return 0
    positions = {}
    for y in range(height):
        for x in range(width):
            positions.setdefault(buf_b[y * width + x], set()).add((x, y))
    wrong = 0
    for y in range(height):
        row = y * width
        for x in range(width):
            value = buf_a[row + x]
            if value == buf_b[row + x]:
                continue
            reachable = positions.get(value)
            if reachable is None:
                wrong += 1
                continue
            if not any((x + dx, y + dy) in reachable
                       for dx in (-1, 0, 1) for dy in (-1, 0, 1)):
                wrong += 1
    return wrong


def compare_pixels(first: str, second: str, max_pixels: int) -> int:
    """Renders every 10 ms frame of both assets and compares them."""
    with open(first, "rb") as fh:
        asset_a = iska.parse_iska(fh.read())
    with open(second, "rb") as fh:
        asset_b = iska.parse_iska(fh.read())
    if list(asset_a["anims"]) != list(asset_b["anims"]):
        raise SystemExit("[roundtrip] the two assets do not have the same animations")
    if asset_a["stage"] != asset_b["stage"]:
        raise SystemExit("[roundtrip] the two assets do not have the same stage")

    skeleton_a = iska.skeleton_from_iska(asset_a)
    skeleton_b = iska.skeleton_from_iska(asset_b)
    sprites_a = iska.sprites_from_iska(asset_a, skeleton_a)
    sprites_b = iska.sprites_from_iska(asset_b, skeleton_b)
    width, height = asset_a["stage"]
    bg = iska.rgb_to_565(16, 17, 22)
    failures = 0

    for name, anim in asset_a["anims"].items():
        other = asset_b["anims"][name]
        checked = worst = worst_time = 0
        worst_pair = (None, None)
        for t_ms in range(0, int(anim["duration"]) + 1, 10):
            buf_a = iska.new_frame(width, height, bg)
            skeleton_a.draw(buf_a, iska.sample_pose(anim, iska.anim_time(anim, t_ms)),
                            sprites_a)
            buf_b = iska.new_frame(width, height, bg)
            skeleton_b.draw(buf_b, iska.sample_pose(other, iska.anim_time(other, t_ms)),
                            sprites_b)
            differing = sum(1 for a, b in zip(buf_a, buf_b) if a != b)
            checked += 1
            if differing > worst:
                worst, worst_time = differing, t_ms
                worst_pair = (buf_a, buf_b)
        wrong = strict_difference(worst_pair[0], worst_pair[1], width, height)
        status = "OK" if wrong <= max_pixels else "TOO MANY PIXELS STILL WRONG"
        if wrong > max_pixels:
            failures += 1
        print(f"[roundtrip] {name:12s} {checked:4d} frames: worst frame t={worst_time} "
              f"ms differs on {worst} px (pose shifted by less than a pixel); "
              f"{wrong} px are wrong even allowing a 1 px shift -> {status}")
    return failures


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--id", default="rabbit3")
    ap.add_argument("--rig", default="", help="rig JSON (default tools/rigs/<id>.json)")
    ap.add_argument("--anims", default="",
                    help="animations JSON (default tools/animations/<id>.json)")
    ap.add_argument("--blend", default="",
                    help="source .blend (default tools/source/<id>_rig.blend)")
    ap.add_argument("--blender", default="", help="path to blender(.exe)")
    ap.add_argument("--tolerance", type=float, default=1.0,
                    help="wire steps tolerated on the values (default 1)")
    ap.add_argument("--max-pixels", type=int, default=256,
                    help="pixels a frame may still get wrong with a 1 px shift "
                         "allowed (default 256)")
    ap.add_argument("--keep", action="store_true",
                    help="keep build/roundtrip/ (the bound .blend and the bake)")
    ap.add_argument("--skip-pixels", action="store_true",
                    help="only compare the values (faster while iterating)")
    args = ap.parse_args()

    rig = args.rig or os.path.join("tools", "rigs", f"{args.id}.json")
    anims = args.anims or os.path.join("tools", "animations", f"{args.id}.json")
    blend = args.blend or os.path.join("tools", "source", f"{args.id}_rig.blend")
    blender_exe = open_blender.find_blender(args.blender)
    tolerance = tuple(value * args.tolerance
                      for value in (1.0, 1.0, 0.1, 0.0001, 0.0001))

    work = os.path.join(ROOT, WORK)
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work, exist_ok=True)
    bound = os.path.join(WORK, f"{args.id}_anim.blend")
    baked = os.path.join(WORK, f"{args.id}_baked.json")
    asset_before = os.path.join(WORK, f"{args.id}_before.iska")
    asset_after = os.path.join(WORK, f"{args.id}_after.iska")

    print(f"[roundtrip] {args.id}: {anims}")
    print(f"[roundtrip] Blender  : {blender_exe}")
    print("[roundtrip] 1/4 binding the planes to the bones")
    blender(blender_exe, blend, "blender_bind.py", "--out", bound)
    print("[roundtrip] 2/4 importing the animations as actions")
    blender(blender_exe, bound, "blender_import_anims.py", "--anims", anims,
            "--rig", rig, "--out", bound)
    print("[roundtrip] 3/4 baking the actions back into JSON")
    blender(blender_exe, bound, "blender_bake_anims.py", "--rig", rig,
            "--out", baked)
    print("[roundtrip] 4/4 packing both JSONs and rendering every frame")
    pack(rig, anims, asset_before)
    pack(rig, baked, asset_after)

    skeleton = iska.Skeleton(load_json(rig))
    worst, where, counts = compare_values(skeleton, load_json(anims), load_json(baked))
    names = ("dx", "dy", "rot", "sx", "sy")
    failures = 0
    print("[roundtrip] values (max |error| over every frame, after the round trip):")
    for component, name in enumerate(names):
        flag = "" if worst[component] <= tolerance[component] else "  <-- TOO BIG"
        if flag:
            failures += 1
        detail = ""
        if where[component]:
            animation, t_ms, bone = where[component]
            detail = f"  [{counts[component]} sample(s) over, worst at {animation} " \
                     f"t={t_ms} ms, bone {bone}]"
        print(f"[roundtrip]   {name:3s} {worst[component]:.5f} "
              f"(tolerated {tolerance[component]:.5f}){flag}{detail}")

    if args.skip_pixels:
        print("[roundtrip] pixel comparison skipped (--skip-pixels)")
    else:
        failures += compare_pixels(asset_before, asset_after, args.max_pixels)

    if not args.keep:
        shutil.rmtree(work, ignore_errors=True)
    if failures:
        raise SystemExit(f"[roundtrip] {failures} check(s) failed: Blender and the "
                         f"engine do NOT agree")
    print("[roundtrip] OK: the animations survive the trip into Blender and back")


if __name__ == "__main__":
    main()
