#include "display565.h"

#include <Arduino.h>
#include <SPI.h>
#include <cstring>

#include "lcd_config.h"

namespace display565 {
namespace {

// The ILI9341 hangs on a dedicated bus: MISO (9) is not the default one of the
// ESP32-S3, and DC (13) sits on the pin FSPI would use for MISO, so the pins are
// always given explicitly.
SPIClass panelBus(FSPI);

constexpr uint8_t kSoftReset = 0x01;
constexpr uint8_t kSleepOut  = 0x11;
constexpr uint8_t kDisplayOn = 0x29;
constexpr uint8_t kColumnSet = 0x2A;
constexpr uint8_t kPageSet   = 0x2B;
constexpr uint8_t kMemoryWrite = 0x2C;
constexpr uint8_t kMadCtl    = 0x36;
constexpr uint8_t kPixelFormat = 0x3A;

uint16_t* scratch = nullptr;         // one panel-sized image, in PSRAM if possible
uint32_t pushed = 0;

void command(uint8_t value) {
    digitalWrite(lcd::PinDc, LOW);
    digitalWrite(lcd::PinCs, LOW);
    panelBus.write(value);
    digitalWrite(lcd::PinCs, HIGH);
}

void data(const uint8_t* values, size_t count) {
    digitalWrite(lcd::PinDc, HIGH);
    digitalWrite(lcd::PinCs, LOW);
    panelBus.writeBytes(const_cast<uint8_t*>(values), count);
    digitalWrite(lcd::PinCs, HIGH);
}

void data8(uint8_t value) { data(&value, 1); }

// The classic ILI9341 power/gamma table (the same one every driver ships).
struct Entry { uint8_t cmd; uint8_t count; uint8_t values[15]; };
const Entry kInitTable[] = {
    {0xEF, 3, {0x03, 0x80, 0x02}},
    {0xCF, 3, {0x00, 0xC1, 0x30}},
    {0xED, 4, {0x64, 0x03, 0x12, 0x81}},
    {0xE8, 3, {0x85, 0x00, 0x78}},
    {0xCB, 5, {0x39, 0x2C, 0x00, 0x34, 0x02}},
    {0xF7, 1, {0x20}},
    {0xEA, 2, {0x00, 0x00}},
    {0xC0, 1, {0x23}},               // power control 1
    {0xC1, 1, {0x10}},               // power control 2
    {0xC5, 2, {0x3E, 0x28}},         // VCOM
    {0xC7, 1, {0x86}},               // VCOM offset
    {0xB1, 2, {0x00, 0x18}},         // frame rate: 79 Hz
    {0xB6, 3, {0x08, 0x82, 0x27}},   // display function control
    {0xF2, 1, {0x00}},               // 3G gamma off
    {0x26, 1, {0x01}},               // gamma curve 1
    {0xE0, 15, {0x0F, 0x31, 0x2B, 0x0C, 0x0E, 0x08, 0x4E, 0xF1,
                0x37, 0x07, 0x10, 0x03, 0x0E, 0x09, 0x00}},
    {0xE1, 15, {0x00, 0x0E, 0x14, 0x03, 0x11, 0x07, 0x31, 0xC1,
                0x48, 0x08, 0x0F, 0x0C, 0x31, 0x36, 0x0F}},
};

/** Memory access control: turns the address window 90/180/270 degrees. */
uint8_t madctl() {
    switch (lcd::Rotation) {
        case 90:  return 0x28;       // MV | BGR
        case 180: return 0x88;       // MY | BGR
        case 270: return 0xE8;       // MY | MX | MV | BGR
        default:  return 0x48;       // MX | BGR
    }
}

int windowWidth() {
    return (lcd::Rotation == 90 || lcd::Rotation == 270) ? lcd::NativeHeight
                                                         : lcd::NativeWidth;
}

int windowHeight() {
    return (lcd::Rotation == 90 || lcd::Rotation == 270) ? lcd::NativeWidth
                                                         : lcd::NativeHeight;
}

void setWindow(int x, int y, int width, int height) {
    const uint16_t x1 = static_cast<uint16_t>(x + width - 1);
    const uint16_t y1 = static_cast<uint16_t>(y + height - 1);
    const uint8_t columns[] = {static_cast<uint8_t>(x >> 8), static_cast<uint8_t>(x & 0xFF),
                               static_cast<uint8_t>(x1 >> 8), static_cast<uint8_t>(x1 & 0xFF)};
    const uint8_t pages[]   = {static_cast<uint8_t>(y >> 8), static_cast<uint8_t>(y & 0xFF),
                               static_cast<uint8_t>(y1 >> 8), static_cast<uint8_t>(y1 & 0xFF)};
    command(kColumnSet);
    data(columns, 4);
    command(kPageSet);
    data(pages, 4);
    command(kMemoryWrite);
}

/** Streams bytes in 4 KB chunks: what the SPI DMA likes, and short enough to
 *  leave the radio and the touch controller some air. */
void pushPixels(const uint16_t* pixels, size_t count) {
    const uint8_t* bytes = reinterpret_cast<const uint8_t*>(pixels);
    size_t left = count * 2;
    panelBus.beginTransaction(SPISettings(lcd::SpiHz, MSBFIRST, SPI_MODE0));
    digitalWrite(lcd::PinDc, HIGH);
    digitalWrite(lcd::PinCs, LOW);
    while (left > 0) {
        const size_t chunk = left > 4096 ? 4096 : left;
        panelBus.writeBytes(const_cast<uint8_t*>(bytes), chunk);
        bytes += chunk;
        left -= chunk;
    }
    digitalWrite(lcd::PinCs, HIGH);
    panelBus.endTransaction();
}

}  // namespace

bool begin() {
    pinMode(lcd::PinCs, OUTPUT);
    pinMode(lcd::PinDc, OUTPUT);
    pinMode(lcd::PinRst, OUTPUT);
    pinMode(lcd::PinBl, OUTPUT);
    digitalWrite(lcd::PinCs, HIGH);
    digitalWrite(lcd::PinBl, ANIM_BACKLIGHT_ON == HIGH ? LOW : HIGH);

    panelBus.begin(lcd::PinSclk, lcd::PinMiso, lcd::PinMosi, -1);

    digitalWrite(lcd::PinRst, HIGH);
    delay(10);
    digitalWrite(lcd::PinRst, LOW);
    delay(20);
    digitalWrite(lcd::PinRst, HIGH);
    delay(150);

    command(kSoftReset);
    delay(150);
    for (const Entry& entry : kInitTable) {
        command(entry.cmd);
        data(entry.values, entry.count);
    }
    command(kPixelFormat);
    data8(0x55);                     // 16 bits per pixel, RGB565
    command(kMadCtl);
    data8(madctl());
    command(kSleepOut);
    delay(120);
    command(kDisplayOn);
    delay(20);

    const size_t bytes = static_cast<size_t>(windowWidth()) * windowHeight() * 2;
    scratch = static_cast<uint16_t*>(ps_malloc(bytes));
    if (scratch == nullptr) {
        scratch = static_cast<uint16_t*>(malloc(bytes));   // last resort
        if (scratch != nullptr) {
            Serial.printf("[display] no PSRAM: the frame buffer is in the internal "
                          "RAM (%u B)\n", static_cast<unsigned>(bytes));
        }
    }
    if (scratch == nullptr) {
        Serial.printf("[display] FAILED: no memory for the %u B frame buffer\n",
                      static_cast<unsigned>(bytes));
        return false;
    }
    backlight(true);
    Serial.printf("[display] ILI9341 %dx%d, rotation %d, offset (%d,%d), SPI %d Hz\n",
                  windowWidth(), windowHeight(), lcd::Rotation, lcd::OffsetX,
                  lcd::OffsetY, lcd::SpiHz);
    return true;
}

void backlight(bool on) {
    digitalWrite(lcd::PinBl, on ? ANIM_BACKLIGHT_ON : (ANIM_BACKLIGHT_ON == HIGH ? LOW : HIGH));
}

void fill(uint16_t color) {
    if (scratch == nullptr) {
        return;
    }
    const int width = windowWidth();
    const int height = windowHeight();
    const uint16_t swapped = static_cast<uint16_t>((color >> 8) | (color << 8));
    for (size_t i = 0; i < static_cast<size_t>(width) * height; i++) {
        scratch[i] = swapped;
    }
    setWindow(0, 0, width, height);
    pushPixels(scratch, static_cast<size_t>(width) * height);
}

void show(const uint16_t* pixels, int width, int height) {
    if (scratch == nullptr || pixels == nullptr || width <= 0 || height <= 0) {
        return;
    }
    const int windowW = windowWidth();
    const int windowH = windowHeight();
    const bool turned = (lcd::Rotation == 90 || lcd::Rotation == 270);
    const int imageW = turned ? height : width;      // size of the turned image
    const int imageH = turned ? width : height;

    for (int y = 0; y < windowH; y++) {
        uint16_t* row = scratch + static_cast<size_t>(y) * windowW;
        const int dy = y - lcd::OffsetY;
        for (int x = 0; x < windowW; x++) {
            const int dx = x - lcd::OffsetX;
            uint16_t value = 0;                       // outside the image: black
            if (dx >= 0 && dy >= 0 && dx < imageW && dy < imageH) {
                size_t index = 0;
                switch (lcd::Rotation) {
                    case 90:                            // a quarter turn clockwise
                        index = static_cast<size_t>(height - 1 - dx) * width + dy;
                        break;
                    case 180:
                        index = static_cast<size_t>(height - 1 - dy) * width
                                + (width - 1 - dx);
                        break;
                    case 270:
                        index = static_cast<size_t>(dx) * width + (width - 1 - dy);
                        break;
                    default:
                        index = static_cast<size_t>(dy) * width + dx;
                        break;
                }
                // the panel wants the high byte first, the buffer is little-endian
                value = static_cast<uint16_t>((pixels[index] >> 8) | (pixels[index] << 8));
            }
            row[x] = value;
        }
    }

    setWindow(0, 0, windowW, windowH);
    pushPixels(scratch, static_cast<size_t>(windowW) * windowH);
    pushed++;
}

uint32_t frames() { return pushed; }

}  // namespace display565
