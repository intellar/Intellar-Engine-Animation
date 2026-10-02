# Notice -- licenses and provenance

This repository is published under **MIT** (see `LICENSE`). It contains **no line**
of code coming from the private Intellar-Engine repositories: the ISKA format, the
loader, the animation player and the Blender/Python tooling were written for this
repository.

## Vendored third-party code

| Path | Origin | License |
| :--- | :--- | :--- |
| `third_party/lcd/` (`Drivers/LCD.h`, `Drivers/LCD.cpp`) | [Intellar-Engine-Simulator](https://github.com/Intellar-Robotics/Intellar-Engine-Simulator) -- simulated ILI9341 screen on SDL2, by the same author | MIT (`third_party/lcd/LICENSE`) |
| `third_party/lcd/LICENSE` | copy of the original license file | MIT |

These two files are copied **verbatim**: no modification was made to them, so that
the original simulator and this demo can be updated independently. If you change
the behaviour of the screen, change it in the original repository instead, then
copy it here again.

## Dependencies not vendored (fetched at build time)

| Dependency | Used by | License |
| :--- | :--- | :--- |
| [SDL2](https://github.com/libsdl-org/SDL) (release-2.28.5) | simulated screen, demo window | zlib |
| [Pillow](https://python-pillow.org/) | Python tooling (`tools/*.py`) | MIT-CMU |
| [Blender](https://www.blender.org/) | source of the planes (`tools/source/*.blend`) | GPL -- used as a tool, not embedded |
| [CMake](https://cmake.org/) | C++ build | BSD-3-Clause |

SDL2 is downloaded by `FetchContent` at the first `cmake -B build`; it is not
versioned here.

## Art

The PNGs in `tools/source/` (character **rabbit3**) and the `rabbit3.blend` file
come from the work of this repository's author and are **not** covered by the MIT
license of the code: they remain the property of their author, who allows their use
within this demo. Do not reuse them outside this repository without permission.

These are **not** versioned in this repository (see `.gitignore`), because they are
useless to the export chain and heavy:

* `tools/source/full.paint` -- the original paint file (~3.7 MB);
* `tools/source/Gemini_Generated_Image_*.jpg` -- the reference image that was used
  as a basis for cutting out the planes (~1.4 MB).

Only the cut-out PNGs (`armL.png`, `torso.png`, ...) and the `.blend` files are
needed to rebuild `assets/rabbit3.iska`.

If you publish a demo with your own characters, simply replace the PNGs and the
`.blend`, then run the export chain again (see README).
