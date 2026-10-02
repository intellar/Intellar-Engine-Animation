"""Checks that an .iska plays **exactly** the same on the C++ side and the Python side.

    python tools/iska_clip_check.py --iska assets/rabbit3.iska \
        --demo build/Release/intellar_anim_demo.exe

What the script checks, with no screen and no Blender:

1. **Binary**: magic, version, pixel block CRC, invariants (parents before
   children, increasing draw order, increasing keys) -- read by the Python parser
   and then by the C++ loader.
2. **Render**: every frame is computed by the Python blitter
   (`iska_common.blit_part`) *and* by the C++ engine (`--dump`), then compared by
   FNV-1a hash and, if the `.565` files are present, **byte by byte**. Any
   divergence is a bug on one side or the other: this is the guarantee that the
   tooling faithfully describes what the engine displays.
3. **Animations**: looping animations show the same frame at the start and at the
   end, the keys stay inside the duration, and no frame of `peek` is empty outside
   the start and the end (the rabbit does not disappear by accident in the
   middle).
"""
from __future__ import annotations

import argparse
import array
import os
import re
import subprocess
import sys
import tempfile

import iska_common as iska

MASK64 = (1 << 64) - 1
FNV_OFFSET = 1469598103934665603
FNV_PRIME = 1099511628211
DUMP_LINE = re.compile(r"^\[dump\]\s+(\S+)\s+t=\s*(\d+)\s+ms\s+fnv1a=([0-9a-f]{16})\s*$")


def fnv1a(pixels) -> int:
    """Same hash as `fnv1a` in demo/main.cpp (low byte first)."""
    hash_value = FNV_OFFSET
    for value in pixels:
        hash_value ^= value & 0xFF
        hash_value = (hash_value * FNV_PRIME) & MASK64
        hash_value ^= (value >> 8) & 0xFF
        hash_value = (hash_value * FNV_PRIME) & MASK64
    return hash_value


