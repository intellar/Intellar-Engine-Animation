/** The panel: init, orientation, and pushing an RGB565 image (Arduino SPI only).
 *
 * Deliberately minimal -- the engine draws into a plain `uint16_t` buffer and this
 * is the only file that knows about wires:
 *
 *     display565::begin();
 *     display565::show(frame, stageW, stageH);   // rotation/offsets applied here
 *
 * `show()` turns and places the image as described in `lcd_config.h` (rotation 90
 * by default), then streams the whole panel in one SPI burst.
 */
#pragma once

#include <cstdint>

namespace display565 {

/** SPI + panel init + backlight. Returns false if the (PSRAM) scratch buffer
 *  could not be allocated, in which case `show()` does nothing. */
bool begin();

/** Lights the panel up or down. */
void backlight(bool on);

/** Pushes an RGB565 `width x height` image, turned and placed by the macros of
 *  `lcd_config.h`. Does nothing if `begin()` failed. */
void show(const uint16_t* pixels, int width, int height);

/** Fills the whole panel with one colour (useful to test the wiring). */
void fill(uint16_t color);

/** Number of frames pushed since `begin()`. */
uint32_t frames();

}  // namespace display565
