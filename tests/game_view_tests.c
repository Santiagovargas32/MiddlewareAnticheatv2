#include "lab/game/view.h"
#include <stdio.h>
#include <string.h>
#define CHECK(x) do { if (!(x)) { fprintf(stderr, "%d: %s\n", __LINE__, #x); return 1; } } while (0)

int main(void) {
    /* Independent LGST/1 fixture, two players, negative x=-10000 for player 0. */
    const uint8_t fixture[80] = {
        'L','G','S','T',1,0,0,1, 5,0,0,0,0,0,0,0, 2,0,0,0,
        1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,
        2,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,
        0xf0,0xd8,0xff,0xff,0,0,0,0,100,4,0,0,
        0xf4,1,0,0,0,0,0,0,75,3,1,0,3,0,0,0
    };
    uint8_t bytes[85] = {0}; memcpy(bytes + 1, fixture, 80);
    game_view_t view = {0};
    CHECK(game_view_decode(bytes + 1, 80, &view));
    CHECK(view.players[0].x_mm == -10000 && view.players[1].x_mm == 500 &&
          view.players[0].health == 100 && view.players[1].ammo == 3 &&
          view.players[0].open && view.players[1].open && view.tick == 5 && view.sequence == 2);
    game_view_t before = view;
    for (size_t n = 0; n <= 84; ++n) if (n != 80) {
        CHECK(!game_view_decode(bytes + 1, n, &view));
        CHECK(!memcmp(&view, &before, sizeof view));
    }
    const size_t offsets[] = {0,4,5,6,7,20,36,52,60,61,62,63,76,77,78,79};
    const uint8_t values[] = {0,2,255,2,2,0,0,0xef,101,5,5,2,4,1,1,1};
    for (size_t i = 0; i < sizeof offsets / sizeof offsets[0]; ++i) {
        memcpy(bytes + 1, fixture, 80); bytes[1 + offsets[i]] = values[i];
        CHECK(!game_view_decode(bytes + 1, 80, &view));
        CHECK(!memcmp(&view, &before, sizeof view));
    }
    CHECK(!game_view_decode(NULL, 80, &view) && !game_view_decode(fixture, 80, NULL));
    uint32_t random = 7;
    for (unsigned i = 0; i < 20000; ++i) {
        memcpy(bytes + 1, fixture, 80);
        random = random * UINT32_C(1664525) + UINT32_C(1013904223);
        bytes[1 + random % 80] ^= (uint8_t)(random >> 24);
        view = before;
        if (!game_view_decode(bytes + 1, 80, &view)) CHECK(!memcmp(&view, &before, sizeof view));
        else CHECK(view.slot < 2 && view.players[0].x_mm >= -10000 && view.players[0].x_mm <= 10000);
    }
    puts("PASS: independent state fixture, signed positions, unaligned lengths, versions, ranges, atomic rejection, 20000 mutations");
    return 0;
}
