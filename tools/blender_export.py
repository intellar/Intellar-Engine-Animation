"""Exporte le placement des plans et le squelette d'un .blend vers un JSON.

    blender -b tools/source/rabbit3_rig.blend --python tools/blender_export.py -- \
        --out build/rabbit3/scene.json

Le JSON produit est le **contrat** entre Blender et le reste de la chaine : il
contient, pour chaque plan (part) :

  - sa boite **locale** (`local`) : rectangle non tourne, non mis a l'echelle ;
  - sa matrice monde 4x4 (`matrix`, ligne par ligne) : position + rotation Z +
    echelle uniforme posees a la main dans Blender ;
  - sa boite monde (`world_bbox`) : rectangle englobant, apres rotation ;
  - le nom de son image (`image`, `image_path`) ;
  - son Z (`z`) : ordre de dessin (plus grand = plus devant).

Et, si une armature est presente, ses os (`armature.bones`) : nom, parent, tete
et queue en coordonnees **monde** (c'est la tete qui devient l'articulation du
squelette moteur). Les actions de pose sont listees (`actions`) pour information :
elles ne sont pas encore cuites en keyframes (les animations s'ecrivent en JSON,
voir `tools/animations/`).

Ce script ne fait que lire la scene : il n'enregistre rien dans le .blend.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import bpy                       # noqa: E402  (fourni par Blender)
from mathutils import Vector     # noqa: E402


def argv_after_dashdash() -> list:
    return sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []


def image_of(obj):
    """(nom, chemin resolu) de la premiere image trouvee dans les materiaux."""
    for slot in obj.material_slots:
        mat = slot.material
        if mat is None:
            continue
        tree = getattr(mat, "node_tree", None)   # pas `use_nodes` (deprecie en 5.x)
        if tree is None:
            continue
        for node in tree.nodes:
            if node.type == "TEX_IMAGE" and node.image:
                img = node.image
                raw = img.filepath or ""
                if raw.startswith("//"):
                    raw = os.path.join(os.path.dirname(bpy.data.filepath), raw[2:])
                return img.name, (os.path.abspath(raw) if raw else "")
    return "", ""


def dump_part(obj) -> dict:
    corners = [Vector(c) for c in obj.bound_box]
    local = [min(c.x for c in corners), min(c.y for c in corners),
             max(c.x for c in corners), max(c.y for c in corners)]
    world = [obj.matrix_world @ c for c in corners]
    image, image_path = image_of(obj)
    matrix = obj.matrix_world
    return {
        "name": obj.name,
        "image": image,
        "image_path": image_path,
        "local": [round(v, 6) for v in local],
        "matrix": [[round(matrix[r][c], 6) for c in range(4)] for r in range(4)],
        "world_bbox": [round(min(v.x for v in world), 6), round(min(v.y for v in world), 6),
                       round(max(v.x for v in world), 6), round(max(v.y for v in world), 6)],
        "z": round(sum(v.z for v in world) / len(world), 6),
        "rot_z_deg": round(obj.rotation_euler.z * 57.29577951308232, 4),
        "scale_xyz": [round(v, 6) for v in obj.scale],
        "parent": obj.parent.name if obj.parent else None,
    }


def dump_armature():
    arm_obj = next((o for o in bpy.data.objects if o.type == "ARMATURE"), None)
    if arm_obj is None:
        return None
    mw = arm_obj.matrix_world
    bones = []
    for bone in arm_obj.data.bones:
        head = mw @ bone.head_local
        tail = mw @ bone.tail_local
        bones.append({
            "name": bone.name,
            "parent": bone.parent.name if bone.parent else None,
            "head": [round(head.x, 6), round(head.y, 6)],
            "tail": [round(tail.x, 6), round(tail.y, 6)],
            "head_local": [round(v, 6) for v in bone.head_local],
            "tail_local": [round(v, 6) for v in bone.tail_local],
        })
    return {"name": arm_obj.name,
            "matrix": [[round(mw[r][c], 6) for c in range(4)] for r in range(4)],
            "bones": bones}


def dump_actions() -> list:
    out = []
    for act in bpy.data.actions:
        targets = set()
        for fc in act.fcurves:
            path = fc.data_path
            if path.startswith('pose.bones["'):
                targets.add(path.split('"')[1])
        out.append({
            "name": act.name,
            "frame_range": [round(v, 3) for v in act.frame_range],
            "fcurves": len(act.fcurves),
            "pose_bones": sorted(targets),
        })
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, help="JSON de sortie")
    args = ap.parse_args(argv_after_dashdash())

    parts = [dump_part(o) for o in bpy.data.objects
             if o.type == "MESH" and image_of(o)[0]]
    parts.sort(key=lambda p: p["z"])

    data = {
        "blender": bpy.app.version_string,
        "blend": os.path.abspath(bpy.data.filepath),
        "units": "Blender (1 unite = 1 plan de reference ; voir tools/rig_build.py)",
        "parts": parts,
        "armature": dump_armature(),
        "actions": dump_actions(),
    }

    out_path = os.path.abspath(args.out)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
        fh.write("\n")

    print(f"[blender_export] {len(parts)} plans, "
          f"{len(data['armature']['bones']) if data['armature'] else 0} os, "
          f"{len(data['actions'])} actions -> {out_path}")
    for part in parts:
        print(f"[blender_export]   {part['name']:6s} z={part['z']:+.2f} "
              f"rot={part['rot_z_deg']:+.1f}deg local={part['local']}")


main()
