"""Packs a rig + animations into `.iska`, the file read by the runtime.

    python tools/iska_pack.py --rig tools/rigs/rabbit3.json \
        --anims tools/animations/rabbit3.json --out assets/rabbit3.iska

This is the step that turns the PNGs and the hand-written poses into a
self-contained binary, with no Blender or Pillow dependency on the runtime side:

  * every PNG is scaled to its sprite box (`rig.parts[].sprite`), converted to
    RGB565, and the translucent pixels become **magenta** (the transparency key
    of the format);
  * the boxes are concatenated into a single pixel block (offsets in bytes);
  * the named poses of the animation JSON (`{"armL": {"rot": -30}}`) are expanded
    into full poses (one 5-tuple per bone, in rig order) and validated: unknown
    bone name, non-ascending keys, inconsistent duration...

`--check` validates everything without writing anything (handy in pre-commit/CI).
"""
from __future__ import annotations

import argparse
import array
import json
import os

from PIL import Image

import iska_common as iska


def load_json(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def check_anim(skeleton: iska.Skeleton, name: str, anim: dict) -> list:
    """Validates an animation and returns its keys as full poses.

    **A key only describes what moves**: a bone missing from a key keeps the
    value of the previous key (like a sparse animation channel), and naming a
    bone without giving a component resets that component to rest. To send a bone
    back to rest, write it explicitly (`"armL": {}`).
    """
    if "keys" not in anim or len(anim["keys"]) < 2:
        raise SystemExit(f"{name}: at least two keys are required")
    last_t = None
    for key in anim["keys"]:
        t = int(round(key["t"]))
        if last_t is not None and t <= last_t:
            raise SystemExit(f"{name}: key times must increase "
                             f"({last_t} then {t})")
        last_t = t
    try:
        keys = iska.carry_keys(skeleton, anim["keys"])
    except KeyError as exc:
        raise SystemExit(f"{name}: {exc.args[0]}") from None
    duration = int(round(anim.get("duration", last_t)))
    if duration < last_t:
        raise SystemExit(f"{name}: duration {duration} ms is below the last key {last_t}")
    if anim.get("loop") and keys[0][0] != 0:
        raise SystemExit(f"{name}: a looping animation must start at t=0")
    return keys, duration


def build_sprites(rig: dict, base_dir: str, alpha_threshold: int):
    """Pixel block (array('H')) + part records, in draw order."""
    parts = sorted(rig["parts"], key=lambda p: p["draw_order"])
    bone_index = {b["name"]: i for i, b in enumerate(rig["bones"])}
    pixels = array.array("H")
    records = []
    report = []
    for part in parts:
        path = os.path.join(base_dir, part["image"])
        if not os.path.exists(path):
            raise SystemExit(f"PNG not found: {path}")
        with Image.open(path) as img:
            sw, sh = part["sprite"]
            sprite = iska.image_to_sprite(img, (sw, sh), alpha_threshold)
        offset = len(pixels) * 2
        pixels.extend(sprite)
        records.append({
            "bone": bone_index.get(part["bone"], -1),
            "pivot": (part["pivot"][0], part["pivot"][1]),
            "sprite": (sw, sh),
            "draw_order": part["draw_order"],
            "flags": 0,
            "pixel_offset": offset,
            "pixel_bytes": sw * sh * 2,
        })
        report.append((part["name"], sw, sh, sw * sh * 2))
    return pixels, records, report


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--rig", required=True, help="rig JSON (tools/rig_build.py)")
    ap.add_argument("--anims", required=True, help="animations JSON")
    ap.add_argument("--out", required=True, help=".iska file to write")
    ap.add_argument("--alpha-threshold", type=int, default=128,
                    help="alpha below which a pixel becomes transparent (magenta)")
    ap.add_argument("--check", action="store_true",
                    help="validate without writing the .iska")
    args = ap.parse_args()

    rig = load_json(args.rig)
    anims_doc = load_json(args.anims)
    skeleton = iska.Skeleton(rig)

    if not skeleton.bones:
        raise SystemExit("rig without any bone")
    for i, bone in enumerate(skeleton.bones):
        parent = bone["parent"]
        if parent is not None and skeleton.index[parent] >= i:
            raise SystemExit(f"rig: bone {bone['name']} must come after its parent "
                             "(ISKA format invariant)")

    animations = []
    for name, anim in anims_doc["animations"].items():
        keys, duration = check_anim(skeleton, name, anim)
        animations.append({"name": name, "loop": bool(anim.get("loop")),
                           "duration_ms": duration, "keys": keys})

    base_dir = os.path.dirname(os.path.abspath(args.rig))
    pixels, records, report = build_sprites(rig, base_dir, args.alpha_threshold)

    bones = [{"parent": None if b["parent"] is None else skeleton.index[b["parent"]],
              "rest": (b["rest"][0], b["rest"][1]), "angle": b["angle"]}
             for b in skeleton.bones]

    blob = iska.build_iska(rig["stage"]["w"], rig["stage"]["h"], bones, records,
                           animations, pixels)

    print(f"[iska_pack] {len(bones)} bones, {len(records)} parts, "
          f"{len(animations)} animations")
    for name, sw, sh, byte_count in report:
        print(f"[iska_pack]   part {name:6s} {sw:3d}x{sh:<3d} {byte_count:6d} B")
    for anim in animations:
        print(f"[iska_pack]   anim {anim['name']:10s} duration={anim['duration_ms']:5d} ms "
              f"loop={str(anim['loop']):5s} keys={len(anim['keys'])}")
    print(f"[iska_pack] pixel block: {len(pixels) * 2} B, file: {len(blob)} B")

    if args.check:
        print("[iska_pack] --check: nothing written (validation OK)")
        return

    out_path = os.path.abspath(args.out)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "wb") as fh:
        fh.write(blob)
    print(f"[iska_pack] -> {out_path}")

    # read-back check: the file must read back identically
    check = iska.parse_iska(blob)
    assert check["stage"] == [rig["stage"]["w"], rig["stage"]["h"]]
    assert len(check["parts"]) == len(records)
    assert set(check["anims"]) == {a["name"] for a in animations}
    for anim in animations:
        assert len(check["anims"][anim["name"]]["keys"]) == len(anim["keys"])
    print("[iska_pack] binary read-back: OK")


if __name__ == "__main__":
    main()
