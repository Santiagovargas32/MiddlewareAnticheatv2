/* Private pipe worker. Only the trusted supervisor sends control operations.
 * Network clients can supply only the 48-byte input payload, never op or slot.
 */
#include "lab/game/game.h"
#include "lab/contracts/lab.h"

#include <errno.h>
#include <stdio.h>
#include <string.h>
#ifdef _WIN32
#include <fcntl.h>
#include <io.h>
#endif

static void put_le(uint8_t *out, uint64_t value, unsigned count) {
    for (unsigned i = 0; i < count; ++i) out[i] = (uint8_t)(value >> (8u * i));
}

static int reply(const game_world_t *world, uint8_t slot, uint32_t sequence, game_result_t status) {
    uint8_t data[80] = {0};
    memcpy(data, "LGST", 4); data[4] = 1; data[5] = (uint8_t)status;
    data[6] = slot; data[7] = 1; /* Explicit server-rules profile, no attestation. */
    put_le(data + 8, world->tick, 8); put_le(data + 16, sequence, 4);
    memcpy(data + 20, world->match, 16);
    memcpy(data + 36, world->players[slot].session, 16);
    for (unsigned i = 0; i < GAME_PLAYERS; ++i) {
        const game_player_t *p = &world->players[i];
        uint8_t *record = data + 52 + 12 * i;
        put_le(record, (uint32_t)p->x_mm, 4); put_le(record + 4, (uint32_t)p->y_mm, 4);
        record[8] = (uint8_t)p->health; record[9] = (uint8_t)p->ammo;
        record[10] = (uint8_t)p->hits; record[11] = (uint8_t)p->kills;
        if (p->open) data[76] |= (uint8_t)(1u << i);
    }
    return fwrite(data, 1, sizeof data, stdout) == sizeof data && fflush(stdout) == 0;
}

static int read_command(uint8_t data[50]) {
    size_t offset = 0;
    while (offset < 50) {
        errno = 0;
        size_t count = fread(data + offset, 1, 50 - offset, stdin);
        offset += count;
        if (offset == 50) return 1;
        if (ferror(stdin) && errno == EINTR) { clearerr(stdin); continue; }
        if (ferror(stdin) || feof(stdin)) return offset == 0 && feof(stdin) ? 0 : -1;
    }
    return 1;
}

int main(int argc, char **argv) {
    (void)argv;
    if (argc != 1) return 2;
#ifdef _WIN32
    if (_setmode(_fileno(stdin), _O_BINARY) == -1 || _setmode(_fileno(stdout), _O_BINARY) == -1) return 1;
#endif
    uint8_t match[16], a[16], b[16];
    game_world_t world;
    if (!lab_random_bytes(match, 16) || !lab_random_bytes(a, 16) || !lab_random_bytes(b, 16) ||
        !game_init(&world, match, a, b) || !reply(&world, 0, 0, GAME_OK) ||
        !reply(&world, 1, 0, GAME_OK)) return 1;
    for (;;) {
        uint8_t command[50];
        int read_status = read_command(command);
        if (read_status != 1) return read_status == 0 ? 0 : 1;
        uint8_t op = command[0], slot = command[1];
        if (slot >= GAME_PLAYERS) return 1;
        uint32_t sequence = 0;
        game_result_t status = GAME_BAD_INPUT;
        if (op == 1) {
            game_input_t in;
            if (game_input_decode(command + 2, 48, &in)) {
                sequence = in.sequence;
                status = game_apply(&world, slot, &in);
            }
        } else {
            unsigned reserved = 0;
            size_t used = op == 2 ? 8u : 0u;
            for (size_t i = used; i < 48; ++i) reserved |= command[2 + i];
            if (reserved) return 1;
            if (op == 2) {
                uint64_t tick = 0;
                for (unsigned i = 0; i < 8; ++i) tick |= (uint64_t)command[2 + i] << (8u * i);
                if (tick < world.tick) return 1;
                world.tick = tick; /* Supervisor's monotonic clock, never client time. */
                status = GAME_OK;
            } else if (op == 3) status = game_close(&world, slot);
            else if (op == 4) status = world.players[slot].open ? GAME_OK : GAME_CLOSED;
            else return 1;
        }
        if (!reply(&world, slot, sequence, status)) return 1;
    }
}
