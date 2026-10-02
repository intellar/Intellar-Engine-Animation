"""Builds the asset and flashes the ESP32 firmware, in one command.

    python tools/flash_esp32.py                    # asset, then upload
    python tools/flash_esp32.py --port COM5
    python tools/flash_esp32.py --port auto        # first USB serial port found
    python tools/flash_esp32.py --monitor          # upload, then open the monitor
    python tools/flash_esp32.py --build-only       # compile, no board needed
    python tools/flash_esp32.py --no-asset         # skip tools/build_asset.py
    python tools/flash_esp32.py --rotation 0       # override a panel macro

The asset is rebuilt first (`tools/build_asset.py`), so what lands on the panel is
always the current `assets/rabbit3.iska`; it is **embedded in the firmware** (see
`firmware/esp32/README.md`), which is why there is no separate file-upload step.

`--rotation/--dx/--dy/--spi-hz` are passed to the build as `-DANIM_*` flags
(through `PLATFORMIO_BUILD_FLAGS`), so they work without editing `platformio.ini`:
handy to find the right mounting of the panel in one shot.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
FIRMWARE = os.path.join("firmware", "esp32")


def environment() -> dict:
    """PlatformIO writes UTF-8; a French console would otherwise crash it."""
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env.setdefault("PLATFORMIO_CALLER", "tools/flash_esp32.py")
    return env


def pio_command() -> list:
    """`pio` when it is on the PATH, else `python -m platformio`."""
    found = shutil.which("pio")
    return [found] if found else [sys.executable, "-m", "platformio"]


def run(command: list, quiet: bool = False) -> str:
    if not quiet:
        print(f"[flash] $ {' '.join(command)}")
    result = subprocess.run(command, cwd=ROOT, env=environment(), text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if result.returncode != 0:
        if quiet and result.stdout:
            print(result.stdout[-3000:])
        raise SystemExit(f"[flash] step failed: {command[0]} "
                         f"(exit {result.returncode})")
    return result.stdout or ""


def device_list() -> list:
    """`[(port, description)]` of the serial ports PlatformIO can see."""
    ports = []
    try:
        raw = run(pio_command() + ["device", "list", "--json-output"], quiet=True)
        for entry in json.loads(raw):
            if entry.get("port"):
                ports.append((entry["port"], entry.get("description", "")))
    except Exception:
        raw = run(pio_command() + ["device", "list"], quiet=True)
        for line in raw.splitlines():
            match = re.match(r"^(\S+)\s{2,}(.*)$", line)
            if match and ("COM" in match.group(1) or "/dev/" in match.group(1)):
                ports.append((match.group(1), match.group(2).strip()))
    return ports


def find_port(explicit: str) -> str:
    if explicit and explicit != "auto":
        return explicit
    ports = device_list()
    if not ports:
        raise SystemExit("[flash] no serial port found: plug the board in, or pass "
                         "--port COM5 (`pio device list` shows what is there)")
    if explicit == "auto" or len(ports) == 1:
        print(f"[flash] port {ports[0][0]} ({ports[0][1]})")
        return ports[0][0]
    listing = ", ".join(f"{port} ({note})" for port, note in ports)
    raise SystemExit(f"[flash] several ports: {listing}\n"
                     f"[flash] pass --port <one of them>")


def build_asset() -> None:
    """The flashed asset must be the one the repository builds, not an old copy."""
    print("[flash] rebuilding the asset first (tools/build_asset.py)")
    run([sys.executable, os.path.join(HERE, "build_asset.py")])
    path = os.path.join(ROOT, "assets", "rabbit3.iska")
    with open(path, "rb") as fh:
        data = fh.read()
    print(f"[flash] assets/rabbit3.iska: {len(data)} B, sha256 "
          f"{hashlib.sha256(data).hexdigest()[:16]}...")


def apply_build_flags(args) -> None:
    """`-DANIM_*` flags handed to PlatformIO through `PLATFORMIO_BUILD_FLAGS`."""
    flags = []
    if args.rotation is not None:
        flags.append(f"-DANIM_ROTATION={args.rotation}")
    if args.dx is not None:
        flags.append(f"-DANIM_DX={args.dx}")
    if args.dy is not None:
        flags.append(f"-DANIM_DY={args.dy}")
    if args.spi_hz is not None:
        flags.append(f"-DANIM_SPI_HZ={args.spi_hz}")
    if args.auto_ms is not None:
        flags.append(f"-DANIM_AUTO_MS={args.auto_ms}")
    if args.littlefs:
        flags.append("-DANIM_USE_LITTLEFS=1")
    if flags:
        os.environ["PLATFORMIO_BUILD_FLAGS"] = " ".join(flags)
        print(f"[flash] extra build flags: {' '.join(flags)}")


def memory_usage(output: str) -> str:
    """Keeps the RAM/flash lines of a PlatformIO build, if it printed them."""
    lines = [line.strip() for line in output.splitlines()
             if line.startswith(("RAM:", "Flash:")) or "Took" in line
             or "SUCCESS" in line]
    return " | ".join(lines[-3:])


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--port", default="", help="serial port (or `auto`)")
    ap.add_argument("--build-only", action="store_true",
                    help="compile without a board")
    ap.add_argument("--monitor", action="store_true",
                    help="open the serial monitor after the upload (Ctrl+C to quit)")
    ap.add_argument("--no-asset", action="store_true",
                    help="do not rebuild assets/rabbit3.iska first")
    ap.add_argument("--rotation", type=int, choices=[0, 90, 180, 270],
                    help="panel rotation (default 90, see firmware/esp32/README.md)")
    ap.add_argument("--dx", type=int, help="horizontal offset of the image")
    ap.add_argument("--dy", type=int, help="vertical offset of the image")
    ap.add_argument("--spi-hz", type=int, help="SPI clock of the panel")
    ap.add_argument("--auto-ms", type=int, help="replay the one-shot every MS ms")
    ap.add_argument("--littlefs", action="store_true",
                    help="read /rabbit3.iska from LittleFS instead of the embedded copy")
    ap.add_argument("-v", "--verbose", action="store_true",
                    help="show the whole PlatformIO output")
    args = ap.parse_args()

    apply_build_flags(args)
    if not args.no_asset:
        build_asset()
    if args.build_only:
        output = run(pio_command() + ["run", "-d", FIRMWARE], quiet=not args.verbose)
        print(f"[flash] build OK -- {memory_usage(output)}")
        return

    output = run(pio_command() + ["run", "-d", FIRMWARE, "-t", "upload",
                                  "--upload-port", find_port(args.port)],
                 quiet=not args.verbose)
    print(f"[flash] upload OK -- {memory_usage(output)}")
    print("[flash] on the board: t = one-shot, r = restart the loop, i = summary")

    if args.monitor:
        run(pio_command() + ["device", "monitor", "-d", FIRMWARE,
                             "--port", find_port(args.port)])


if __name__ == "__main__":
    main()
