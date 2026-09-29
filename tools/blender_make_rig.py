"""Cree (ou remet a jour) l'armature du personnage dans un .blend, sans interface.

    blender -b tools/source/rabbit3.blend --python tools/blender_make_rig.py -- \
        --bones tools/rigs/rabbit3_bones.json \
        --out tools/source/rabbit3_rig.blend

Les plans du personnage ont ete poses a la main dans Blender (« Images as Planes ») ;
ce script pose par-dessus les **tetes d'os** deduites de ces plans (voir
`anchor` dans le JSON de graines), relie les os entre eux, puis enregistre une
copie du .blend. C'est un POINT DE DEPART : l'armature s'ajuste ensuite a la
souris dans Blender (`rabbit3_rig.blend` est la reference du squelette).

Une fois l'armature ajustee, l'export se fait avec `tools/blender_export.py`
(qui relit les tetes d'os, pas les graines).

Si une armature du meme nom existe deja, elle est **effacee** puis recreee : le
script est idempotent (pratique pour repartir des graines).
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import bpy                      # noqa: E402  (fourni par Blender)
from mathutils import Vector     # noqa: E402


def argv_after_dashdash() -> list:
    return sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []


def norm(name: str) -> str:
    return "".join(ch for ch in name.lower() if ch.isalnum())


def meshes_by_name() -> dict:
    """Plans utilisables comme parts : mesh avec une image dans ses materiaux."""
    found = {}
    for obj in bpy.data.objects:
        if obj.type != "MESH":
            continue
        found[obj.name] = obj
        found.setdefault(norm(obj.name), obj)
    return found


def local_rect(obj):
    """Rectangle local du plan : lu dans le mesh (pas via `obj.bound_box`, dont le
    cache n'est pas fiable ici : il renvoie des valeurs aberrantes selon l'ordre
    des lectures, meme en mode objet)."""
    verts = [v.co for v in obj.data.vertices]
    if not verts:                       # mesh sans sommet : repli sur le cache
        verts = [Vector(c) for c in obj.bound_box]
    return (min(v.x for v in verts), min(v.y for v in verts),
            max(v.x for v in verts), max(v.y for v in verts))


def anchor_world(obj, anchor) -> Vector:
    lx0, ly0, lx1, ly1 = local_rect(obj)
    ax, ay = anchor
    local = Vector((lx0 + ax * (lx1 - lx0), ly0 + ay * (ly1 - ly0), 0.0))
    return obj.matrix_world @ local


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bones", default="tools/rigs/rabbit3_bones.json")
    ap.add_argument("--out", default="tools/source/rabbit3_rig.blend")
    args = ap.parse_args(argv_after_dashdash())

    with open(args.bones, encoding="utf-8") as fh:
        seeds = json.load(fh)

    parts = meshes_by_name()
    length = float(seeds.get("bone_length", 0.35))
    arm_name = seeds.get("armature", "skeleton")

    # Idempotence : on repart d'une armature neuve.
    old = bpy.data.objects.get(arm_name)
    if old is not None:
        bpy.data.objects.remove(old, do_unlink=True)

    # Mesures AVANT d'entrer en mode edit : Blender ne reevalue pas la boite des
    # autres objets pendant l'edition d'un objet (bound_box y est vide/aberrant).
    heads = {}
    tails = {}
    for seed in seeds["bones"]:
        part = parts.get(seed["part"]) or parts.get(norm(seed["part"]))
        if part is None:
            print(f"[make_rig] plan introuvable pour l'os {seed['name']} ({seed['part']})")
            continue
        head = anchor_world(part, seed["anchor"])
        direction = Vector((seed["dir"][0], seed["dir"][1], 0.0))
        if direction.length == 0:
            direction = Vector((0.0, 1.0, 0.0))
        heads[seed["name"]] = head
        tails[seed["name"]] = head + direction.normalized() * length

    arm_data = bpy.data.armatures.new(arm_name)
    arm_obj = bpy.data.objects.new(arm_name, arm_data)
    bpy.context.collection.objects.link(arm_obj)
    bpy.context.view_layer.objects.active = arm_obj
    arm_obj.select_set(True)

    bpy.ops.object.mode_set(mode="EDIT")
    made = {}
    for seed in seeds["bones"]:
        if seed["name"] not in heads:
            continue
        edit_bone = arm_data.edit_bones.new(seed["name"])
        edit_bone.head = heads[seed["name"]]
        edit_bone.tail = tails[seed["name"]]
        made[seed["name"]] = edit_bone
    for seed in seeds["bones"]:
        bone = made.get(seed["name"])
        if bone is None or not seed["parent"]:
            continue
        parent = made.get(seed["parent"])
        if parent is None:
            print(f"[make_rig] parent inconnu pour {seed['name']} : {seed['parent']}")
            continue
        bone.parent = parent
    bpy.ops.object.mode_set(mode="OBJECT")

    out_path = os.path.abspath(args.out)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=out_path)
    print(f"[make_rig] {len(made)} os -> {out_path}")
    # NB : on imprime `heads` (releve avant l'edition) et non les `edit_bones` :
    # apres le retour en mode objet, ces handles pointent sur de la memoire liberee.
    for seed in seeds["bones"]:
        head = heads.get(seed["name"])
        if head is not None:
            print(f"[make_rig]   {seed['name']:6s} head=({head.x:+.3f}, {head.y:+.3f}) "
                  f"parent={seed['parent']}")


main()
