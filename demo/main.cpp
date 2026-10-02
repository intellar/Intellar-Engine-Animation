/**
 * Intellar-Engine-Animation demo: plays `assets/rabbit3.iska` on the simulated
 * screen (SDL2) of the Intellar-Engine-Simulator repository.
 *
 * Two modes:
 *
 *  1. **Window** (default): 240x320 panel (the real portrait setup); the screen
 *     shows the idle loop, a click (simulated touch) triggers the one-shot
 *     animation, then it goes back to the loop.
 *
 *         intellar_anim_demo --iska assets/rabbit3.iska
 *         intellar_anim_demo --iska assets/rabbit3.iska --auto 5000
 *
 *  2. **Capture** (`--dump DIR`): no window, no SDL. Renders the frames into
 *     BMP files (+ raw .565 files): this is the mode used to check the render
 *     without a screen, and to compare it with `tools/iska_preview.py`.
 *
 *         intellar_anim_demo --iska assets/rabbit3.iska --dump build/frames \
 *             --anim all --keys
 *
 * Every captured frame comes with an FNV-1a fingerprint: the very same
 * fingerprint is computed on the Python side (`tools/iska_clip_check.py`),
 * which proves that both renderers are identical down to the pixel.
 */
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <chrono>
#include <filesystem>
#include <string>
#include <vector>

#include "Drivers/LCD.h"
#include "Iska/IskaLoader.h"
#include "Iska/IskaPlayer.h"

