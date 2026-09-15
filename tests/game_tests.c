#include "lab/game/game.h"

#include <stdio.h>
#include <string.h>

#define CHECK(x) do { if (!(x)) { fprintf(stderr, "%s:%d: %s\n", __FILE__, __LINE__, #x); return false; } } while (0)

static game_world_t fresh(void) {
    /* Test identities only. Production caller must supply fresh entropy. */
    const uint8_t match[16] = {1}, a[16] = {2}, b[16] = {3};
    game_world_t world = {0};
    (void)game_init(&world, match, a, b);
    return world;
}

static game_input_t input(const game_world_t *world, size_t slot, uint32_t seq,
                          uint8_t action, uint8_t x, uint8_t y) {
    game_input_t in = { .sequence = seq, .action = action, .axis_x = x, .axis_y = y };
    memcpy(in.match, world->match, 16);
    memcpy(in.session, world->players[slot].session, 16);
    return in;
}

static bool reject(game_world_t *world, size_t slot, game_input_t in, game_result_t reason) {
    game_world_t before = *world;
    CHECK(game_apply(world, slot, &in) == reason);
    CHECK(!memcmp(&before, world, sizeof before));
    return true;
}

static bool advance(game_world_t *world, unsigned ticks) {
    for (unsigned i = 0; i < ticks; ++i) CHECK(game_advance(world) == GAME_OK);
    return true;
}

static bool codec(void) {
    /* Independent literal fixture: MOVE west, sequence 0x12345678 LE. */
    const uint8_t fixture[48] = {
        0x4c,0x47,0x49,0x4e,1,1,1,0,
        1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,
        2,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,
        0x78,0x56,0x34,0x12,0,0,0,0
    };
    uint8_t wire[128] = {0};
    memcpy(wire + 1, fixture, sizeof fixture);
    game_input_t out = {0};
    CHECK(game_input_decode(wire + 1, sizeof fixture, &out));
    CHECK(out.sequence == UINT32_C(0x12345678) && out.action == GAME_MOVE &&
          out.axis_x == GAME_AXIS_NEG && !out.axis_y && out.match[0] == 1 && out.session[0] == 2);
    uint8_t encoded[50]; memset(encoded, 0xa5, sizeof encoded);
    CHECK(game_input_encode(encoded + 1, 48, &out));
    CHECK(encoded[0] == 0xa5 && encoded[49] == 0xa5 && !memcmp(encoded + 1, fixture, 48));
    game_input_t before = out;
    for (size_t n = 0; n < 127; ++n) if (n != 48) {
        CHECK(!game_input_decode(wire + 1, n, &out));
        CHECK(!memcmp(&out, &before, sizeof out));
    }
    /* Reject incompatible version, all reserved fields, axes, action and absent IDs. */
    const size_t offsets[] = {0,4,5,6,7,8,24,44,45,46,47};
    const uint8_t values[] = {0,2,9,3,1,0,0,1,1,1,1};
    for (size_t i = 0; i < sizeof offsets / sizeof offsets[0]; ++i) {
        memcpy(wire + 1, fixture, 48); wire[1 + offsets[i]] = values[i];
        CHECK(!game_input_decode(wire + 1, 48, &out));
        CHECK(!memcmp(&out, &before, sizeof out));
    }
    memcpy(wire + 1, fixture, 48); memset(wire + 41, 0, 4);
    CHECK(!game_input_decode(wire + 1, 48, &out));
    out = before; out.action = GAME_FIRE;
    uint8_t untouched[50]; memcpy(untouched, encoded, sizeof encoded);
    CHECK(!game_input_encode(encoded + 1, 48, &out));
    CHECK(!memcmp(encoded, untouched, sizeof encoded));
    CHECK(!game_input_decode(NULL, 48, &out) && !game_input_decode(fixture, 48, NULL));
    CHECK(!game_input_encode(NULL, 48, &before) && !game_input_encode(encoded, 48, NULL));
    return true;
}

static bool isolation(void) {
    game_world_t world = fresh(), before = world;
    uint8_t zero[16] = {0};
    CHECK(!game_init(&world, zero, before.players[0].session, before.players[1].session));
    CHECK(!memcmp(&world, &before, sizeof world));
    CHECK(!game_init(&world, before.match, before.players[0].session, before.players[0].session));
    CHECK(!memcmp(&world, &before, sizeof world));
    game_input_t in = input(&world, 0, 1, GAME_WAIT, 0, 0);
    CHECK(reject(&world, 1, in, GAME_WRONG_SESSION));
    CHECK(reject(&world, GAME_PLAYERS, in, GAME_BAD_INPUT));
    in.match[1] = 1;
    CHECK(reject(&world, 0, in, GAME_WRONG_MATCH));
    in.match[1] = 0;
    CHECK(game_apply(&world, 0, &in) == GAME_OK);
    in = input(&world, 1, 1, GAME_WAIT, 0, 0);
    CHECK(game_apply(&world, 1, &in) == GAME_OK);
    CHECK(world.players[0].last_sequence == 1 && world.players[1].last_sequence == 1);
    CHECK(game_close(&world, 0) == GAME_OK && game_close(&world, 0) == GAME_OK);
    in = input(&world, 0, 2, GAME_WAIT, 0, 0);
    CHECK(reject(&world, 0, in, GAME_CLOSED));
    CHECK(world.players[1].open);
    return true;
}

