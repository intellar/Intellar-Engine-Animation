"""PlatformIO pre-build script: stages the ISKA asset before the build.

`board_build.embed_files` names the symbols after the **path** of the file it
embeds. Embedding `../../assets/rabbit3.iska` directly would therefore bake
`_binary_C__Users_..._assets_rabbit3_iska_start` into the binary -- a symbol that
changes with the machine. Copying the file to `firmware/esp32/assets/rabbit3.iska`
first makes the name stable (`_binary_assets_rabbit3_iska_start`), which is what
`src/main.cpp` declares; the copy is a build artefact (git ignored), the asset
itself stays where it belongs: `assets/rabbit3.iska`.

It also fails early, with a readable message, when the asset has not been built.
"""
import os
import shutil

Import("env")                                    # noqa: F821 (PlatformIO/SCons)

PROJECT = env["PROJECT_DIR"]                     # noqa: F821
SOURCE = os.path.normpath(os.path.join(PROJECT, os.pardir, os.pardir, "assets",
                                      "rabbit3.iska"))
STAGED = os.path.join(PROJECT, "assets", "rabbit3.iska")

if not os.path.isfile(SOURCE):
    raise SystemExit(
        "\n[firmware] missing asset: %s\n"
        "[firmware] build it first:  python tools/build_asset.py\n" % SOURCE)

if not os.path.isfile(STAGED) or os.path.getmtime(STAGED) < os.path.getmtime(SOURCE):
    os.makedirs(os.path.dirname(STAGED), exist_ok=True)
    shutil.copyfile(SOURCE, STAGED)
    print("[firmware] staged %s (%d B)" % (STAGED, os.path.getsize(STAGED)))
