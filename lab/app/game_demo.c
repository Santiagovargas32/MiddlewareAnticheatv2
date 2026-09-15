#include "lab/game/game.h"
#include "lab/contracts/lab.h"

#include <inttypes.h>
#include <stdio.h>
#include <string.h>

static bool step(game_world_t *world, size_t slot, uint32_t seq, uint8_t action,
                 uint8_t x, game_result_t expected) {
    game_input_t command = { .sequence = seq, .action = action, .axis_x = x };
    memcpy(command.match, world->match, 16);
    memcpy(command.session, world->players[slot].session, 16);
    uint8_t bytes[GAME_INPUT_SIZE];
    game_input_t parsed;
    if (!game_input_encode(bytes, sizeof bytes, &command) ||
        !game_input_decode(bytes, sizeof bytes, &parsed)) return false;
    game_result_t result = game_apply(world, slot, &parsed);
    printf("{\"event\":\"input\",\"tick\":%" PRIu64 ",\"player\":%zu,\"sequence\":%" PRIu32
           ",\"action\":%u,\"reason\":\"%s\"}\n", world->tick, slot, seq,
           (unsigned)action, game_result_name(result));
    return result == expected;
}

int main(int argc, char **argv) {
    if (argc != 1) {
        (void)argv;
        fputs("Usage: lab_game_demo\n", stderr);
        return 2;
    }
    uint8_t match[16], a[16], b[16];
    game_world_t world;
    if (!lab_random_bytes(match, sizeof match) || !lab_random_bytes(a, sizeof a) ||
        !lab_random_bytes(b, sizeof b) || !game_init(&world, match, a, b)) {
        fputs("{\"error\":\"INITIALIZATION_FAILED\"}\n", stderr);
        return 1;
    }
    puts("{\"event\":\"start\",\"protocol\":\"lab-game-input/1\",\"scope\":\"local_scripted_simulation\",\"authenticated_transport\":false,\"tick_ms\":50}");
    if (!step(&world, 0, 1, GAME_MOVE, GAME_AXIS_POS, GAME_OK) ||
        !step(&world, 0, 2, GAME_MOVE, GAME_AXIS_POS, GAME_TICK_USED) ||
        !step(&world, 0, 1, GAME_MOVE, GAME_AXIS_POS, GAME_REPLAY) ||
        game_advance(&world) != GAME_OK ||
        !step(&world, 0, 2, GAME_FIRE, 0, GAME_OK) ||
        game_advance(&world) != GAME_OK ||
        !step(&world, 0, 3, GAME_FIRE, 0, GAME_COOLDOWN) ||
        !step(&world, 1, 1, GAME_MOVE, GAME_AXIS_POS, GAME_OK)) return 1;
    while (world.tick < 5) if (game_advance(&world) != GAME_OK) return 1;
    if (!step(&world, 0, 3, GAME_FIRE, 0, GAME_OK) || game_close(&world, 1) != GAME_OK ||
        !step(&world, 1, 2, GAME_WAIT, 0, GAME_CLOSED)) return 1;
    bool ok = world.players[0].x_mm == 100 && world.players[0].ammo == 2 &&
              world.players[0].hits == 2 && world.players[1].x_mm == 600 &&
              world.players[1].health == 50 && !world.players[1].open;
    printf("{\"event\":\"final\",\"passed\":%s,\"tick\":%" PRIu64
           ",\"player0_x_mm\":%" PRId32 ",\"player0_ammo\":%u,\"player0_hits\":%u,"
           "\"player1_x_mm\":%" PRId32 ",\"player1_health\":%u,\"player1_open\":false}\n",
           ok ? "true" : "false", world.tick, world.players[0].x_mm, world.players[0].ammo,
           world.players[0].hits, world.players[1].x_mm, world.players[1].health);
    return ok && fflush(stdout) == 0 && !ferror(stdout) ? 0 : 1;
}
