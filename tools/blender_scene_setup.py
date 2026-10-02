"""Sets the Blender scene up for joint / animation work (run by `open_blender.py`).

    blender tools/source/rabbit3_rig.blend --python tools/blender_scene_setup.py -- \
        --mode rig

What it does -- **view state only, it never writes into the .blend**:

* bones drawn **in front of** the planes, with their names (octahedral shape):
  you can drop a bone head on the right pixel of a paw;
* planes shown **textured** (solid shading + texture): you see the artwork;
* the 3D view framed on the character, in Pose mode (`rig`, `anim`) or Object mode;
* `--mode anim` also puts the timeline at **100 fps** -- 1 frame = 10 ms, so the
  key times of the JSON (0, 1440, 1520... ms) land on *exact* frames;
* a report of the plane <-> bone names. The engine binds a plane to the bone with
  **the same exact name** (`tools/rig_build.py`): a typo does not fail, it
  silently falls back on the root bone, so the report catches it immediately;
* a report of a **leftover pose**: when the planes are bound to the armature (the
  animation file), a pose left over from a session would be read by the export as
  the new reference placement.
"""
from __future__ import annotations

import argparse
import sys

import bpy                      # noqa: E402  (provided by Blender)


def argv_after_dashdash() -> list:
    return sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []


def image_of(obj):
    """Name of the first image found in the materials (`""` if none)."""
    for slot in obj.material_slots:
        mat = slot.material
        tree = getattr(mat, "node_tree", None) if mat else None
        if tree is None:
            continue
        for node in tree.nodes:
            if node.type == "TEX_IMAGE" and node.image:
                return node.image.name
    return ""


def show(obj) -> None:
    """Makes an object visible in the viewport and in the render."""
    obj.hide_viewport = False
    obj.hide_render = False
    try:
        obj.hide_set(False)
    except Exception:            # no view layer (background mode)
        pass


def armature():
    return next((o for o in bpy.data.objects if o.type == "ARMATURE"), None)


def posed_bones(arm) -> list:
    """Names of the pose bones that are **not** at rest (would be exported)."""
    if arm is None:
        return []
    out = []
    for pose_bone in arm.pose.bones:
        if (pose_bone.location.length > 1e-6
                or abs(pose_bone.rotation_quaternion.angle) > 1e-6
                or (pose_bone.rotation_euler.x, pose_bone.rotation_euler.y,
                    pose_bone.rotation_euler.z) != (0.0, 0.0, 0.0)
                or abs(pose_bone.scale.x - 1.0) > 1e-6
                or abs(pose_bone.scale.y - 1.0) > 1e-6
                or abs(pose_bone.scale.z - 1.0) > 1e-6):
            out.append(pose_bone.name)
    return out


def report(planes: list, arm) -> None:
    """The name binding, which is the one thing that fails silently."""
    bone_names = [b.name for b in arm.data.bones] if arm else []
    print(f"[scene_setup] armature: {arm.name if arm else '(none)'}, "
          f"{len(bone_names)} bones, {len(planes)} planes")
    for obj in planes:
        marks = "" if obj.name in bone_names else \
            "  <-- NO BONE WITH THIS NAME: the engine would fall back on the root bone"
        print(f"[scene_setup]   plane {obj.name:12s} -> bone {obj.name:12s}{marks}")
    for name in bone_names:
        if name not in [obj.name for obj in planes]:
            print(f"[scene_setup]   bone  {name:12s} -> (no plane: it only carries "
                  f"its children, that is normal for the root)")


def setup_view_state(mode: str) -> None:
    """Textured planes, framed 3D view (no effect in background mode)."""
    screen = getattr(bpy.context, "screen", None)
    if screen is None:
        print("[scene_setup] background mode: no 3D view to set up")
        return
    for area in screen.areas:
        if area.type != "VIEW_3D":
            continue
        space = area.spaces.active
        space.shading.type = "SOLID"
        space.shading.color_type = "TEXTURE"     # show the plane artwork
        region = next((r for r in area.regions if r.type == "WINDOW"), None)
        try:
            with bpy.context.temp_override(area=area, region=region):
                bpy.ops.view3d.view_all()
        except Exception as exc:                 # pragma: no cover - UI only
            print(f"[scene_setup] view_all skipped ({exc})")
        print(f"[scene_setup] 3D view: solid + texture, framed on the character")


