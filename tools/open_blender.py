"""Opens the right .blend in the GUI Blender, set up for joint/animation work.

    python tools/open_blender.py rig       # tools/source/rabbit3_rig.blend  (place the bones)
    python tools/open_blender.py anim      # tools/source/rabbit3_anim.blend (edit the animations)
    python tools/open_blender.py planes    # tools/source/rabbit3.blend      (place the images)
    python tools/open_blender.py --id mybot rig    # tools/source/mybot_rig.blend
    python tools/open_blender.py --print-blender    # which Blender would be used?

The scripts of `tools/` split in two families. The plain ones (`build_asset.py`,
`iska_view.py`, `anim_roundtrip.py`, ...) are normal programs: `python tools/<name>.py`,
each with a `--help`. The **Blender-side** ones start with `blender_` (`blender_make_rig.py`,
`blender_bind.py`, `blender_export.py`, `blender_import_anims.py`, `blender_bake_anims.py`)
and `blender_scene_setup.py`: they `import bpy` and only exist **inside** Blender --
`python tools/blender_make_rig.py` fails with `ModuleNotFoundError: No module named
'bpy'`. `--script` runs one of them, with this file supplying the executable, the
`.blend` and the flag order:

    python tools/open_blender.py planes --script blender_make_rig.py -- \
        --bones tools/rigs/rabbit3_bones.json --out tools/source/rabbit3_rig.blend

(the positional `rig|anim|planes` chooses the `.blend` to open, everything after `--`
goes to the script -- that is Blender's own convention, kept here).

Blender is not on the PATH, and several versions can be installed side by side:
the script looks for it in this order -- `--blender PATH`, `$BLENDER_EXE`, the
PATH, then the usual install folders (newest version first).

Once Blender is up, `tools/blender_scene_setup.py` runs inside it: bones drawn in
front of the textured planes, view framed on the character, Pose mode, and a
report of the plane <-> bone names (the engine binds them **by exact name**).
`--no-setup` opens the .blend untouched, `--background` runs it headless (no
window: useful to check the setup script itself), `--wait` waits for Blender.
"""
from __future__ import annotations

import argparse
import glob
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SETUP = os.path.join(HERE, "blender_scene_setup.py")

SCENES = {
    "rig": os.path.join("tools", "source", "rabbit3_rig.blend"),
    "anim": os.path.join("tools", "source", "rabbit3_anim.blend"),
    "planes": os.path.join("tools", "source", "rabbit3.blend"),
}


def scene_blend(identifier: str, scene: str) -> str:
    """The .blend to open: the rabbit3 scenes, or `tools/source/<id>_*.blend`."""
    if identifier:
        stem = {"rig": f"{identifier}_rig.blend",
                "anim": f"{identifier}_anim.blend",
                "planes": f"{identifier}.blend"}[scene]
        return os.path.join(ROOT, "tools", "source", stem)
    return os.path.join(ROOT, SCENES[scene])
CANDIDATES = [
    r"C:\Program Files\Blender Foundation\Blender *\blender.exe",
    r"C:\Program Files (x86)\Blender Foundation\Blender *\blender.exe",
    "/Applications/Blender.app/Contents/MacOS/Blender",
    "/usr/local/bin/blender",
    "/usr/bin/blender",
]


def version_of(path: str):
    """`(major, minor)` read in an install path; `(0, 0)` when there is none."""
    match = re.search(r"(\d+)\.(\d+)", path)
    return (int(match.group(1)), int(match.group(2))) if match else (0, 0)


def find_blender(explicit: str = "") -> str:
    """Path of the Blender executable to use (raises `SystemExit` if none)."""
    if explicit:
        if os.path.isfile(explicit):
            return os.path.abspath(explicit)
        raise SystemExit(f"no Blender at {explicit}")
    for name in ("BLENDER_EXE", "BLENDER_PATH"):
        value = os.environ.get(name)
        if value and os.path.isfile(value):
            return os.path.abspath(value)
    on_path = shutil.which("blender")
    if on_path:
        return on_path
    installs = []
    for pattern in CANDIDATES:
        installs += glob.glob(pattern)
    if installs:
        installs.sort(key=version_of, reverse=True)
        return os.path.abspath(installs[0])
    raise SystemExit("Blender not found: use --blender PATH or set BLENDER_EXE "
                     "(https://www.blender.org/download/)")


