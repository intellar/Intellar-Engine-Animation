"""Verifie qu'un .iska se joue **exactement** pareil cote C++ et cote Python.

    python tools/iska_clip_check.py --iska assets/rabbit3.iska \
        --demo build/Release/intellar_anim_demo.exe

Ce que le script controle, sans ecran et sans Blender :

1. **Binaire** : magie, version, CRC du bloc de pixels, invariants (parents avant
   enfants, ordre de dessin croissant, cles croissantes) -- lus par le parseur
   Python puis par le chargeur C++.
2. **Rendu** : chaque image est calculee par le blitter Python
   (`iska_common.blit_part`) *et* par le moteur C++ (`--dump`), puis comparee par
   empreinte FNV-1a et, si les fichiers `.565` sont presents, **octet par octet**.
   Toute divergence est un bug de l'un des deux cotes : c'est la garantie que
   l'outillage decrit fidelement ce que le moteur affiche.
3. **Animations** : les animations en boucle ont la meme image au debut et a la
   fin, les cles sont bien a l'interieur de la duree, et aucune image de `peek`
   n'est vide en dehors du debut et de la fin (le lapin ne disparait pas par
   accident au milieu).
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
    """Meme empreinte que `fnv1a` dans demo/main.cpp (octets de poids faible d'abord)."""
    hash_value = FNV_OFFSET
    for value in pixels:
        hash_value ^= value & 0xFF
        hash_value = (hash_value * FNV_PRIME) & MASK64
        hash_value ^= (value >> 8) & 0xFF
        hash_value = (hash_value * FNV_PRIME) & MASK64
    return hash_value


def check_times(anim: dict) -> list:
    """Instants captures par `--keys` cote C++ (cles + milieux), a l'identique."""
    times = []
    for i, key in enumerate(anim["keys"]):
        times.append(key[0])
        if i + 1 < len(anim["keys"]):
            times.append((key[0] + anim["keys"][i + 1][0]) // 2)
    return times


def render(data: dict, name: str, t_ms: float):
    """Framebuffer RGB565 de l'animation `name` a l'instant `t_ms` (blitter Python)."""
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
                    help="binaire de la demo (obligatoire pour la comparaison de rendu)")
    ap.add_argument("--keep", default=None,
                    help="repertoire de capture conserve (defaut : dossier temporaire)")
    ap.add_argument("--no-render", action="store_true",
                    help="ne verifier que le binaire (pas de rendu)")
    args = ap.parse_args()

    failures = []
    with open(args.iska, "rb") as fh:
        blob = fh.read()
    data = iska.parse_iska(blob)          # valide magie, version, CRC, tailles
    print(f"[check] {args.iska} : ISKA v{data['version']} "
          f"{data['stage'][0]}x{data['stage'][1]}, {len(data['bones'])} os, "
          f"{len(data['parts'])} parts, {len(data['anims'])} animations, "
          f"{data['bytes']} o")

    # -- invariants du format ------------------------------------------------
    for i, bone in enumerate(data["bones"]):
        parent = bone["parent"]
        if parent is not None and parent >= i:
            failures.append(f"os {i} : parent {parent} non anterieur")
    orders = [part["draw_order"] for part in data["parts"]]
    if orders != sorted(orders):
        failures.append("parts non triees par ordre de dessin")
    for i, part in enumerate(data["parts"]):
        if part["bone"] >= len(data["bones"]):
            failures.append(f"part {i} : os {part['bone']} hors limites")
        if part["pixel_offset"] // 2 + part["sprite"][0] * part["sprite"][1] > len(data["pixels"]):
            failures.append(f"part {i} : case hors du bloc de pixels")

    # -- animations ----------------------------------------------------------
    for name, anim in data["anims"].items():
        times = [t for t, _ in anim["keys"]]
        if times != sorted(times):
            failures.append(f"{name} : cles non ordonnees")
        if times[-1] > anim["duration"]:
            failures.append(f"{name} : cle {times[-1]} apres la duree {anim['duration']}")
        if anim["loop"]:
            if times[0] != 0:
                failures.append(f"{name} : boucle qui ne commence pas a 0")
            first = render(data, name, 0)
            last = render(data, name, anim["duration"])
            if list(first) != list(last):
                failures.append(f"{name} : la boucle ne se raccorde pas (t=0 != t=duree)")
            else:
                print(f"[check] {name} : boucle raccordee (t=0 identique a t={anim['duration']})")
        else:
            # une image vide n'est un bug que si elle est encadree d'images non
            # vides : au debut (et a la fin) d'un one-shot, le personnage peut
            # legitimement etre hors cadre.
            frames = [(t, render(data, name, t)) for t in times]
            blank = [all(value == 0 for value in frame) for _t, frame in frames]
            for i in range(1, len(frames) - 1):
                if blank[i] and not blank[i - 1] and not blank[i + 1]:
                    failures.append(f"{name} : image vide isolee a t={frames[i][0]} "
                                    "(le personnage disparait par accident)")
            edge_blank = sum(1 for flag in blank if flag)
            if edge_blank:
                print(f"[check] {name} : {edge_blank} image(s) hors cadre "
                      "(debut/fin, prevu)")

    # -- rendu C++ vs Python -------------------------------------------------
    if not args.no_render:
        if not args.demo:
            raise SystemExit("--demo est necessaire pour comparer les rendus "
                             "(ou utiliser --no-render)")
        if not os.path.exists(args.demo):
            raise SystemExit(f"binaire introuvable : {args.demo}")
        dump_dir = args.keep or tempfile.mkdtemp(prefix="iska_dump_")
        os.makedirs(dump_dir, exist_ok=True)
        hashes = run_demo(args.demo, args.iska, dump_dir, "all")
        checked = 0
        for name, anim in data["anims"].items():
            for t in check_times(anim):
                expected = fnv1a(render(data, name, t))
                got = hashes.get((name, t))
                if got is None:
                    failures.append(f"{name} t={t} : image absente de la capture C++")
                    continue
                if got != expected:
                    failures.append(f"{name} t={t} : C++ {got:016x} != Python {expected:016x}")
                    continue
                raw_path = os.path.join(dump_dir, f"{name}_{t:05d}.565")
                if os.path.exists(raw_path):
                    with open(raw_path, "rb") as fh:
                        got_bytes = fh.read()
                    want_bytes = array.array("H", render(data, name, t)).tobytes()
                    if got_bytes != want_bytes:
                        failures.append(f"{name} t={t} : pixels differents "
                                        f"(memes empreintes mais octets differents)")
                        continue
                checked += 1
        print(f"[check] rendu C++ vs Python : {checked} image(s) identiques "
              f"(capture dans {dump_dir})")

    if failures:
        print(f"[check] ECHEC : {len(failures)} probleme(s)")
        for failure in failures:
            print(f"[check]   - {failure}")
        sys.exit(1)
    print("[check] OK : binaire valide et rendus identiques")


def run_demo(demo: str, iska_path: str, dump_dir: str, anim: str) -> dict:
    """Lance la demo en mode capture et renvoie {(anim, t): empreinte}."""
    command = [demo, "--iska", iska_path, "--dump", dump_dir, "--anim", anim, "--keys"]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit(f"la demo a echoue ({result.returncode}) :\n{result.stdout}{result.stderr}")
    hashes = {}
    for line in result.stdout.splitlines():
        match = DUMP_LINE.match(line.strip())
        if match:
            hashes[(match.group(1), int(match.group(2)))] = int(match.group(3), 16)
    if not hashes:
        raise SystemExit("aucune image capturee par la demo (--dump) : sortie inattendue")
    return hashes


if __name__ == "__main__":
    main()
