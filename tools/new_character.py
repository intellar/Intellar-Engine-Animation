"""Scaffolds a new character: rig seeds + a first animation template.

    python tools/new_character.py mybot --parts torso,head,armL,armR,footL,footR

Run AFTER placing the planes in `tools/source/<id>.blend` (one plane per part,
`Add > Image > Images as Planes`, object name = bone/part name). Writes:

    tools/rigs/<id>_bones.json   seeds for tools/blender_make_rig.py
    tools/anims_<id>.py          animation template to edit

then prints the commands that follow. Pass --force to overwrite.
"""
from __future__ import annotations

import argparse
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

# The animation template. `<id>` is replaced by the character name.
TEMPLATE = '''"""Writes the <id> animations (tools/animations/<id>.json).

    python tools/anims_<id>.py --rig tools/rigs/<id>.json \\
        --out tools/animations/<id>.json

Pose conventions (dict of bone name -> deltas):

    dx, dy : translation in screen pixels (positive dy = downwards)
    rot    : rotation in degrees, clockwise
    sx, sy : scale of the part (1.0 = normal), not inherited by children

A bone missing from a pose keeps its rest position; keys are sorted by time and a
looping animation must end on the pose it starts from. Edit `idle_loop` below.
"""
from __future__ import annotations

import argparse
import json
import os

import iska_common as iska


def idle_loop() -> dict:
    """A 2000 ms looping animation. Add a key with deltas to move."""
    keys = {
        0: {},        # "everything at rest"
        2000: {},
    }
    # Example: make `head` nod mid-loop (and rest-key it at 0/2000 so it loops):
    #     keys[1000] = {"head": {"rot": 8.0}}
    #     keys[0] = keys[2000] = {"head": {}}

    ordered = [{"t": t, "pose": keys[t]} for t in sorted(keys)]
    return {"loop": True, "duration": 2000, "keys": ordered}


def validate(skeleton: iska.Skeleton, name: str, anim: dict) -> None:
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
        raise SystemExit(f"{name}: loop does not join up")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--rig", default="tools/rigs/<id>.json")
    ap.add_argument("--out", default="tools/animations/<id>.json")
    args = ap.parse_args()

    with open(args.rig, encoding="utf-8") as fh:
        rig = json.load(fh)
    skeleton = iska.Skeleton(rig)

    animations = {"idle_loop": idle_loop()}
    for name, anim in animations.items():
        validate(skeleton, name, anim)

    doc = {
        "character": "<id>",
        "rig": "tools/rigs/<id>.json",
        "notes": ["dx/dy in screen pixels (dy downwards), rot in clockwise degrees,",
                  "sx/sy = scale of the part (not inherited by children)."],
        "animations": animations,
    }

    out_path = os.path.abspath(args.out)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2, ensure_ascii=False)
        fh.write("\\n")

    print(f"[anims] {len(animations)} animations -> {out_path} ; rig {args.rig}")
    for name, anim in animations.items():
        print(f"[anims]   {name:10s} duration={anim['duration']:5d} ms "
              f"loop={str(anim['loop']):5s} keys={len(anim['keys']):3d}")


if __name__ == "__main__":
    main()
'''

def seeds_doc(identifier: str, parts: list) -> dict:
    """A sensible starting armature: `root` on the first part, the rest flat."""
    bones = [{"name": "root", "parent": None, "part": parts[0],
              "anchor": [0.5, 0.0], "dir": [0, 1]}]
    for index, part in enumerate(parts):
        anchor = [0.5, 0.0] if index == 0 else [0.5, 0.5]
        bones.append({"name": part, "parent": "root", "part": part,
                      "anchor": anchor, "dir": [0, 1]})
    return {
        "_comment": [
            f"Seeds of the {identifier} skeleton: used by tools/blender_make_rig.py to",
            "create the armature in the .blend, then read back by tools/blender_export.py.",
            "Once the armature is placed in Blender, the .blend is the reference: this",
            "file is only used to regenerate a starting armature.",
            "anchor = fraction of the plane's local box: x 0=left 1=right, y 0=bottom 1=top",
            "(a value outside [0,1] is allowed: -0.05 = 5% below the box).",
            "dir = bone direction in Blender (y upwards) -- used for bone angles.",
        ],
        "armature": "skeleton",
        "bone_length": 0.35,
        "bones": bones,
    }


def write(path: str, text: str, force: bool) -> None:
    if os.path.isfile(path) and not force:
        raise SystemExit(f"[new_character] {path} already exists (--force to overwrite)")
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    print(f"[new_character] wrote {os.path.relpath(path, ROOT)}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("id")
    ap.add_argument("--parts", required=True,
                    help="comma-separated plane/bone names (first = the body)")
    ap.add_argument("--out-dir", default="tools",
                    help="where to write (rigs/<id>_bones.json + anims_<id>.py)")
    ap.add_argument("--force", action="store_true", help="overwrite existing files")
    args = ap.parse_args()

    parts = [p.strip() for p in args.parts.split(",") if p.strip()]
    if not parts:
        raise SystemExit("--parts needs at least one name, e.g. --parts torso,head")

    seeds_path = os.path.join(ROOT, args.out_dir, "rigs", f"{args.id}_bones.json")
    anims_path = os.path.join(ROOT, args.out_dir, f"anims_{args.id}.py")

    write(seeds_path, json.dumps(seeds_doc(args.id, parts), indent=2,
                                 ensure_ascii=False) + "\n", args.force)
    write(anims_path, TEMPLATE.replace("<id>", args.id), args.force)

    print("[new_character] next:")
    print(f"  python tools/open_blender.py --id {args.id} planes "
          f"--script blender_make_rig.py -- --bones tools/rigs/{args.id}_bones.json "
          f"--out tools/source/{args.id}_rig.blend")
    print(f"  python tools/open_blender.py --file tools/source/{args.id}_rig.blend")
    print(f"  python tools/build_asset.py --id {args.id} --rig-from-blender")
    print(f"  # edit tools/anims_{args.id}.py, then:")
    print(f"  python tools/build_asset.py --id {args.id} --anims-from-python")
    print(f"  python tools/iska_view.py assets/{args.id}.iska")


if __name__ == "__main__":
    main()