namespace {

struct Options {
    std::string iska      = "assets/rabbit3.iska";
    std::string idle      = "";        // background animation (default: first loop)
    std::string oneShot   = "peek";    // animation triggered by a click
    std::string dumpDir   = "";        // capture mode (no window)
    std::string anim      = "";        // animation to capture ("all" = every one)
    std::vector<uint32_t> at;          // explicit times (ms)
    int         frames    = 0;         // evenly spaced frames (when --at is absent)
    bool        keys      = false;     // capture on the keys (+ in between)
    bool        raw       = true;      // also write the raw .565 files
    uint32_t    autoMs    = 0;         // periodic one-shot (window)
    int         bench     = 0;         // --bench N: N frames rendered, nothing written
    uint16_t    background = 0x0000;
};

void usage() {
    std::printf(
        "intellar_anim_demo --iska FILE [options]\n"
        "  --idle NAME     background animation (default: the first looping one)\n"
        "  --once NAME     animation played on click (default: peek)\n"
        "  --auto MS       replays the one-shot every MS ms (0 = never)\n"
        "  --bg R,G,B      background colour (default 0,0,0)\n"
        "  --dump DIR      frame capture without a window (BMP + .565)\n"
        "  --anim NAME|all animation to capture\n"
        "  --at t0,t1,...  captured times, in ms\n"
        "  --frames N      number of frames spread over the duration\n"
        "  --keys          capture on every key and between the keys\n"
        "  --bench N       renders N frames (writes nothing) and prints the mean time\n"
        "  --no-raw        do not write the raw .565 files\n");
}

bool parseOptions(int argc, char** argv, Options& opt) {
    for (int i = 1; i < argc; i++) {
        const std::string arg = argv[i];
        const bool hasNext = (i + 1 < argc);
        if (arg == "--help" || arg == "-h") { usage(); return false; }
        if (arg == "--iska" && hasNext)        opt.iska = argv[++i];
        else if (arg == "--idle" && hasNext)   opt.idle = argv[++i];
        else if (arg == "--once" && hasNext)   opt.oneShot = argv[++i];
        else if (arg == "--auto" && hasNext)   opt.autoMs = static_cast<uint32_t>(std::atoi(argv[++i]));
        else if (arg == "--dump" && hasNext)   opt.dumpDir = argv[++i];
        else if (arg == "--anim" && hasNext)   opt.anim = argv[++i];
        else if (arg == "--frames" && hasNext) opt.frames = std::atoi(argv[++i]);
        else if (arg == "--keys")              opt.keys = true;
        else if (arg == "--no-raw")            opt.raw = false;
        else if (arg == "--bench" && hasNext)  opt.bench = std::atoi(argv[++i]);
        else if (arg == "--at" && hasNext) {
            const char* p = argv[++i];
            while (*p) {
                opt.at.push_back(static_cast<uint32_t>(std::atoi(p)));
                const char* comma = std::strchr(p, ',');
                if (!comma) break;
                p = comma + 1;
            }
        } else if (arg == "--bg" && hasNext) {
            unsigned r = 0, g = 0, b = 0;
            if (std::sscanf(argv[++i], "%u,%u,%u", &r, &g, &b) == 3) {
                opt.background = static_cast<uint16_t>(((r & 0xF8u) << 8) |
                                                       ((g & 0xFCu) << 3) | (b >> 3));
            }
        } else {
            std::fprintf(stderr, "unknown option: %s (see --help)\n", arg.c_str());
            return false;
        }
    }
    return true;
}

/** FNV-1a 64-bit: same computation in tools/iska_clip_check.py. */
uint64_t fnv1a(const uint16_t* pixels, size_t count) {
    uint64_t hash = 1469598103934665603ull;
    for (size_t i = 0; i < count; i++) {
        hash ^= static_cast<uint64_t>(pixels[i] & 0xFFu);
        hash *= 1099511628211ull;
        hash ^= static_cast<uint64_t>((pixels[i] >> 8) & 0xFFu);
        hash *= 1099511628211ull;
    }
    return hash;
}

/** 24-bit BMP (rows from the bottom up, as the format requires). */
bool writeBmp(const char* path, const uint16_t* pixels, int width, int height) {
    const int rowBytes  = width * 3;
    const int padding   = (4 - (rowBytes % 4)) % 4;
    const int dataBytes = (rowBytes + padding) * height;
    const int fileBytes = 54 + dataBytes;

    std::FILE* file = std::fopen(path, "wb");
    if (!file) return false;
    uint8_t header[54] = {0};
    header[0] = 'B';
    header[1] = 'M';
    const uint32_t sizes[3] = {static_cast<uint32_t>(fileBytes), 0u,
                               static_cast<uint32_t>(54)};
    std::memcpy(header + 2, sizes, 12);
    header[14] = 40;                                   // BITMAPINFOHEADER
    const int32_t info[4] = {static_cast<int32_t>(width), static_cast<int32_t>(height),
                             1, 24};
    std::memcpy(header + 18, info, 16);
    std::fwrite(header, 1, 54, file);

    std::vector<uint8_t> row(static_cast<size_t>(rowBytes + padding), 0);
    for (int y = height - 1; y >= 0; y--) {
        for (int x = 0; x < width; x++) {
            const uint16_t c = pixels[static_cast<size_t>(y) * width + x];
            row[static_cast<size_t>(x) * 3 + 0] = static_cast<uint8_t>((c & 0x1F) * 255 / 31);
            row[static_cast<size_t>(x) * 3 + 1] = static_cast<uint8_t>(((c >> 5) & 0x3F) * 255 / 63);
            row[static_cast<size_t>(x) * 3 + 2] = static_cast<uint8_t>(((c >> 11) & 0x1F) * 255 / 31);
        }
        std::fwrite(row.data(), 1, row.size(), file);
    }
    std::fclose(file);
    return true;
}


std::vector<uint32_t> dumpTimes(const Iska::Animation& anim, const Options& opt,
                                const std::vector<uint32_t>& explicitTimes) {
    if (!explicitTimes.empty()) return explicitTimes;
    std::vector<uint32_t> times;
    if (opt.keys) {
        for (size_t i = 0; i < anim.keys.size(); i++) {
            times.push_back(anim.keys[i].tMs);
            if (i + 1 < anim.keys.size()) {   // the middle, to see the interpolation
                times.push_back((anim.keys[i].tMs + anim.keys[i + 1].tMs) / 2);
            }
        }
        return times;
    }
    const int count = (opt.frames > 0) ? opt.frames : 6;
    for (int i = 0; i < count; i++) {
        times.push_back(static_cast<uint32_t>(
            static_cast<double>(anim.durationMs) * i / (count > 1 ? count - 1 : 1)));
    }
    return times;
}

int dumpFrames(const Iska::Asset& asset, const Options& opt) {
    Iska::Player player;
    if (!player.bind(&asset)) {
        std::fprintf(stderr, "asset without a bone: nothing to draw\n");
        return 1;
    }
    std::error_code ec;
    std::filesystem::create_directories(opt.dumpDir, ec);   // the directory may not exist
    const int width  = player.stageWidth();
    const int height = player.stageHeight();
    std::vector<uint16_t> frame(static_cast<size_t>(width) * height);

    int written = 0;
    for (const Iska::Animation& anim : asset.animations) {
        if (!opt.anim.empty() && opt.anim != "all" && opt.anim != anim.name) continue;
        // `--at` applies to the animation named by --anim, or to the first one
        // in the file when --anim is absent.
        std::vector<uint32_t> explicitTimes;
        if (!opt.at.empty() &&
            (opt.anim == anim.name ||
             (opt.anim.empty() && &anim == &asset.animations.front()))) {
            explicitTimes = opt.at;
        }
        const std::vector<uint32_t> times = dumpTimes(anim, opt, explicitTimes);
        player.play(anim.name.c_str(), true);
        for (uint32_t t : times) {
            player.setTime(t);
            player.render(frame.data(), opt.background);
            char stem[512];
            std::snprintf(stem, sizeof(stem), "%s/%s_%05u", opt.dumpDir.c_str(),
                          anim.name.c_str(), t);
            char path[600];
            std::snprintf(path, sizeof(path), "%s.bmp", stem);
            if (!writeBmp(path, frame.data(), width, height)) {
                std::fprintf(stderr, "cannot write: %s\n", path);
                return 1;
            }
            if (opt.raw) {
                std::snprintf(path, sizeof(path), "%s.565", stem);
                std::FILE* file = std::fopen(path, "wb");
                if (file) {
                    std::fwrite(frame.data(), sizeof(uint16_t), frame.size(), file);
                    std::fclose(file);
                }
            }
            std::printf("[dump] %-10s t=%5u ms  fnv1a=%016llx\n", anim.name.c_str(), t,
                        static_cast<unsigned long long>(
                            fnv1a(frame.data(), frame.size())));
            written++;
        }
    }
    std::printf("[dump] %d image(s) -> %s\n", written, opt.dumpDir.c_str());
    return written > 0 ? 0 : 1;
}


/** Display loop: 240x320 panel on the simulator's SDL screen. */
int runWindow(const Iska::Asset& asset, const Options& opt) {
    Iska::Player player;
    if (!player.bind(&asset)) {
        std::fprintf(stderr, "asset without a bone: nothing to display\n");
        return 1;
    }
    std::string idleName = opt.idle;
    if (idleName.empty()) {
        for (const Iska::Animation& anim : asset.animations) {
            if (anim.loop) { idleName = anim.name; break; }
        }
        if (idleName.empty()) idleName = asset.animations.front().name;
    }
    if (!asset.find(idleName.c_str())) {
        std::fprintf(stderr, "unknown background animation: %s\n", idleName.c_str());
        return 1;
    }
    const bool hasOneShot = !opt.oneShot.empty() && asset.find(opt.oneShot.c_str()) != nullptr;

    // the panel is chosen BEFORE initLCD (the geometry is frozen at init)
    Drivers::setPanelSize(player.stageWidth(), player.stageHeight());
    Drivers::initLCD(0, 0, 0, 0);
    if (!Drivers::tftTouchSubsystemReady()) {
        std::fprintf(stderr, "screen unavailable (SDL): nothing to display\n");
        return 1;
    }

    std::vector<uint16_t> frame(static_cast<size_t>(player.stageWidth()) * player.stageHeight());
    player.play(idleName.c_str(), true);
    bool     oneShotActive = false;
    bool     wasTouching   = false;
    uint32_t autoAccumMs   = 0;
    auto last = std::chrono::steady_clock::now();

    std::printf("[demo] %s -- background=%s%s%s -- click to play %s, ESC to quit\n",
                opt.iska.c_str(), idleName.c_str(),
                opt.autoMs ? " (auto " : "", opt.autoMs ? std::to_string(opt.autoMs).c_str() : "",
                hasOneShot ? opt.oneShot.c_str() : "(none)");

    while (Drivers::pumpEvents()) {
        const auto now = std::chrono::steady_clock::now();
        const uint32_t dtMs = static_cast<uint32_t>(
            std::chrono::duration_cast<std::chrono::milliseconds>(now - last).count());
        last = now;

        int16_t  touchX = 0, touchY = 0;
        const bool touching = hasOneShot && Drivers::getIli9341TouchScreenPos(&touchX, &touchY);
        const bool triggered = (touching && !wasTouching) ||   // rising edge of the click
                               (opt.autoMs > 0 &&
                                (autoAccumMs += dtMs) >= opt.autoMs);
        wasTouching = touching;
        if (triggered) {
            if (opt.autoMs > 0) autoAccumMs = 0;
            player.play(opt.oneShot.c_str(), true);
            oneShotActive = true;
        }

        if (oneShotActive && player.finished()) {
            player.play(idleName.c_str(), true);   // back to the loop
            oneShotActive = false;
        }

        player.update(dtMs);
        player.render(frame.data(), opt.background);
        Drivers::pushScreen565(frame.data());
    }
    return 0;
}

/** Measures the pure rendering cost (nothing written, no SDL). */
int bench(const Iska::Asset& asset, const Options& opt) {
    Iska::Player player;
    if (!player.bind(&asset)) return 1;
    const int animations = static_cast<int>(asset.animations.size());
    std::vector<uint16_t> frame(static_cast<size_t>(player.stageWidth()) * player.stageHeight());
    const int count = opt.bench > 0 ? opt.bench : 200;

    const auto start = std::chrono::steady_clock::now();
    for (int i = 0; i < count; i++) {
        const Iska::Animation& anim = asset.animations[static_cast<size_t>(i) % animations];
        player.playIndex(static_cast<size_t>(i) % animations, false);
        player.setTime(anim.durationMs > 0 ? (i * 7u) % anim.durationMs : 0u);
        player.render(frame.data(), opt.background);
    }
    const auto elapsed = std::chrono::duration_cast<std::chrono::microseconds>(
        std::chrono::steady_clock::now() - start).count();

    std::printf("[bench] %d images %dx%d in %.1f ms => %.2f ms/image "
                "(%.0f images/s), %.2f M pixels/s\n",
                count, player.stageWidth(), player.stageHeight(), elapsed / 1000.0,
                elapsed / 1000.0 / count,
                count * 1000.0 / (elapsed / 1000.0),
                (count * player.stageWidth() * player.stageHeight()) / (double)elapsed);
    return 0;
}

}  // namespace

int main(int argc, char** argv) {
    Options opt;
    if (!parseOptions(argc, argv, opt)) return 2;

    Iska::Asset asset;
    std::string error;
    if (!Iska::loadAsset(opt.iska.c_str(), asset, &error)) {
        std::fprintf(stderr, "cannot load (%s): %s\n", opt.iska.c_str(),
                     error.c_str());
        return 1;
    }
    std::printf("[demo] %s\n", Iska::describe(asset).c_str());

    if (opt.bench > 0) return bench(asset, opt);
    if (!opt.dumpDir.empty()) return dumpFrames(asset, opt);
    return runWindow(asset, opt);
}


