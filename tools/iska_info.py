"""Affiche le contenu d'un fichier .iska (os, parts, animations, poids).

    python tools/iska_info.py assets/rabbit3.iska
    python tools/iska_info.py assets/rabbit3.iska --json build/rabbit3/info.json

Utile pour verifier un asset livre, sans Blender ni PNG : le fichier est
autonome, donc ces chiffres sont exactement ceux que voit le moteur.
"""
from __future__ import annotations

import argparse
import json
import os

import iska_common as iska


def bone_tree(iska: dict) -> list:
    """[(profondeur, nom/index, texte)] : arbre des os (parents avant enfants)."""
    lines = []
    for i, bone in enumerate(iska["bones"]):
        parent = bone["parent"]
        depth = 0
        walker = parent
        seen = 0
        while walker is not None and seen < len(iska["bones"]):
            depth += 1
            walker = iska["bones"][walker]["parent"]
            seen += 1
        lines.append((depth, i, bone))
    return lines


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("iska")
    ap.add_argument("--json", default=None, help="ecrire un resume machine (JSON)")
    args = ap.parse_args()

    with open(args.iska, "rb") as fh:
        data = iska.parse_iska(fh.read())

    print(f"[info] {args.iska}")
    print(f"[info] version {data['version']}, panneau {data['stage'][0]}x{data['stage'][1]}, "
          f"{len(data['bones'])} os, {len(data['parts'])} parts, "
          f"{len(data['anims'])} animations, {data['bytes']} o au total")
    print(f"[info] bloc pixels : {len(data['pixels']) * 2} o "
          f"({os.path.getsize(args.iska) - data['pixel_offset']} o apres l'en-tete)")

    print("[info] os :")
    for depth, index, bone in bone_tree(data):
        parent_note = "" if bone["parent"] is None else "  <- os %d" % bone["parent"]
        print(f"[info]   {'  ' * depth}{index:2d} rest=({bone['rest'][0]:+6.1f},"
              f"{bone['rest'][1]:+6.1f}) angle={bone['angle']:+6.2f}{parent_note}")

    print("[info] parts :")
    for i, part in enumerate(data["parts"]):
        print(f"[info]   {i:2d} os={part['bone']:2d} case={part['sprite'][0]:3d}x{part['sprite'][1]:<3d} "
              f"pivot=({part['pivot'][0]:+6.1f},{part['pivot'][1]:+6.1f}) "
              f"ordre={part['draw_order']:2d} octets={part['pixel_bytes']}")

    for name, anim in data["anims"].items():
        print(f"[info] animation {name} : {anim['duration']} ms, "
              f"boucle={anim['loop']}, {len(anim['keys'])} cles")
        for t, pose in anim["keys"]:
            moved = [(i, p) for i, p in enumerate(pose)
                     if p[:3] != (0, 0, 0) or p[3:] != (1.0, 1.0)]
            detail = " ".join(f"os{i}:({p[0]:+.0f},{p[1]:+.0f},{p[2]:+.1f},"
                              f"{p[3]:.2f},{p[4]:.2f})" for i, p in moved)
            print(f"[info]   t={t:5d} {detail if detail else '(repos)'}")

    if args.json:
        summary = {
            "file": os.path.abspath(args.iska),
            "bytes": data["bytes"],
            "stage": data["stage"],
            "bones": [{"index": i, "parent": b["parent"], "rest": b["rest"],
                       "angle": b["angle"]} for i, b in enumerate(data["bones"])],
            "parts": data["parts"],
            "anims": {name: {"duration": a["duration"], "loop": a["loop"],
                             "keys": len(a["keys"])} for name, a in data["anims"].items()},
        }
        os.makedirs(os.path.dirname(os.path.abspath(args.json)), exist_ok=True)
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(summary, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        print(f"[info] resume JSON -> {args.json}")


if __name__ == "__main__":
    main()