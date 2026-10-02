# ESP32-S3 firmware (standalone)

Plays `assets/rabbit3.iska` on the robot's ILI9341 panel. **Nothing of
Intellar-Engine is modified**: the repository's own `src/Iska/` is used as it is,
through the small `library.json` it carries (`lib_deps = symlink://../../src/Iska`),
and the panel is driven with the Arduino SPI directly, so there is no graphics
library to download either.

## One command

```powershell
python tools/flash_esp32.py                 # rebuilds the asset, compiles, uploads
python tools/flash_esp32.py --port COM5     # no port auto-detection
python tools/flash_esp32.py --build-only    # compile only (no board needed)
python tools/flash_esp32.py --monitor       # then opens the serial monitor
```

Without the wrapper (from the repository root):

```powershell
pio run -d firmware/esp32 -t upload --upload-port COM5
pio device monitor --port COM5
```

## What the board does

| Serial key | Effect |
| :--- | :--- |
| `t` | plays the one-shot animation (`peek`), then goes back to the loop |
| `r` | restarts the looping animation (`idle_loop`) |
| `i` | prints the asset summary (bones, parts, animations, bytes) |

Once a second it prints its frame rate, e.g.
`[esp32] 30 fps, idle_loop 1240/2400 ms loop (asset 59.9 kB)`. The frame rate is
what the panel allows: the stage is a 240x320 RGB565 image (153 600 B) and the SPI
link is the bottleneck, not the engine (see *Memory and speed*).

## The asset travels with the firmware

`board_build.embed_files` puts `assets/rabbit3.iska` **inside the firmware image**,
so flashing is enough: no LittleFS partition to fill, no file to upload, and the
animation cannot get out of sync with the code. Two details:

* `extra_script.py` stages a copy in `firmware/esp32/assets/` before the build,
  because PlatformIO names the embedded symbols after the **path** of the file -- a
  copy keeps them portable (`_binary_assets_rabbit3_iska_start`, the name
  `src/main.cpp` declares). The staged copy is a build artefact (git ignored).
* the asset is rebuilt by `tools/flash_esp32.py` before each upload, so the panel
  always gets what `python tools/build_asset.py` produces.

`--littlefs` (or `-DANIM_USE_LITTLEFS=1`) reads `/rabbit3.iska` from LittleFS
instead, which is handy to swap an animation without recompiling:

```powershell
pio run -d firmware/esp32 -t uploadfs     # after copying the asset to the data/ dir
```

## The panel

| Signal | Pin | | Signal | Pin |
| :--- | :--- | :--- | :--- | :--- |
| MOSI | 11 | | DC | 13 |
| SCLK | 12 | | RST | 14 |
| MISO | 9 | | Backlight | 46 |
| CS | 47 | | Touch CS | 48 (left alone) |

The pins are in `src/lcd_config.h`; so is the orientation, and both can be changed
from the command line (no file to edit):

```powershell
python tools/flash_esp32.py --rotation 0 --dx 0 --dy 0     # portrait mounting
python tools/flash_esp32.py --rotation 90                   # default
python tools/flash_esp32.py --spi-hz 80000000                # faster panel link
python tools/flash_esp32.py --auto-ms 5000                   # one-shot every 5 s
```

The default is **rotation 90** because the stage of the engine is portrait
(240x320) while this panel is driven in landscape (320x240) -- the same frame the
robot's own firmware uses when it pushes its 240x240 eye area at x=40. If the
character comes out sideways or off-centre on your panel, try `--rotation 270`
first (mirror image), then the offsets.

## Memory and speed

Measured on the build of this repository: **RAM 6.2 %** (20 308 B of 327 680) and
**flash 11.3 %** (378 613 B of 3 342 336, asset included). The framebuffer
(153 600 B) is allocated in PSRAM with `ps_malloc()`, with a fallback to the
internal RAM.

Per frame, the engine costs about **0.1 ms** (measured in the SDL demo of this
repository: 2 000 frames in 208 ms on one PC core) and the SPI transfer dominates:
153 600 B at 40 MHz is ~31 ms (32 fps), at 80 MHz ~15 ms. A slower panel link is
therefore *not* a problem for this animation.

## Troubleshooting

* **PlatformIO complains about several Cores** (`Obsolete PIO Core ... is used`):
  `python -m platformio upgrade`, or call the same `pio` the wrapper uses
  (`tools/flash_esp32.py` uses `pio` from the PATH, else `python -m platformio`).
* **The build stops with "missing asset"**: run `python tools/build_asset.py`.
* **The screen stays black**: check the backlight pin/level (`-DANIM_BACKLIGHT_ON=LOW`
  for an inverted transistor) and the wiring; `display565::fill(0x001F)` paints it
  blue, which is the quickest test.
* **Wrong colours (blue and red swapped)**: the MADCTL BGR bit is set in
  `display565.cpp` (`madctl()`); clear that bit for a panel wired the other way.