def find_script(name: str) -> str:
    """Path of a Blender-side tool: `blender_make_rig.py`, `tools/…`, or a full path."""
    for candidate in (name, os.path.join(HERE, name), os.path.join(ROOT, name)):
        if candidate and os.path.isfile(candidate):
            return os.path.abspath(candidate)
    raise SystemExit(f"[open_blender] no such Blender-side script: {name}\n"
                     f"[open_blender] (they live in {HERE}; plain Python tools do not "
                     f"need Blender)")


def split_passthrough(argv: list) -> tuple:
    """`(our arguments, the ones after --)`, Blender's own convention."""
    if "--" in argv:
        index = argv.index("--")
        return argv[:index], argv[index + 1:]
    return argv, []


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("scene", nargs="?", default="rig", choices=sorted(SCENES),
                    help="rig | anim | planes (default: rig)")
    ap.add_argument("--blender", default="", help="explicit path to blender(.exe)")
    ap.add_argument("--id", default="",
                    help="character id: resolves tools/source/<id>.blend / <id>_rig.blend / "
                         "<id>_anim.blend (default: the rabbit3 scenes)")
    ap.add_argument("--file", default="", help="a .blend of your own")
    ap.add_argument("--script", default="",
                    help="run a Blender-side tool (blender_*.py, which needs bpy) in "
                         "this .blend instead of opening it; its arguments follow `--`")
    ap.add_argument("--no-setup", action="store_true",
                    help="open the .blend without running the scene setup")
    ap.add_argument("--background", action="store_true",
                    help="headless, no window (the setup runs then Blender exits)")
    ap.add_argument("--wait", action="store_true", help="wait for Blender to quit")
    ap.add_argument("--print-blender", action="store_true",
                    help="print the Blender used, then exit")
    ap.add_argument("--list", action="store_true", help="list the known .blend files")
    return ap


def main() -> None:
    own, passthrough = split_passthrough(sys.argv[1:])
    args = build_parser().parse_args(own)
    if passthrough and not args.script:
        raise SystemExit("[open_blender] the arguments after `--` go to a Blender-side "
                         "script: add --script NAME.py (or drop them)")
    blender = find_blender(args.blender)

    if args.print_blender:
        print(blender)
        return
    if args.list:
        for key in sorted(SCENES):
            path = os.path.join(ROOT, SCENES[key])
            print(f"[open_blender] {key:7s} {SCENES[key]:34s} "
                  f"{'found' if os.path.isfile(path) else 'MISSING'}")
        return

    blend = os.path.abspath(args.file) if args.file else scene_blend(args.id, args.scene)
    if not os.path.isfile(blend):
        hint = ("generated by `python tools/build_asset.py --to-blender`"
                if args.scene == "anim" else "see tools/source/ and NOTICE.md")
        raise SystemExit(f"[open_blender] no such .blend: {blend}\n"
                         f"[open_blender] ({hint})")

    command = [blender]
    if args.background:
        command.append("-b")
    command.append(blend)
    script = ""
    if args.script:
        script = find_script(args.script)
        command += ["--python", script]
        if passthrough:
            command += ["--", *passthrough]
    elif not args.no_setup and os.path.isfile(SETUP):
        command += ["--python", SETUP, "--", "--mode", args.scene]

    shown = " ".join(f'"{part}"' if " " in part else part for part in command)
    print(f"[open_blender] Blender  : {blender}")
    if script:
        print(f"[open_blender] script   : {script}")
        print(f"[open_blender] no scene setup: the script is the point "
              f"(--no-setup is implied)")
    print(f"[open_blender] command  : {shown}")
    version = subprocess.run([blender, "--version"], capture_output=True, text=True,
                             check=False).stdout.splitlines()
    print(f"[open_blender] version  : {version[0] if version else '?'}")

    if args.background or args.wait:
        print("[open_blender] running Blender in the foreground...")
        raise SystemExit(subprocess.call(command, cwd=ROOT))
    # cwd=ROOT: Blender is started where the rest of the chain runs (`tools/` is
    # then what the Blender-side scripts read when they are handed a path).
    subprocess.Popen(command, cwd=ROOT)
    print("[open_blender] Blender is starting -- this console stays free")


if __name__ == "__main__":
    main()
