#include "IskaLoader.h"

#include <cstdio>
#include <cstring>

namespace Iska {
namespace {

/** CRC32 (IEEE, celui de zlib) : meme controle que cote Python. */
uint32_t crc32Of(const uint8_t* data, size_t size) {
    static uint32_t table[256];
    static bool     ready = false;
    if (!ready) {
        for (uint32_t i = 0; i < 256; i++) {
            uint32_t c = i;
            for (int k = 0; k < 8; k++) c = (c & 1u) ? (0xEDB88320u ^ (c >> 1)) : (c >> 1);
            table[i] = c;
        }
        ready = true;
    }
    uint32_t crc = 0xFFFFFFFFu;
    for (size_t i = 0; i < size; i++) crc = table[(crc ^ data[i]) & 0xFFu] ^ (crc >> 8);
    return crc ^ 0xFFFFFFFFu;
}

bool fail(std::string* error, const std::string& message) {
    if (error) *error = message;
    return false;
}

}  // namespace

const Animation* Asset::find(const char* name) const {
    if (!name) return nullptr;
    for (const Animation& anim : animations) {
        if (anim.name == name) return &anim;
    }
    return nullptr;
}

bool parseAsset(const uint8_t* data, size_t size, Asset& out, std::string* error) {
    out = Asset{};
    if (!data || size < kHeaderBytes) return fail(error, "fichier trop petit");
    if (std::memcmp(data, kMagic, 4) != 0) return fail(error, "ce n'est pas un fichier ISKA");

    const uint16_t version     = readU16(data + 4);
    const uint16_t headerBytes = readU16(data + 6);
    const uint16_t stageW      = readU16(data + 8);
    const uint16_t stageH      = readU16(data + 10);
    const uint16_t boneCount   = readU16(data + 12);
    const uint16_t partCount   = readU16(data + 14);
    const uint16_t animCount   = readU16(data + 16);
    const uint32_t pixelBytes  = readU32(data + 20);
    const uint32_t pixelCount  = readU32(data + 24);
    const uint32_t pixelCrc    = readU32(data + 28);

    if (version != kFormatVersion) {
        return fail(error, "version ISKA " + std::to_string(version) + " non geree");
    }
    if (headerBytes != kHeaderBytes) return fail(error, "en-tete de taille inattendue");
    if (stageW == 0 || stageH == 0) return fail(error, "panneau de taille nulle");

    size_t offset = headerBytes;
    if (size < offset + boneCount * kBoneBytes) return fail(error, "bloc d'os tronque");
    out.bones.resize(boneCount);
    for (uint16_t i = 0; i < boneCount; i++) {
        Bone& bone     = out.bones[i];
        bone.parent    = readI16(data + offset);
        bone.restX     = readI16(data + offset + 2);
        bone.restY     = readI16(data + offset + 4);
        bone.angle     = readI16(data + offset + 6) / kAngleScale;
        offset        += kBoneBytes;
        if (bone.parent >= static_cast<int16_t>(i)) {
            return fail(error, "os " + std::to_string(i) + " : parent non anterieur");
        }
    }

    if (size < offset + partCount * kPartBytes) return fail(error, "bloc de parts tronque");
    out.parts.resize(partCount);
    for (uint16_t i = 0; i < partCount; i++) {
        Part& part        = out.parts[i];
        part.bone         = readI16(data + offset);
        part.pivotX       = readI16(data + offset + 2);
        part.pivotY       = readI16(data + offset + 4);
        part.width        = readU16(data + offset + 6);
        part.height       = readU16(data + offset + 8);
        part.drawOrder    = readU16(data + offset + 10);
        part.flags        = readU16(data + offset + 12);
        part.pixelOffset  = readU32(data + offset + 18);
        part.pixelCount   = readU32(data + offset + 22) / 2;
        offset           += kPartBytes;
        if (part.bone >= static_cast<int16_t>(boneCount)) {
            return fail(error, "part " + std::to_string(i) + " : os hors limites");
        }
        if (part.pixelOffset / 2 + part.pixelCount > pixelCount) {
            return fail(error, "part " + std::to_string(i) + " : pixels hors limites");
        }
    }
    // ordre de dessin croissant (le moteur dessine dans l'ordre du fichier, mais
    // on verifie l'invariant pour attraper un asset bricole a la main)
    for (uint16_t i = 1; i < partCount; i++) {
        if (out.parts[i].drawOrder < out.parts[i - 1].drawOrder) {
            return fail(error, "parts non triees par ordre de dessin");
        }
    }

    out.animations.resize(animCount);
    for (uint16_t a = 0; a < animCount; a++) {
        if (size < offset + 2) return fail(error, "bloc d'animations tronque");
        const uint16_t nameLen = readU16(data + offset);
        offset += 2;
        if (size < offset + nameLen + 8) return fail(error, "bloc d'animations tronque");
        Animation& anim = out.animations[a];
        anim.name.assign(reinterpret_cast<const char*>(data + offset), nameLen);
        offset += nameLen;
        const uint16_t flags      = readU16(data + offset);
        const uint16_t keyCount   = readU16(data + offset + 2);
        anim.durationMs           = readU32(data + offset + 4);
        anim.loop                 = (flags & kAnimFlagLoop) != 0;
        offset                   += 8;
        if (keyCount == 0) return fail(error, "animation " + anim.name + " sans cle");

        const size_t keyBytes = 2 + static_cast<size_t>(boneCount) * kKeyPoseBytes;
        if (size < offset + keyBytes * keyCount) return fail(error, "cles tronquees");
        anim.keys.resize(keyCount);
        for (uint16_t k = 0; k < keyCount; k++) {
            Key& key  = anim.keys[k];
            key.tMs   = readU16(data + offset);
            offset   += 2;
            key.pose.resize(static_cast<size_t>(boneCount) * 5);
            for (uint16_t b = 0; b < boneCount; b++) {
                for (int v = 0; v < 5; v++) {
                    key.pose[static_cast<size_t>(b) * 5 + v] = readI16(data + offset);
                    offset += 2;
                }
            }
            if (k > 0 && key.tMs < anim.keys[k - 1].tMs) {
                return fail(error, "animation " + anim.name + " : cles non ordonnees");
            }
        }
    }

    if (size < offset + pixelBytes) return fail(error, "bloc de pixels tronque");
    if (crc32Of(data + offset, pixelBytes) != pixelCrc) {
        return fail(error, "CRC du bloc de pixels invalide");
    }
    out.pixels.resize(pixelCount);
    if (pixelBytes == pixelCount * 2) {
        std::memcpy(out.pixels.data(), data + offset, pixelBytes);
    } else {
        for (uint32_t i = 0; i < pixelCount; i++) {
            out.pixels[i] = readU16(data + offset + i * 2);
        }
    }

    out.stageW    = stageW;
    out.stageH    = stageH;
    out.fileBytes = size;
    return true;
}

bool loadAsset(const char* path, Asset& out, std::string* error) {
    std::FILE* file = std::fopen(path, "rb");
    if (!file) return fail(error, std::string("ouverture impossible : ") + path);
    std::fseek(file, 0, SEEK_END);
    const long length = std::ftell(file);
    std::fseek(file, 0, SEEK_SET);
    if (length <= 0) {
        std::fclose(file);
        return fail(error, std::string("fichier vide : ") + path);
    }
    std::vector<uint8_t> buffer(static_cast<size_t>(length));
    const size_t read = std::fread(buffer.data(), 1, buffer.size(), file);
    std::fclose(file);
    if (read != buffer.size()) return fail(error, std::string("lecture incomplete : ") + path);
    return parseAsset(buffer.data(), buffer.size(), out, error);
}

std::string describe(const Asset& asset) {
    std::string text = "ISKA " + std::to_string(asset.stageW) + "x" +
                       std::to_string(asset.stageH) + " : " +
                       std::to_string(asset.bones.size()) + " os, " +
                       std::to_string(asset.parts.size()) + " parts, " +
                       std::to_string(asset.animations.size()) + " animations, " +
                       std::to_string(asset.fileBytes) + " o";
    for (const Animation& anim : asset.animations) {
        text += "\n  " + anim.name + " : " + std::to_string(anim.durationMs) +
                " ms, " + std::to_string(anim.keys.size()) + " cles, " +
                (anim.loop ? "boucle" : "one-shot");
    }
    return text;
}

}  // namespace Iska