static bool movement(void) {
    game_world_t world = fresh();
    game_input_t in = input(&world, 0, 1, GAME_MOVE, GAME_AXIS_NEG, 0);
    CHECK(game_apply(&world, 0, &in) == GAME_OK && world.players[0].x_mm == -100);
    in.sequence = 2;
    CHECK(reject(&world, 0, in, GAME_TICK_USED));
    CHECK(advance(&world, 200)); /* Idle time grants no accumulated movement credit. */
    CHECK(game_apply(&world, 0, &in) == GAME_OK && world.players[0].x_mm == -200);
    for (uint32_t seq = 3; seq <= 100; ++seq) {
        CHECK(advance(&world, 1)); in.sequence = seq;
        CHECK(game_apply(&world, 0, &in) == GAME_OK);
    }
    CHECK(world.players[0].x_mm == -10000);
    CHECK(advance(&world, 1)); in.sequence = 101;
    CHECK(reject(&world, 0, in, GAME_WALL));
    in.axis_x = GAME_AXIS_POS;
    CHECK(game_apply(&world, 0, &in) == GAME_OK && world.players[0].x_mm == -9900);
    world = fresh();
    in = input(&world, 0, 1, GAME_MOVE, GAME_AXIS_POS, GAME_AXIS_POS);
    CHECK(reject(&world, 0, in, GAME_BAD_INPUT));
    in.axis_y = 0;
    for (uint32_t seq = 1; seq <= 4; ++seq) {
        in.sequence = seq; CHECK(game_apply(&world, 0, &in) == GAME_OK);
        CHECK(advance(&world, 1));
    }
    in.sequence = 5; CHECK(reject(&world, 0, in, GAME_OCCUPIED));
    in.axis_x = 0; in.axis_y = GAME_AXIS_POS;
    CHECK(game_apply(&world, 0, &in) == GAME_OK && world.players[0].y_mm == 100);
    return true;
}

static bool combat(void) {
    game_world_t world = fresh();
    game_input_t shot = input(&world, 0, 1, GAME_FIRE, 0, 0);
    CHECK(game_apply(&world, 0, &shot) == GAME_OK);
    CHECK(world.players[0].ammo == 3 && world.players[1].health == 75 && world.players[0].hits == 1);
    CHECK(advance(&world, 3)); shot.sequence = 2;
    CHECK(reject(&world, 0, shot, GAME_COOLDOWN));
    CHECK(advance(&world, 1));
    CHECK(game_apply(&world, 0, &shot) == GAME_OK && world.players[1].health == 50);
    for (uint32_t seq = 3; seq <= 4; ++seq) {
        CHECK(advance(&world, 4)); shot.sequence = seq;
        CHECK(game_apply(&world, 0, &shot) == GAME_OK);
    }
    CHECK(world.players[1].health == 0 && world.players[0].ammo == 0 &&
          world.players[0].hits == 4 && world.players[0].kills == 1);
    CHECK(advance(&world, 4)); shot.sequence = 5;
    CHECK(reject(&world, 0, shot, GAME_NO_AMMO));
    game_input_t dead = input(&world, 1, 1, GAME_MOVE, GAME_AXIS_POS, 0);
    CHECK(reject(&world, 1, dead, GAME_DEAD));
    return true;
}

static bool aiming(void) {
    game_world_t world = fresh();
    game_input_t move = input(&world, 0, 1, GAME_MOVE, GAME_AXIS_NEG, 0);
    CHECK(game_apply(&world, 0, &move) == GAME_OK && advance(&world, 1));
    game_input_t shot = input(&world, 0, 2, GAME_FIRE, 0, 0);
    CHECK(game_apply(&world, 0, &shot) == GAME_OK); /* Faces away: no client hit claims. */
    CHECK(world.players[1].health == 100 && world.players[0].hits == 0 && world.players[0].ammo == 3);
    world = fresh();
    move = input(&world, 1, 1, GAME_MOVE, 0, GAME_AXIS_POS);
    CHECK(game_apply(&world, 1, &move) == GAME_OK);
    shot = input(&world, 0, 1, GAME_FIRE, 0, 0);
    CHECK(game_apply(&world, 0, &shot) == GAME_OK && world.players[1].health == 100);
    world = fresh();
    move = input(&world, 1, 1, GAME_MOVE, GAME_AXIS_POS, 0);
    for (uint32_t seq = 1; seq <= 16; ++seq) {
        move.sequence = seq; CHECK(game_apply(&world, 1, &move) == GAME_OK);
        CHECK(advance(&world, 1));
    }
    shot = input(&world, 0, 1, GAME_FIRE, 0, 0);
    CHECK(game_apply(&world, 0, &shot) == GAME_OK && world.players[1].health == 100);
    return true;
}