def enter_mode(arm, mode: str) -> None:
    """Pose mode for joint/animation work, Object mode otherwise."""
    if arm is None:
        return
    try:
        bpy.ops.object.select_all(action="DESELECT")
        arm.select_set(True)
        bpy.context.view_layer.objects.active = arm
        bpy.ops.object.mode_set(mode="POSE" if mode in ("rig", "anim") else "OBJECT")
        print(f"[scene_setup] {arm.name}: "
              f"{'Pose' if mode in ('rig', 'anim') else 'Object'} mode")
    except Exception as exc:                     # pragma: no cover - UI only
        print(f"[scene_setup] could not change the mode ({exc})")


def set_timeline(mode: str) -> None:
    """100 fps in animation mode: 1 frame = 10 ms, so the JSON keys land on frames."""
    scene = bpy.context.scene
    if mode != "anim":
        print(f"[scene_setup] timeline left as is ({scene.render.fps} fps); "
              f"`--mode anim` sets 100 fps = 1 frame per 10 ms")
        return
    scene.render.fps = 100
    scene.render.fps_base = 1.0
    scene.frame_start = 1
    end = 1
    for action in bpy.data.actions:
        try:
            end = max(end, int(round(action.frame_range[1])))
        except Exception:
            continue
    scene.frame_end = max(end, 2)
    print(f"[scene_setup] timeline: 100 fps (1 frame = 10 ms), frames "
          f"{scene.frame_start}..{scene.frame_end}")


def scale_note(arm) -> None:
    """The engine does not inherit the scale: says it, never changes the data."""
    if arm is None or not arm.pose.bones:
        return
    modes = sorted({pose_bone.bone.inherit_scale for pose_bone in arm.pose.bones})
    if modes != ["NONE"]:
        print(f"[scene_setup] note: inherit_scale is {modes} on this armature, while "
              f"the engine does NOT inherit the scale of a parent "
              f"(docs/FORMAT.md). `tools/build_asset.py --to-blender` sets NONE on "
              f"the generated animation file.")


def report_pose(arm, planes: list) -> None:
    """A leftover pose only matters when the planes follow the armature."""
    posed = posed_bones(arm)
    if not posed:
        return
    shown = ", ".join(posed[:4]) + ("..." if len(posed) > 4 else "")
    # by name: reading `obj.parent` again gives a new Python wrapper (see bind)
    bound = [obj for obj in planes
             if obj.parent is not None and obj.parent.name == arm.name]
    if bound:
        print(f"[scene_setup] WARNING: the armature is posed ({shown}) and "
              f"{len(bound)}/{len(planes)} planes are bound to it: the export reads "
              f"the planes as they are, so reset the pose (Pose mode, "
              f"Alt+G / Alt+R / Alt+S) or the posed placement becomes the rest pose")
    else:
        print(f"[scene_setup] note: the armature is posed ({shown}) but no plane is "
              f"bound to it, so the placement read by the export is unaffected")


def next_steps(mode: str) -> None:
    print("[scene_setup] ready: wheel = zoom, middle drag = pan, Tab = Edit/Pose "
          "mode, Ctrl+S = save the .blend")
    if mode == "rig":
        print("[scene_setup] next: place the bone heads on the joints, save, then "
              "python tools/build_asset.py --rig-from-blender")
    elif mode == "anim":
        print("[scene_setup] next: edit the actions (Dope Sheet / Graph Editor), "
              "save, then python tools/build_asset.py --anims-from-blender")
    else:
        print("[scene_setup] next: place the planes (Images as Planes), save, then "
              "python tools/open_blender.py rig")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default="rig",
                    choices=["rig", "anim", "planes", "custom"])
    args = ap.parse_args(argv_after_dashdash())

    planes = [obj for obj in bpy.data.objects
              if obj.type == "MESH" and image_of(obj)]
    planes.sort(key=lambda obj: obj.name)
    arm = armature()

    for obj in planes:
        show(obj)
    if arm is not None:
        show(arm)
        arm.data.display_type = "OCTAHEDRAL"
        arm.data.show_names = True          # the bones must be readable...
        arm.show_in_front = True            # ...over the artwork of the planes

    report_pose(arm, planes)
    print(f"[scene_setup] mode {args.mode}, "
          f"{bpy.data.filepath or '(unsaved .blend)'}")
    report(planes, arm)
    scale_note(arm)
    setup_view_state(args.mode)
    set_timeline(args.mode)
    enter_mode(arm, args.mode)
    next_steps(args.mode)


main()
