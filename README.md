# Intellar-Engine-Animation

Démo publique d'**animation osseuse** (squelette + parties découpées) pour
Intellar-Engine : un personnage pixel art **rabbit3** riggé et animé, joué sur le
panneau **ILI9341 240×320** (le format portrait du robot).

![Planche contact de l'animation peek](docs/img/rabbit3_peek.png)

*`peek` : le lapin est hors cadre, jaillit, regarde à gauche puis à droite, fait
un petit saut sur place et replonge. Images rendues à partir du binaire
`assets/rabbit3.iska` par `tools/iska_preview.py`.*

| | |
| :--- | :--- |
| Animations | `idle_loop` (respiration, boucle) + `peek` (one-shot) |
| Rig | 11 os, 10 parts, 60 ko de binaire autonome |
| Moteur | C++17 sans dépendance : lecture + rendu dans un framebuffer RGB565 |
| Chaîne | Blender → JSON → `.iska` (Python/Pillow), tout reproductible |
| Licence | MIT (code) — voir `NOTICE.md` pour les tiers |

## Ce que montre le dépôt

1. **Un format maison, documenté et outillé** ([docs/FORMAT.md](docs/FORMAT.md)) :
   un `.iska` contient le squelette, les sprites RGB565 et les animations. Le
   moteur n'a besoin de rien d'autre (ni Blender, ni PNG, ni JSON).
2. **Un lecteur temps réel** (`src/Iska/`) : hiérarchie d'os, interpolation de
   clés, blit affine au plus proche voisin avec clé de transparence magenta.
   Mesuré : **0,10 ms par image** sur ce lapin (2 000 images en 208 ms, soit
   ~9 600 images/s sur un cœur, panneau 240×320 effacé à chaque image —
   `intellar_anim_demo --bench 2000`).
3. **Un outillage Blender → squelette** (`tools/`) : le rig se pose à la souris
   dans Blender (les articulations se voient), puis tout le reste — échelle,
   pistes, pivots, ordre de dessin, empaquetage — est calculé automatiquement.
4. **Une vérification croisée** : le même rendu est implémenté en Python et en
   C++, et `tools/iska_clip_check.py` prouve que les deux donnent **des images
   identiques octet par octet** (94 images sur `rabbit3`). Un bug de l'un se voit
   immédiatement dans l'autre.

## Le rig en un coup d'œil

![Rig de rabbit3 : sprites, articulations et liaisons](docs/img/rabbit3_rig.png)

*Pose de repos vue par le moteur (`tools/rig_build.py --preview`) : croix rouges
= articulations, traits bleus = liaisons d'os.*

Et la boucle d'inactivité (respiration + clignement des yeux, 2,4 s) :

![Planche contact de idle_loop](docs/img/rabbit3_idle.png)

## Build & exécution (Windows / MSVC, ou tout compilateur C++17)

Prérequis : [CMake](https://cmake.org/) 3.16+ et un compilateur C++ (Visual
Studio 2022 Build Tools convient). **SDL2 est récupéré automatiquement** au
premier configure via `FetchContent`, rien à installer.

```powershell
cmake -S . -B build -G "Visual Studio 17 2022" -A x64
cmake --build build --config Release --target intellar_anim_demo
.\build\Release\intellar_anim_demo.exe --iska assets/rabbit3.iska
```

La fenêtre s'ouvre en **720×960** (panneau 240×320 × 3) : c'est l'écran simulé
du dépôt [Intellar-Engine-Simulator](https://github.com/Intellar-Robotics/Intellar-Engine-Simulator),
réutilisé tel quel (voir `NOTICE.md`).

| Entrée | Effet |
| :--- | :--- |
| *clic* / *tactile simulé* | joue `peek`, puis revient à `idle_loop` |
| `Échap` | quitte |
| `--auto 5000` | rejoue `peek` toutes les 5 s (idéal pour une capture) |

### Capture d'images, sans écran ni SDL

```powershell
.\build\Release\intellar_anim_demo.exe --iska assets/rabbit3.iska `
    --dump build\frames --anim all --keys
```

Chaque image est écrite en BMP (+ `.565` brut) et accompagnée d'une empreinte
**FNV-1a**, recalculée côté Python par `iska_clip_check.py` : c'est cette
empreinte partagée qui garantit que le moteur et l'outillage regardent la même
chose.

## La chaîne complète : Blender → `.iska`

```
tools/source/rabbit3.blend        plans posés à la main (Images as Planes)
        │  blender_make_rig.py     ajoute l'armature (11 os) au .blend
        ▼
tools/source/rabbit3_rig.blend    ← le squelette se retouche ICI, à la souris
        │  blender_export.py       lit plans + os  → build/rabbit3/scene.json
        ▼
tools/rig_build.py                échelle, pistes, pivots, ordre de dessin
        ▼
tools/rigs/rabbit3.json           rig runtime (tout en pixels écran)
        │  anims_rabbit3.py        écrit les animations (JSON, déterministe)
        ▼
tools/animations/rabbit3.json     poses par clé, en deltas
        │  iska_pack.py            PNG → RGB565, poses → binaire
        ▼
assets/rabbit3.iska               ce que le moteur charge
```

Toutes les commandes (à lancer depuis la racine du dépôt) :

```powershell
# 1. squelette de départ (idempotent : réécrit l'armature depuis les graines)
blender -b tools\source\rabbit3.blend --python tools\blender_make_rig.py -- `
    --bones tools\rigs\rabbit3_bones.json --out tools\source\rabbit3_rig.blend

# 2. export du placement Blender (plans + os)
blender -b tools\source\rabbit3_rig.blend --python tools\blender_export.py -- `
    --out build\rabbit3\scene.json

# 3. rig moteur + aperçu de contrôle (docs/img/rabbit3_rig.png)
python tools\rig_build.py build\rabbit3\scene.json --id rabbit3 `
    --out tools\rigs\rabbit3.json --preview build\rabbit3\rig_preview.png

# 4. animations, empaquetage, contrôle
python tools\anims_rabbit3.py --rig tools\rigs\rabbit3.json `
    --out tools\animations\rabbit3.json
python tools\iska_pack.py --rig tools\rigs\rabbit3.json `
    --anims tools\animations\rabbit3.json --out assets\rabbit3.iska

# 5. vérification C++ vs Python (94 images) — aussi via la cible CMake
python tools\iska_clip_check.py --iska assets\rabbit3.iska `
    --demo build\Release\intellar_anim_demo.exe
```

### Pourquoi passer par Blender pour le squelette ?

Parce que placer une articulation est un travail **visuel** : dans Blender, on
voit la patte, l'oreille et le plan, et on pose la tête d'os au bon endroit puis
on clique-parente. Une fois le `.blend` ajusté, tout le reste (échelle, lignes de
pieds, mise à l'échelle des cases, pivots ramenés dans l'image, ordre de dessin
tiré du Z, angles de repos) est **calculé**, jamais saisi à la main :

* `blender_make_rig.py` pose une armature de départ automatiquement (les graines
  de `tools/rigs/rabbit3_bones.json` sont des fractions de la boîte de chaque
  plan) : vous ne partez pas d'une page blanche ;
* `blender_export.py` ne fait que **lire** le `.blend` (il n'y écrit rien) ;
* `rig_build.py` note `"angles": "plane"` : par défaut l'angle de repos vient de
  la rotation du plan dans Blender, le rendu colle donc exactement au placement
  d'origine. `--angles bone` utilise la direction de l'os (utile si vous avez
  redressé les os pour définir la pose de référence).

Les **animations**, elles, s'écrivent en Python/JSON (`tools/anims_rabbit3.py`) :
un rebond de 90 ms ou un clignement de 80 ms se règlent plus vite dans un tableau
que dans une timeline, le résultat est versionnable, diffable et vérifiable sans
ouvrir Blender. Les deux animations fournies sont générées par du code :
`idle_loop` est une somme de sinusoïdes (dont les périodes divisent la durée, ce
qui garantit une boucle sans couture — vérifiée image par image), et `peek` est
un tableau d'images clés commenté.

## Outils

| Outil | Rôle |
| :--- | :--- |
| `tools/blender_make_rig.py` | crée/rafraîchit l'armature de départ dans un `.blend` |
| `tools/blender_export.py` | exporte plans + os du `.blend` vers `scene.json` (lecture seule) |
| `tools/rig_build.py` | calcule le rig runtime en pixels écran (+ aperçu PNG de contrôle) |
| `tools/anims_rabbit3.py` | écrit les deux animations (JSON déterministe, validé contre le rig) |
| `tools/iska_pack.py` | PNG → RGB565 + poses → `assets/rabbit3.iska` (`--check` pour valider sans écrire) |
| `tools/iska_info.py` | inspecte un `.iska` (os, parts, clés, tailles) |
| `tools/iska_preview.py` | rend une planche contact PNG d'une animation, sans Blender ni SDL |
| `tools/iska_clip_check.py` | vérifie binaire + invariants + **rendus C++ identiques à Python** |
| `tools/iska_common.py` | format + blitter + squelette, partagés (jumeau Python de `src/Iska/`) |

`tools/rigs/rabbit3_bones.json` (graines de squelette), `tools/rigs/rabbit3.json`
(rig runtime) et `tools/animations/rabbit3.json` (poses) sont **versionnés** :
l'asset `.iska` est donc reproductible à l'octet près sans Blender.

## Structure du dépôt

```
assets/rabbit3.iska        l'asset livré (60 ko, autonome)
demo/main.cpp              fenêtre SDL 240×320 + mode --dump/--bench
docs/FORMAT.md             spécification du format ISKA v1
docs/img/                  images du README (générées par l'outillage)
src/Iska/IskaFormat.h      constantes et structures du format
src/Iska/IskaLoader.*      chargement + validation (CRC, invariants)
src/Iska/IskaPlayer.*      lecture des animations, hiérarchie d'os
src/Iska/IskaRender.*      blit affine RGB565 au plus proche voisin
third_party/lcd/           écran simulé ILI9341 (MIT, voir NOTICE.md)
tools/                     chaîne Blender → .iska (Python)
tools/source/              rabbit3.blend, rabbit3_rig.blend et les PNG des plans
```

## Vérifier le rendu

```powershell
# cible CMake : build puis comparaison C++ / Python
cmake --build build --config Release --target iska_clip_check
```

Le contrôle échoue si un octet diffère, si le CRC ne colle pas, si un os
référence un parent trop tardif, si une boucle ne se raccorde pas ou si le
personnage disparaît au milieu d'une animation. C'est le filet de sécurité qui a
attrapé, pendant l'écriture de cette démo, un clignement d'yeux qui remettait
tout le corps au repos le temps d'une image (le bug était invisible sur les
empreintes de clés, visible sur celles des **images**).

## Adapter à un autre personnage

1. Modèlez les plans (Images as Planes) et posez l'armature à la souris dans
   Blender — ou partez d'un `blender_make_rig.py` adapté (fractions d'ancrage).
2. `blender_export.py` → `rig_build.py` : le rig est calculé. Ajustez au besoin
   `--height-frac` (hauteur du personnage dans le panneau), `--feet-y`
   (ligne de pieds) et `--center`.
3. Écrivez vos animations (`anims_rabbit3.py` comme modèle, ou directement le
   JSON), puis `iska_pack.py`.
4. `iska_clip_check.py` doit rester vert.

## Limites assumées

* Le blit est un **plus proche voisin** : pas d'anticrénelage, donc du pixel art
  net ; l'échelle est libre mais les rotations de sprite ne sont pas filtrées.
* Les angles sont stockés en **dixièmes de degré** (±3276,7°) : au-delà, il faut
  découper une rotation complète en plusieurs clés.
* L'échelle n'est **pas héritée** par les enfants (voir `docs/FORMAT.md`) : c'est
  ce qui rend le squash and stretch prévisible, mais un « parent qui grossit »
  doit être réglé os par os.
* Les poses d'un `.iska` sont **toutes** écrites (pas de compression) : ~11 octets
  par os et par clé. À cette échelle c'est négligeable (6 ko d'animations pour
  ce lapin), un personnage à 60 os nécessiterait une passe de compression.
* Blender n'est utilisé que comme **source du rig** : les animations ne sont pas
  cuites depuis des actions Blender (c'est possible, mais ce n'est pas ce que
  fait cette chaîne).

## Licence

Code sous **MIT** (`LICENSE`). L'écran simulé de `third_party/lcd/` provient
d'Intellar-Engine-Simulator (MIT) et y est recopié tel quel. Les PNG/`.blend` du
personnage appartiennent à leur auteur et ne sont pas couverts par la licence du
code — voir **[NOTICE.md](NOTICE.md)**.



