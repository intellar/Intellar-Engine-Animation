/** Hardware description of the panel: wiring, geometry, orientation.
 *
 * Everything can be overridden from `platformio.ini` (`build_flags`), so the same
 * firmware drives another wiring or another mounting without touching the code:
 *
 *     -DANIM_ROTATION=90 -DANIM_DX=0 -DANIM_DY=0 -DANIM_SPI_HZ=40000000
 *
 * The pins are the ones of this robot's ILI9341, as used by the firmware of the
 * robot itself (which pushes a 240x240 image at x=40 of a **landscape 320x240**
 * panel -- that is why the default rotation is 90: the stage of the engine is
 * portrait 240x320, and turning it 90 degrees makes it fill the panel).
 */
#pragma once

#include <cstdint>

/** 0, 90, 180 or 270: how the stage is turned to fit the panel. */
#ifndef ANIM_ROTATION
#define ANIM_ROTATION 90
#endif

/** Where the (rotated) image goes, in panel pixels. */
#ifndef ANIM_DX
#define ANIM_DX 0
#endif
#ifndef ANIM_DY
#define ANIM_DY 0
#endif

/** SPI clock of the panel. 80 MHz usually works on a short ribbon cable. */
#ifndef ANIM_SPI_HZ
#define ANIM_SPI_HZ 40000000L
#endif

/** Backlight pin level that lights the panel up (some boards are inverted). */
#ifndef ANIM_BACKLIGHT_ON
#define ANIM_BACKLIGHT_ON HIGH
#endif

/** Replays the one-shot animation every MS ms (0 = only on the serial command). */
#ifndef ANIM_AUTO_MS
#define ANIM_AUTO_MS 0
#endif

/** 1 = read /rabbit3.iska from LittleFS instead of the embedded copy. */
#ifndef ANIM_USE_LITTLEFS
#define ANIM_USE_LITTLEFS 0
#endif

namespace lcd {

// --- the panel (native portrait geometry: the address window is swapped for
//     90/270, exactly like a library would do with setRotation()) ----------- //
constexpr int NativeWidth  = 240;
constexpr int NativeHeight = 320;
constexpr int Rotation     = ANIM_ROTATION;
constexpr int OffsetX      = ANIM_DX;
constexpr int OffsetY      = ANIM_DY;
constexpr int SpiHz        = static_cast<int>(ANIM_SPI_HZ);

// --- wiring (ESP32-S3) ----------------------------------------------------- //
constexpr int PinMosi    = 11;
constexpr int PinSclk    = 12;
constexpr int PinMiso    = 9;
constexpr int PinCs      = 47;
constexpr int PinDc      = 13;
constexpr int PinRst     = 14;
constexpr int PinBl      = 46;
constexpr int PinTouchCs = 48;   // left alone: this firmware has no touch code

}  // namespace lcd