static bool sequences(void) {
    game_world_t world = fresh();
    game_input_t in = input(&world, 0, 2, GAME_WAIT, 0, 0); /* Lost command 1 is harmless. */
    CHECK(game_apply(&world, 0, &in) == GAME_OK && advance(&world, 1));
    in.sequence = 1; CHECK(reject(&world, 0, in, GAME_REPLAY));
    in.sequence = 2; CHECK(reject(&world, 0, in, GAME_REPLAY));
    in.sequence = 40; CHECK(game_apply(&world, 0, &in) == GAME_OK && advance(&world, 1));
    in.sequence = 3; CHECK(reject(&world, 0, in, GAME_REPLAY));
    in.sequence = UINT32_MAX - 1; CHECK(game_apply(&world, 0, &in) == GAME_OK && advance(&world, 1));
    in.sequence = UINT32_MAX; CHECK(reject(&world, 0, in, GAME_SEQUENCE_EXHAUSTED));
    in.sequence = 1; CHECK(reject(&world, 0, in, GAME_REPLAY));
    in.sequence = 0; CHECK(reject(&world, 0, in, GAME_BAD_INPUT));
    world = fresh(); world.tick = UINT64_MAX - 3;
    in = input(&world, 0, 1, GAME_FIRE, 0, 0);
    CHECK(reject(&world, 0, in, GAME_CLOCK_EXHAUSTED));
    world.tick = UINT64_MAX;
    game_world_t before = world;
    CHECK(game_advance(&world) == GAME_CLOCK_EXHAUSTED && !memcmp(&world, &before, sizeof world));
    return true;
}

static bool fuzz(void) {
    uint32_t seed = 17;
    uint8_t bytes[65];
    for (unsigned i = 0; i < 20000; ++i) {
        for (size_t j = 0; j < sizeof bytes; ++j) {
            seed = seed * UINT32_C(1664525) + UINT32_C(1013904223);
            bytes[j] = (uint8_t)(seed >> 24);
        }
        /* Half the inputs mutate a valid packet: exercise fields past magic/version. */
        size_t length = i % 64;
        if (i % 2 == 0) {
            game_world_t initial = fresh();
            game_input_t base = input(&initial, 0, 1, GAME_MOVE, GAME_AXIS_POS, 0);
            uint8_t change = bytes[2];
            size_t offset = bytes[3] % GAME_INPUT_SIZE;
            CHECK(game_input_encode(bytes + 1, GAME_INPUT_SIZE, &base));
            bytes[1 + offset] ^= change;
            length = GAME_INPUT_SIZE;
        }
        game_input_t output = {0}, before = output;
        if (game_input_decode(bytes + 1, length, &output)) {
            uint8_t encoded[48];
            CHECK(game_input_encode(encoded, sizeof encoded, &output));
            CHECK(!memcmp(bytes + 1, encoded, 48));
        } else CHECK(!memcmp(&output, &before, sizeof output));
        /* State history: alternate malformed, valid and burst/replayed intents. */
        game_world_t world = fresh();
        for (unsigned n = 0; n < 8; ++n) {
            game_input_t in = input(&world, n % 2, bytes[n] + 1u,
                                    (uint8_t)(bytes[n + 1] % 5),
                                    (uint8_t)(bytes[n + 2] % 4), (uint8_t)(bytes[n + 3] % 4));
            game_world_t old = world;
            game_result_t result = game_apply(&world, n % 2, &in);
            if (result != GAME_OK) CHECK(!memcmp(&old, &world, sizeof old));
            for (size_t player = 0; player < 2; ++player) {
                CHECK(world.players[player].ammo <= 4 && world.players[player].health <= 100);
                CHECK(world.players[player].x_mm >= -10000 && world.players[player].x_mm <= 10000);
                CHECK(world.players[player].y_mm >= -10000 && world.players[player].y_mm <= 10000);
            }
            if (n % 3 == 0) CHECK(advance(&world, 1));
        }
    }
    return true;
}

int main(void) {
    const struct { const char *name; bool (*run)(void); } tests[] = {
        {"wire_fixtures_and_rejection", codec}, {"identities_and_closed_slots", isolation},
        {"server_movement_burst_walls_collision", movement}, {"fire_cooldown_ammo_death", combat},
        {"server_aim_and_range", aiming}, {"loss_replay_and_overflow", sequences},
        {"bounded_parser_and_state_history_fuzz", fuzz}
    };
    for (size_t i = 0; i < sizeof tests / sizeof tests[0]; ++i) {
        if (!tests[i].run()) return 1;
        printf("PASS: %s\n", tests[i].name);
    }
    return 0;
}
