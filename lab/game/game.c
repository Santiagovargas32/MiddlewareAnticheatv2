#include "game.h"

#include <string.h>

static bool nonzero(const uint8_t id[16]) {
    unsigned combined = 0;
    for (size_t i = 0; i < 16; ++i) combined |= id[i];
    return combined != 0;
}

static bool valid_input(const game_input_t *in) {
    if (!in || !nonzero(in->match) || !nonzero(in->session) || !in->sequence ||
        in->axis_x > GAME_AXIS_POS || in->axis_y > GAME_AXIS_POS) return false;
    if (in->action == GAME_MOVE)
        return (in->axis_x != GAME_AXIS_NONE) != (in->axis_y != GAME_AXIS_NONE);
    return (in->action == GAME_FIRE || in->action == GAME_WAIT) &&
           in->axis_x == GAME_AXIS_NONE && in->axis_y == GAME_AXIS_NONE;
}

bool game_input_decode(const uint8_t *bytes, size_t size, game_input_t *out) {
    if (!bytes || !out || size != GAME_INPUT_SIZE || memcmp(bytes, "LGIN", 4) ||
        bytes[4] != 1 || bytes[44] || bytes[45] || bytes[46] || bytes[47]) return false;
    game_input_t candidate = {0};
    candidate.action = bytes[5];
    candidate.axis_x = bytes[6];
    candidate.axis_y = bytes[7];
    memcpy(candidate.match, bytes + 8, 16);
    memcpy(candidate.session, bytes + 24, 16);
    for (unsigned i = 0; i < 4; ++i)
        candidate.sequence |= (uint32_t)bytes[40 + i] << (8u * i);
    if (!valid_input(&candidate)) return false;
    *out = candidate;
    return true;
}

bool game_input_encode(uint8_t *bytes, size_t size, const game_input_t *in) {
    if (!bytes || size != GAME_INPUT_SIZE || !valid_input(in)) return false;
    /* Assemble separately so an invalid input never changes caller output. */
    uint8_t result[GAME_INPUT_SIZE] = {0};
    memcpy(result, "LGIN", 4);
    result[4] = 1;
    result[5] = in->action;
    result[6] = in->axis_x;
    result[7] = in->axis_y;
    memcpy(result + 8, in->match, 16);
    memcpy(result + 24, in->session, 16);
    for (unsigned i = 0; i < 4; ++i)
        result[40 + i] = (uint8_t)(in->sequence >> (8u * i));
    memcpy(bytes, result, sizeof result);
    return true;
}

bool game_init(game_world_t *world, const uint8_t match[16],
               const uint8_t session_a[16], const uint8_t session_b[16]) {
    if (!world || !match || !session_a || !session_b || !nonzero(match) ||
        !nonzero(session_a) || !nonzero(session_b) || !memcmp(session_a, session_b, 16)) return false;
    game_world_t next = {0};
    memcpy(next.match, match, 16);
    memcpy(next.players[0].session, session_a, 16);
    memcpy(next.players[1].session, session_b, 16);
    next.players[1].x_mm = 500;
    for (size_t i = 0; i < GAME_PLAYERS; ++i) {
        next.players[i].facing_x = i == 0 ? 1 : -1;
        next.players[i].ammo = GAME_AMMO;
        next.players[i].health = GAME_HEALTH;
        next.players[i].open = true;
    }
    *world = next;
    return true;
}

static int32_t direction(uint8_t axis) {
    return axis == GAME_AXIS_NEG ? -1 : axis == GAME_AXIS_POS ? 1 : 0;
}

static bool hit(const game_player_t *shooter, const game_player_t *other) {
    /* Positions are server-owned, confined to [-GAME_EDGE_MM, GAME_EDGE_MM]. */
    int32_t dx = other->x_mm - shooter->x_mm;
    int32_t dy = other->y_mm - shooter->y_mm;
    if (shooter->facing_x)
        return dy == 0 && dx * shooter->facing_x > 0 && dx * shooter->facing_x <= GAME_RANGE_MM;
    return dx == 0 && dy * shooter->facing_y > 0 && dy * shooter->facing_y <= GAME_RANGE_MM;
}

