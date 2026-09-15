#ifndef LAB_GAME_VIEW_H
#define LAB_GAME_VIEW_H
#include "game.h"

typedef struct {
    uint8_t match[16], session[16], slot, result;
    uint32_t sequence;
    uint64_t tick;
    struct {
        int32_t x_mm, y_mm;
        uint8_t health, ammo, hits, kills;
        bool open;
    } players[GAME_PLAYERS];
} game_view_t;

/* Decode LGST/1 from the existing C worker. Output untouched on failure. */
bool game_view_decode(const uint8_t *bytes, size_t size, game_view_t *out);
#endif
