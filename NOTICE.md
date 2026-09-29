# Notice — licences et provenances

Ce dépôt est publié sous **MIT** (voir `LICENSE`). Il ne contient **aucune ligne**
de code provenant des dépôts privés Intellar-CyberAnima / Intellar-Engine : le
format ISKA, le chargeur, le lecteur d'animations et l'outillage Blender/Python
ont été écrits pour ce dépôt.

## Code tiers embarqué (vendored)

| Chemin | Origine | Licence |
| :--- | :--- | :--- |
| `third_party/lcd/` (`Drivers/LCD.h`, `Drivers/LCD.cpp`) | [Intellar-Engine-Simulator](https://github.com/Intellar-Robotics/Intellar-Engine-Simulator) — ecran simule ILI9341 sur SDL2, par le meme auteur | MIT (`third_party/lcd/LICENSE`) |
| `third_party/lcd/LICENSE` | copie du fichier de licence d'origine | MIT |

Ces deux fichiers sont recopies **tels quels** : aucune modification n'y a été
apportée, afin que le simulateur d'origine et cette démo puissent être mis à jour
indépendamment. Si vous modifiez le comportement de l'écran, changez-le plutôt
dans le dépôt d'origine puis recopiez-le ici.

## Dépendances non embarquées (récupérées au build)

| Dépendance | Utilisée par | Licence |
| :--- | :--- | :--- |
| [SDL2](https://github.com/libsdl-org/SDL) (release-2.28.5) | écran simule, fenêtre de la démo | zlib |
| [Pillow](https://python-pillow.org/) | outillage Python (`tools/*.py`) | MIT-CMU |
| [Blender](https://www.blender.org/) | source des plans (`tools/source/*.blend`) | GPL — utilisé comme outil, pas embarqué |
| [CMake](https://cmake.org/) | build C++ | BSD-3-Clause |

SDL2 est téléchargé par `FetchContent` au premier `cmake -B build` ; il n'est pas
versionné ici.

## Art

Les PNG de `tools/source/` (personnage **rabbit3**) et le fichier
`rabbit3.blend` proviennent du travail de l'auteur de ce dépôt et ne sont **pas**
couverts par la licence MIT du code : ils restent la propriété de leur auteur,
qui autorise leur utilisation dans le cadre de cette démo. Ne les réutilisez pas
hors de ce dépôt sans autorisation.

Ne sont **pas** versionnés dans ce dépôt (voir `.gitignore`), car inutiles à la
chaîne d'export et lourds :

* `tools/source/full.paint` — le fichier de peinture d'origine (~3,7 Mo) ;
* `tools/source/Gemini_Generated_Image_*.jpg` — l'image de référence qui a servi
  de base au découpage des plans (~1,4 Mo).

Seuls les PNG découpés (`armL.png`, `torso.png`, …) et les `.blend` sont
nécessaires pour reconstruire `assets/rabbit3.iska`.

Si vous publiez une démo avec vos propres personnages, remplacez simplement les
PNG et le `.blend`, puis relancez la chaîne d'export (voir README).