game_result_t game_apply(game_world_t *world, size_t slot, const game_input_t *in) {
    if (!world || slot >= GAME_PLAYERS || !valid_input(in)) return GAME_BAD_INPUT;
    if (memcmp(world->match, in->match, 16)) return GAME_WRONG_MATCH;
    game_player_t *player = &world->players[slot];
    if (memcmp(player->session, in->session, 16)) return GAME_WRONG_SESSION;
    if (!player->open) return GAME_CLOSED;
    if (!player->health) return GAME_DEAD;
    if (in->sequence == UINT32_MAX) return GAME_SEQUENCE_EXHAUSTED;
    if (in->sequence <= player->last_sequence) return GAME_REPLAY;
    if (player->has_input && player->last_input_tick == world->tick) return GAME_TICK_USED;
    game_player_t next = *player;
    game_player_t *other = &world->players[1u - slot];
    bool damage = false;
    if (in->action == GAME_MOVE) {
        next.facing_x = (int8_t)direction(in->axis_x);
        next.facing_y = (int8_t)direction(in->axis_y);
        next.x_mm += next.facing_x * GAME_STEP_MM;
        next.y_mm += next.facing_y * GAME_STEP_MM;
        if (next.x_mm < -GAME_EDGE_MM || next.x_mm > GAME_EDGE_MM ||
            next.y_mm < -GAME_EDGE_MM || next.y_mm > GAME_EDGE_MM) return GAME_WALL;
        if (other->open && other->health && next.x_mm == other->x_mm && next.y_mm == other->y_mm)
            return GAME_OCCUPIED;
    } else if (in->action == GAME_FIRE) {
        if (!next.ammo) return GAME_NO_AMMO;
        if (world->tick < next.next_fire_tick) return GAME_COOLDOWN;
        if (world->tick > UINT64_MAX - GAME_FIRE_TICKS) return GAME_CLOCK_EXHAUSTED;
        next.next_fire_tick = world->tick + GAME_FIRE_TICKS;
        --next.ammo;
        damage = other->open && other->health && hit(&next, other);
        if (damage) {
            ++next.hits;
            if (other->health <= GAME_DAMAGE) ++next.kills;
        }
    }
    next.has_input = true;
    next.last_input_tick = world->tick;
    next.last_sequence = in->sequence;
    *player = next;
    if (damage) other->health = other->health > GAME_DAMAGE ? other->health - GAME_DAMAGE : 0;
    return GAME_OK;
}

game_result_t game_advance(game_world_t *world) {
    if (!world) return GAME_BAD_INPUT;
    if (world->tick == UINT64_MAX) return GAME_CLOCK_EXHAUSTED;
    ++world->tick;
    return GAME_OK;
}

game_result_t game_close(game_world_t *world, size_t slot) {
    if (!world || slot >= GAME_PLAYERS) return GAME_BAD_INPUT;
    world->players[slot].open = false;
    return GAME_OK;
}

const char *game_result_name(game_result_t result) {
    switch (result) {
    case GAME_OK: return "ACCEPTED";
    case GAME_BAD_INPUT: return "BAD_INPUT";
    case GAME_WRONG_MATCH: return "WRONG_MATCH";
    case GAME_WRONG_SESSION: return "WRONG_SESSION";
    case GAME_CLOSED: return "SESSION_CLOSED";
    case GAME_DEAD: return "PLAYER_DEAD";
    case GAME_REPLAY: return "SEQUENCE_REPLAY";
    case GAME_SEQUENCE_EXHAUSTED: return "SEQUENCE_EXHAUSTED";
    case GAME_TICK_USED: return "TICK_ALREADY_USED";
    case GAME_COOLDOWN: return "FIRE_COOLDOWN";
    case GAME_NO_AMMO: return "NO_AMMO";
    case GAME_WALL: return "OUTSIDE_ARENA";
    case GAME_OCCUPIED: return "POSITION_OCCUPIED";
    case GAME_CLOCK_EXHAUSTED: return "SERVER_TICK_EXHAUSTED";
    }
    return "UNKNOWN_RESULT";
}
