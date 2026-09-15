#ifndef LAB_GAME_H
#define LAB_GAME_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

/* lab-game-input/1, separate from lab-udp/2. No authentication in this codec. */
#define GAME_INPUT_SIZE 48u
#define GAME_PLAYERS 2u
#define GAME_TICK_MS 50u
#define GAME_STEP_MM 100
#define GAME_EDGE_MM 10000
#define GAME_RANGE_MM 2000
#define GAME_FIRE_TICKS 4u
#define GAME_AMMO 4u
#define GAME_HEALTH 100u
#define GAME_DAMAGE 25u

typedef enum { GAME_MOVE = 1, GAME_FIRE = 2, GAME_WAIT = 3 } game_action_t;
typedef enum { GAME_AXIS_NONE = 0, GAME_AXIS_NEG = 1, GAME_AXIS_POS = 2 } game_axis_t;
typedef enum {
    GAME_OK = 0, GAME_BAD_INPUT, GAME_WRONG_MATCH, GAME_WRONG_SESSION,
    GAME_CLOSED, GAME_DEAD, GAME_REPLAY, GAME_SEQUENCE_EXHAUSTED,
    GAME_TICK_USED, GAME_COOLDOWN, GAME_NO_AMMO, GAME_WALL,
    GAME_OCCUPIED, GAME_CLOCK_EXHAUSTED
} game_result_t;

typedef struct {
    uint8_t match[16], session[16];
    uint32_t sequence;
    uint8_t action, axis_x, axis_y;
} game_input_t;

typedef struct {
    uint8_t session[16];
    int32_t x_mm, y_mm;
    int8_t facing_x, facing_y;
    uint32_t last_sequence;
    uint64_t last_input_tick, next_fire_tick;
    unsigned ammo, health, hits, kills;
    bool open, has_input;
} game_player_t;

/* Owned by ONE trusted server thread. Never deserialize client bytes here.
 * Transport chooses authenticated_slot; the packet cannot choose its owner.
 * advance() is called by the server scheduler only, never by client time.
 * No catch-up after idle: at most one accepted intent/player/server tick.
 * Rejected input changes neither world nor sequence. Slots are not reopened;
 * a new match needs fresh random match/session IDs provided by the caller.
 */
typedef struct {
    uint8_t match[16];
    uint64_t tick;
    game_player_t players[GAME_PLAYERS];
} game_world_t;

bool game_input_decode(const uint8_t *bytes, size_t size, game_input_t *out);
bool game_input_encode(uint8_t *bytes, size_t size, const game_input_t *input);
bool game_init(game_world_t *world, const uint8_t match[16],
               const uint8_t session_a[16], const uint8_t session_b[16]);
game_result_t game_apply(game_world_t *world, size_t authenticated_slot,
                         const game_input_t *input);
game_result_t game_advance(game_world_t *world);
game_result_t game_close(game_world_t *world, size_t authenticated_slot);
const char *game_result_name(game_result_t result);

#endif
