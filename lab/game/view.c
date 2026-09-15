#include "view.h"
#include <string.h>

static uint64_t read_le(const uint8_t *bytes, unsigned count) {
    uint64_t result = 0;
    for (unsigned i = 0; i < count; ++i) result |= (uint64_t)bytes[i] << (8u * i);
    return result;
}

static int32_t signed32(const uint8_t *bytes) {
    uint32_t raw = (uint32_t)read_le(bytes, 4);
    return raw <= INT32_MAX ? (int32_t)raw : (int32_t)((int64_t)raw - INT64_C(4294967296));
}

bool game_view_decode(const uint8_t *bytes, size_t size, game_view_t *out) {
    if (!bytes || !out || size != 80 || memcmp(bytes, "LGST\1", 5) ||
        bytes[5] > GAME_CLOCK_EXHAUSTED || bytes[6] >= GAME_PLAYERS || bytes[7] != 1 ||
        bytes[76] > 3 || bytes[77] || bytes[78] || bytes[79]) return false;
    game_view_t view = {0};
    view.slot = bytes[6]; view.result = bytes[5];
    view.sequence = (uint32_t)read_le(bytes + 16, 4);
    view.tick = read_le(bytes + 8, 8);
    memcpy(view.match, bytes + 20, 16); memcpy(view.session, bytes + 36, 16);
    unsigned match = 0, session = 0;
    for (size_t i = 0; i < 16; ++i) { match |= view.match[i]; session |= view.session[i]; }
    if (!match || !session) return false;
    for (unsigned i = 0; i < GAME_PLAYERS; ++i) {
        const uint8_t *p = bytes + 52 + 12 * i;
        view.players[i].x_mm = signed32(p); view.players[i].y_mm = signed32(p + 4);
        view.players[i].health = p[8]; view.players[i].ammo = p[9];
        view.players[i].hits = p[10]; view.players[i].kills = p[11];
        view.players[i].open = (bytes[76] & (1u << i)) != 0;
        if (view.players[i].x_mm < -GAME_EDGE_MM || view.players[i].x_mm > GAME_EDGE_MM ||
            view.players[i].y_mm < -GAME_EDGE_MM || view.players[i].y_mm > GAME_EDGE_MM ||
            p[8] > GAME_HEALTH || p[9] > GAME_AMMO || p[10] > GAME_AMMO || p[11] > 1) return false;
    }
    *out = view;
    return true;
}