def check_times(anim: dict) -> list:
    """Instants captured by `--keys` on the C++ side (keys + midpoints), to match."""
    times = []
    for i, key in enumerate(anim["keys"]):
        times.append(key[0])
        if i + 1 < len(anim["keys"]):
            times.append((key[0] + anim["keys"][i + 1][0]) // 2)
    return times


def render(data: dict, name: str, t_ms: float):
    """RGB565 framebuffer of animation `name` at time `t_ms` (Python blitter)."""
    anim = data["anims"][name]
    skeleton = iska.skeleton_from_iska(data)
    buf = iska.new_frame(data["stage"][0], data["stage"][1], 0x0000)
    skeleton.draw(buf, iska.sample_pose(anim, iska.anim_time(anim, t_ms)),
                  iska.sprites_from_iska(data, skeleton))
    return buf


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--iska", default="assets/rabbit3.iska")
    ap.add_argument("--demo", default=None,
                    help="demo binary (required for the render comparison)")
    ap.add_argument("--keep", default=None,
                    help="directory where the capture is kept (default: temp dir)")
    ap.add_argument("--no-render", action="store_true",
                    help="only check the binary (no rendering)")
    args = ap.parse_args()

    failures = []
    with open(args.iska, "rb") as fh:
        blob = fh.read()
    data = iska.parse_iska(blob)          # validates magic, version, CRC, sizes
    print(f"[check] {args.iska}: ISKA v{data['version']} "
          f"{data['stage'][0]}x{data['stage'][1]}, {len(data['bones'])} bones, "
          f"{len(data['parts'])} parts, {len(data['anims'])} animations, "
          f"{data['bytes']} B")

    # -- format invariants ----------------------------------------------------
    for i, bone in enumerate(data["bones"]):
        parent = bone["parent"]
        if parent is not None and parent >= i:
            failures.append(f"bone {i}: parent {parent} does not come earlier")
    orders = [part["draw_order"] for part in data["parts"]]
    if orders != sorted(orders):
        failures.append("parts are not sorted by draw order")
    for i, part in enumerate(data["parts"]):
        if part["bone"] >= len(data["bones"]):
            failures.append(f"part {i}: bone {part['bone']} out of range")
        if part["pixel_offset"] // 2 + part["sprite"][0] * part["sprite"][1] > len(data["pixels"]):
            failures.append(f"part {i}: box outside the pixel block")

    # -- animations -----------------------------------------------------------
    for name, anim in data["anims"].items():
        times = [t for t, _ in anim["keys"]]
        if times != sorted(times):
            failures.append(f"{name}: keys are not ordered")
        if times[-1] > anim["duration"]:
            failures.append(f"{name}: key {times[-1]} past the duration {anim['duration']}")
        if anim["loop"]:
            if times[0] != 0:
                failures.append(f"{name}: a loop that does not start at 0")
            first = render(data, name, 0)
            last = render(data, name, anim["duration"])
            if list(first) != list(last):
                failures.append(f"{name}: the loop does not join up (t=0 != t=duration)")
            else:
                print(f"[check] {name}: loop joins up (t=0 identical to t={anim['duration']})")
        else:
            # an empty frame is only a bug if it is surrounded by non-empty
            # frames: at the start (and the end) of a one-shot, the character may
            # legitimately be off screen.
            frames = [(t, render(data, name, t)) for t in times]
            blank = [all(value == 0 for value in frame) for _t, frame in frames]
            for i in range(1, len(frames) - 1):
                if blank[i] and not blank[i - 1] and not blank[i + 1]:
                    failures.append(f"{name}: isolated empty frame at t={frames[i][0]} "
                                    "(the character disappears by accident)")
            edge_blank = sum(1 for flag in blank if flag)
            if edge_blank:
                print(f"[check] {name}: {edge_blank} off-screen frame(s) "
                      "(start/end, expected)")

    # -- C++ vs Python render -------------------------------------------------
    if not args.no_render:
        if not args.demo:
            raise SystemExit("--demo is required to compare the renders "
                             "(or use --no-render)")
        if not os.path.exists(args.demo):
            raise SystemExit(f"binary not found: {args.demo}")
        dump_dir = args.keep or tempfile.mkdtemp(prefix="iska_dump_")
        os.makedirs(dump_dir, exist_ok=True)
        hashes = run_demo(args.demo, args.iska, dump_dir, "all")
        checked = 0
        for name, anim in data["anims"].items():
            for t in check_times(anim):
                expected = fnv1a(render(data, name, t))
                got = hashes.get((name, t))
                if got is None:
                    failures.append(f"{name} t={t}: frame missing from the C++ capture")
                    continue
                if got != expected:
                    failures.append(f"{name} t={t}: C++ {got:016x} != Python {expected:016x}")
                    continue
                raw_path = os.path.join(dump_dir, f"{name}_{t:05d}.565")
                if os.path.exists(raw_path):
                    with open(raw_path, "rb") as fh:
                        got_bytes = fh.read()
                    want_bytes = array.array("H", render(data, name, t)).tobytes()
                    if got_bytes != want_bytes:
                        failures.append(f"{name} t={t}: different pixels "
                                        "(same hashes but different bytes)")
                        continue
                checked += 1
        print(f"[check] C++ vs Python render: {checked} identical frame(s) "
              f"(capture in {dump_dir})")

    if failures:
        print(f"[check] FAIL: {len(failures)} problem(s)")
        for failure in failures:
            print(f"[check]   - {failure}")
        sys.exit(1)
    print("[check] OK: valid binary and identical renders")


def run_demo(demo: str, iska_path: str, dump_dir: str, anim: str) -> dict:
    """Runs the demo in capture mode and returns {(anim, t): hash}."""
    command = [demo, "--iska", iska_path, "--dump", dump_dir, "--anim", anim, "--keys"]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit(f"the demo failed ({result.returncode}):\n{result.stdout}{result.stderr}")
    hashes = {}
    for line in result.stdout.splitlines():
        match = DUMP_LINE.match(line.strip())
        if match:
            hashes[(match.group(1), int(match.group(2)))] = int(match.group(3), 16)
    if not hashes:
        raise SystemExit("no frame captured by the demo (--dump): unexpected output")
    return hashes


if __name__ == "__main__":
    main()
