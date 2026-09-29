/**
 * Demo Intellar-Engine-Animation : joue `assets/rabbit3.iska` sur l'ecran
 * simule (SDL2) du repertoire Intellar-Engine-Simulator.
 *
 * Deux modes :
 *
 *  1. **Fenetre** (defaut) : panneau 240x320 (le setup portrait reel), l'ecran
 *     affiche la boucle d'inactivite ; un clic (tactile simule) declenche
 *     l'animation one-shot, puis on revient a la boucle.
 *
 *         intellar_anim_demo --iska assets/rabbit3.iska
 *         intellar_anim_demo --iska assets/rabbit3.iska --auto 5000
 *
 *  2. **Capture** (`--dump DIR`) : aucune fenetre, aucun SDL. Rend les images
 *     dans des BMP (+ fichiers .565 bruts) : c'est le mode qui sert a verifier
 *     le rendu sans ecran, et a le comparer a `tools/iska_preview.py`.
 *
 *         intellar_anim_demo --iska assets/rabbit3.iska --dump build/frames \
 *             --anim all --keys
 *
 * Chaque image capturee est accompagnee d'une empreinte FNV-1a : la meme
 * empreinte est calculee cote Python (`tools/iska_clip_check.py`), ce qui permet
 * de prouver que les deux rendus sont identiques au pixel pres.
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
    std::string idle      = "";        // animation de fond (defaut : la 1ere boucle)
    std::string oneShot   = "peek";    // animation declenchee par un clic
    std::string dumpDir   = "";        // mode capture (sans fenetre)
    std::string anim      = "";        // animation a capturer ("all" = toutes)
    std::vector<uint32_t> at;          // instants explicites (ms)
    int         frames    = 0;         // images reparties (si --at absent)
    bool        keys      = false;     // capturer aux cles (+ milieux)
    bool        raw       = true;      // ecrire aussi les .565 bruts
    uint32_t    autoMs    = 0;         // one-shot periodique (fenetre)
    int         bench     = 0;         // --bench N : N images rendues sans ecriture
    uint16_t    background = 0x0000;
};

void usage() {
    std::printf(
        "intellar_anim_demo --iska FICHIER [options]\n"
        "  --idle NOM      animation de fond (defaut : la premiere en boucle)\n"
        "  --once NOM      animation jouee sur clic (defaut : peek)\n"
        "  --auto MS       rejoue le one-shot toutes les MS ms (0 = jamais)\n"
        "  --bg R,G,B      couleur de fond (defaut 0,0,0)\n"
        "  --dump DIR      capture d'images sans fenetre (BMP + .565)\n"
        "  --anim NOM|all  animation a capturer\n"
        "  --at t0,t1,...  instants captures en ms\n"
        "  --frames N      nombre d'images reparties sur la duree\n"
        "  --keys          capturer a chaque cle et entre les cles\n"
        "  --bench N       rend N images (sans rien ecrire) et affiche le temps moyen\n"
        "  --no-raw        ne pas ecrire les .565 bruts\n");
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
            std::fprintf(stderr, "option inconnue : %s (--help pour l'aide)\n", arg.c_str());
            return false;
        }
    }
    return true;
}

/** FNV-1a 64 bits : meme calcul dans tools/iska_clip_check.py. */
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

/** BMP 24 bits (lignes du bas vers le haut, comme le veut le format). */
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
            if (i + 1 < anim.keys.size()) {   // le milieu, pour voir l'interpolation
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
        std::fprintf(stderr, "asset sans os : rien a dessiner\n");
        return 1;
    }
    std::error_code ec;
    std::filesystem::create_directories(opt.dumpDir, ec);   // le dossier peut ne pas exister
    const int width  = player.stageWidth();
    const int height = player.stageHeight();
    std::vector<uint16_t> frame(static_cast<size_t>(width) * height);

    int written = 0;
    for (const Iska::Animation& anim : asset.animations) {
        if (!opt.anim.empty() && opt.anim != "all" && opt.anim != anim.name) continue;
        // `--at` s'applique a l'animation nommee par --anim, ou a la premiere du
        // fichier si --anim est absent.
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
                std::fprintf(stderr, "ecriture impossible : %s\n", path);
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


/** Boucle d'affichage : panneau 240x320 sur l'ecran SDL du simulateur. */
int runWindow(const Iska::Asset& asset, const Options& opt) {
    Iska::Player player;
    if (!player.bind(&asset)) {
        std::fprintf(stderr, "asset sans os : rien a afficher\n");
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
        std::fprintf(stderr, "animation de fond inconnue : %s\n", idleName.c_str());
        return 1;
    }
    const bool hasOneShot = !opt.oneShot.empty() && asset.find(opt.oneShot.c_str()) != nullptr;

    // le panneau est choisi AVANT initLCD (geometrie figee a l'initialisation)
    Drivers::setPanelSize(player.stageWidth(), player.stageHeight());
    Drivers::initLCD(0, 0, 0, 0);
    if (!Drivers::tftTouchSubsystemReady()) {
        std::fprintf(stderr, "ecran indisponible (SDL) : rien a afficher\n");
        return 1;
    }

    std::vector<uint16_t> frame(static_cast<size_t>(player.stageWidth()) * player.stageHeight());
    player.play(idleName.c_str(), true);
    bool     oneShotActive = false;
    bool     wasTouching   = false;
    uint32_t autoAccumMs   = 0;
    auto last = std::chrono::steady_clock::now();

    std::printf("[demo] %s — fond=%s%s%s — clic pour jouer %s, ECHAP pour quitter\n",
                opt.iska.c_str(), idleName.c_str(),
                opt.autoMs ? " (auto " : "", opt.autoMs ? std::to_string(opt.autoMs).c_str() : "",
                hasOneShot ? opt.oneShot.c_str() : "(aucune)");

    while (Drivers::pumpEvents()) {
        const auto now = std::chrono::steady_clock::now();
        const uint32_t dtMs = static_cast<uint32_t>(
            std::chrono::duration_cast<std::chrono::milliseconds>(now - last).count());
        last = now;

        int16_t  touchX = 0, touchY = 0;
        const bool touching = hasOneShot && Drivers::getIli9341TouchScreenPos(&touchX, &touchY);
        const bool triggered = (touching && !wasTouching) ||   // front montant du clic
                               (opt.autoMs > 0 &&
                                (autoAccumMs += dtMs) >= opt.autoMs);
        wasTouching = touching;
        if (triggered) {
            if (opt.autoMs > 0) autoAccumMs = 0;
            player.play(opt.oneShot.c_str(), true);
            oneShotActive = true;
        }

        if (oneShotActive && player.finished()) {
            player.play(idleName.c_str(), true);   // retour a la boucle
            oneShotActive = false;
        }

        player.update(dtMs);
        player.render(frame.data(), opt.background);
        Drivers::pushScreen565(frame.data());
    }
    return 0;
}

/** Mesure le cout de rendu pur (aucune ecriture, aucun SDL). */
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

    std::printf("[bench] %d images %dx%d en %.1f ms => %.2f ms/image "
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
        std::fprintf(stderr, "chargement impossible (%s) : %s\n", opt.iska.c_str(),
                     error.c_str());
        return 1;
    }
    std::printf("[demo] %s\n", Iska::describe(asset).c_str());

    if (opt.bench > 0) return bench(asset, opt);
    if (!opt.dumpDir.empty()) return dumpFrames(asset, opt);
    return runWindow(asset, opt);
}


