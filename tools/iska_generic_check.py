"""Guards the boundary between the engine and its hosts.

    python tools/iska_generic_check.py

`src/Iska/` must stay **host agnostic**: it is used by the SDL demo of this
repository, by the ESP32 firmware of `firmware/esp32/`, and by anything else that
can give it a framebuffer. This script fails if a host concept ever leaks into it:

* no SDL, no Arduino, no ESP32/ESP-IDF, no LovyanGFX, no filesystem, no `main()`;
* no character-specific word either (`rabbit`, `torso`, `ear`, ...): the library
  describes a format, not a character;
* nothing but the C++ standard library is included (an allow-list, checked line by
  line), and no dynamic allocation of anything exotic.

It runs in a fraction of a second and needs no compiler, so it can guard every
commit -- including the ones that would add, say, a convenient `#include <Arduino.h>`
"just for the ESP32 build".
"""
from __future__ import annotations

import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
LIBRARY = os.path.join("src", "Iska")

# Words that betray a host, a character or a tool being pulled into the library.
# `std::fopen` in `loadAsset()` is allowed on purpose: a path is the smallest
# possible I/O, it compiles everywhere (the ESP32 firmware simply never calls it --
# it uses `parseAsset()` on the asset embedded in the binary). What must not appear
# is a filesystem *object model* (`<fstream>`, `std::filesystem`), a windowing
# library, an Arduino/ESP32 header, or the name of a character.
FORBIDDEN = [
    r"\bSDL\b", r"SDL_", r"#\s*include\s*<\s*SDL",
    r"\bArduino\b", r"Arduino\.h", r"esp_", r"ESP32", r"esp32", r"\bidf\b",
    r"\blgfx\b", r"LovyanGFX", r"M5Stack", r"TFT_eSPI",
    r"LittleFS", r"SPIFFS", r"std::filesystem", r"<fstream>", r"std::ifstream",
    r"\bmain\s*\(",
    r"rabbit", r"torso", r"\bear\b", r"\bearL\b", r"\bearR\b", r"\barmL\b",
    r"\bfootL\b", r"\bfootR\b",
]
# The only includes allowed in a host-agnostic library.
ALLOWED_INCLUDES = ["cstddef", "cstdint", "cstdio", "cstring", "cmath", "string",
                    "vector", "algorithm", "utility", "cstdlib", "climits", "new",
                    "limits", "initializer_list", "type_traits", "cassert",
                    "IskaFormat.h", "IskaLoader.h", "IskaPlayer.h", "IskaRender.h"]


def sources() -> list:
    directory = os.path.join(ROOT, LIBRARY)
    return [os.path.join(directory, name) for name in sorted(os.listdir(directory))
            if name.endswith((".h", ".cpp"))]


def strip_comments(text: str) -> str:
    """Comments out, **line numbers preserved** (block comments become newlines)."""
    text = re.sub(r"/\*.*?\*/", lambda match: "\n" * match.group(0).count("\n"),
                  text, flags=re.S)
    return re.sub(r"//[^\n]*", "", text)


def check() -> int:
    failures = 0
    files = sources()
    if not files:
        print(f"[generic] FAILED: no source in {LIBRARY}")
        return 1

    for path in files:
        with open(path, encoding="utf-8") as handle:
            raw = handle.read()
        text = strip_comments(raw)
        name = os.path.relpath(path, ROOT)
        for pattern in FORBIDDEN:
            for match in re.finditer(pattern, text):
                line = text.count("\n", 0, match.start()) + 1
                print(f"[generic] {name}:{line}: forbidden host word "
                      f"'{match.group(0)}' (the library must stay host agnostic)")
                failures += 1
        for match in re.finditer(r"#\s*include\s*<\s*([^>]+)\s*>", text):
            header = match.group(1).strip()
            if header not in ALLOWED_INCLUDES:
                line = text.count("\n", 0, match.start()) + 1
                print(f"[generic] {name}:{line}: unexpected include <{header}> "
                      f"(allowed: {', '.join(ALLOWED_INCLUDES)})")
                failures += 1
        for match in re.finditer(r"#\s*include\s*\"\s*([^\"]+)\s*\"", text):
            header = os.path.basename(match.group(1).strip())
            if header not in ALLOWED_INCLUDES:
                line = text.count("\n", 0, match.start()) + 1
                print(f"[generic] {name}:{line}: unexpected include \"{header}\"")
                failures += 1

    total = sum(len(open(path, encoding="utf-8").read().splitlines()) for path in files)
    if failures:
        print(f"[generic] {failures} problem(s): the library is not host agnostic "
              f"any more")
        return 1
    print(f"[generic] {LIBRARY}: {len(files)} files, {total} lines, no host, no "
          f"character, no forbidden include -- OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(check())