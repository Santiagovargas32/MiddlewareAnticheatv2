#define _POSIX_C_SOURCE 200809L
#include "lab/game/view.h"
#include "lab/contracts/lab.h"
#include "raylib.h"

#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>

/* Graphics owns no simulation state. Every position/HP/ammo is server supplied. */
typedef struct {
    uint8_t buffer[84];
    size_t used, wanted;
    game_view_t view;
    bool ready;
    int face_x, face_y;
    unsigned updates;
    const char *message;
} viewer_t;

static bool message(viewer_t *v, const uint8_t *data, size_t size) {
    if (size == 5 && !memcmp(data, "LGRE", 4)) {
        if (data[4] != 7) return false;
        v->message = "Waiting for both players";
        return true;
    }
    game_view_t next;
    if (!game_view_decode(data, size, &next)) return false;
    if (v->ready) {
        if (memcmp(next.match, v->view.match, 16) || memcmp(next.session, v->view.session, 16) ||
            next.slot != v->view.slot || next.tick < v->view.tick || next.sequence < v->view.sequence) return false;
        int32_t dx = next.players[next.slot].x_mm - v->view.players[next.slot].x_mm;
        int32_t dy = next.players[next.slot].y_mm - v->view.players[next.slot].y_mm;
        if (dx) { v->face_x = dx > 0 ? 1 : -1; v->face_y = 0; }
        else if (dy) { v->face_x = 0; v->face_y = dy > 0 ? 1 : -1; }
    } else v->face_x = next.slot == 0 ? 1 : -1;
    v->view = next; v->ready = true; ++v->updates;
    v->message = game_result_name((game_result_t)next.result);
    return true;
}

static int receive(viewer_t *v) {
    /* Bound work per rendered frame even if the pipe is flooded. */
    for (unsigned iteration = 0; iteration < 16; ++iteration) {
        if (!v->wanted) v->wanted = 4;
        ssize_t count = read(STDIN_FILENO, v->buffer + v->used, v->wanted - v->used);
        if (count < 0) {
            if (errno == EINTR) continue;
            return errno == EAGAIN || errno == EWOULDBLOCK ? 1 : -1;
        }
        if (!count) return -1;
        v->used += (size_t)count;
        if (v->used != v->wanted) continue;
        if (v->wanted == 4) {
            uint32_t length = (uint32_t)v->buffer[0] << 24 | (uint32_t)v->buffer[1] << 16 |
                              (uint32_t)v->buffer[2] << 8 | v->buffer[3];
            if (length != 80 && length != 5) return -1;
            v->wanted = 4 + length;
        } else {
            if (!message(v, v->buffer + 4, v->wanted - 4)) return -1;
            v->used = 0; v->wanted = 4;
        }
    }
    return 1;
}

static void draw(const viewer_t *v) {
    const Color base = {12, 19, 30, 255}, accent = {70, 210, 218, 255};
    BeginDrawing(); ClearBackground(base);
    if (v->ready) {
        unsigned own = v->view.slot, other = 1u - own;
        /* 100 mm of server coordinates per visual unit, uniform scaling. */
        float x = (float)v->view.players[own].x_mm * 0.01f;
        float z = (float)v->view.players[own].y_mm * 0.01f;
        Camera3D camera = { .position = {x, 1.6f, z},
            .target = {x + (float)v->face_x, 1.5f, z + (float)v->face_y},
            .up = {0, 1, 0}, .fovy = 70, .projection = CAMERA_PERSPECTIVE };
        BeginMode3D(camera);
        DrawPlane((Vector3){0, -0.01f, 0}, (Vector2){200, 200}, (Color){27, 39, 53, 255});
        DrawGrid(40, 5);
        for (int side = -1; side <= 1; side += 2) {
            DrawCube((Vector3){(float)side * 100, 2, 0}, 0.5f, 4, 200, (Color){35, 67, 86, 255});
            DrawCube((Vector3){0, 2, (float)side * 100}, 200, 4, 0.5f, (Color){35, 67, 86, 255});
        }
        if (v->view.players[other].open && v->view.players[other].health) {
            float ox = (float)v->view.players[other].x_mm * 0.01f;
            float oz = (float)v->view.players[other].y_mm * 0.01f;
            DrawCube((Vector3){ox, 0.85f, oz}, 0.65f, 1.7f, 0.65f, (Color){235, 110, 65, 255});
            DrawCubeWires((Vector3){ox, 0.85f, oz}, 0.67f, 1.72f, 0.67f, ORANGE);
            DrawSphere((Vector3){ox, 1.95f, oz}, 0.3f, (Color){255, 192, 110, 255});
        }
        EndMode3D();
        DrawRectangle(0, 0, 960, 76, (Color){12, 19, 30, 245});
        DrawText("OPEN ARENA / LINUX", 28, 18, 24, accent);
        DrawText(TextFormat("PLAYER %u  |  SERVER RULES  |  TICK %llu", own + 1,
                 (unsigned long long)v->view.tick), 28, 48, 16, LIGHTGRAY);
        DrawLine(472, 270, 488, 270, accent); DrawLine(480, 262, 480, 278, accent);
        /* Original geometric weapon marker: no assets or client-side hit scoring. */
        DrawRectangle(448, 435, 64, 105, (Color){37, 69, 92, 255});
        DrawRectangle(465, 410, 30, 55, accent);
        DrawRectangle(0, 478, 400, 62, (Color){12, 19, 30, 240});
        DrawText(TextFormat("HEALTH %u    AMMO %u    HITS %u", v->view.players[own].health,
                 v->view.players[own].ammo, v->view.players[own].hits), 24, 491, 20, WHITE);
        DrawText("W/A/S/D cardinal move | SPACE fire | ESC exit", 24, 518, 14, LIGHTGRAY);
        DrawRectangle(640, 488, 320, 52, (Color){12, 19, 30, 240});
        DrawText(v->message, 653, 502, 16, accent);
    } else DrawText("Connecting to authoritative server...", 80, 230, 24, accent);
    EndDrawing();
}

int main(int argc, char **argv) {
    bool hidden = false, scripted = false;
    uint32_t seconds = 20;
    const char *screenshot = NULL;
    for (int i = 1; i < argc; ++i) {
        if (!strcmp(argv[i], "--hidden")) hidden = true;
        else if (!strcmp(argv[i], "--scripted")) scripted = true;
        else if (!strcmp(argv[i], "--seconds") && i + 1 < argc) {
            if (!lab_parse_u32(argv[++i], 1, 20, &seconds)) return 2;
        } else if (!strcmp(argv[i], "--screenshot") && i + 1 < argc) screenshot = argv[++i];
        else return 2;
    }
    int flags = fcntl(STDIN_FILENO, F_GETFL);
    if (flags == -1 || fcntl(STDIN_FILENO, F_SETFL, flags | O_NONBLOCK) == -1) return 1;
    SetTraceLogLevel(LOG_NONE);
    if (hidden) SetConfigFlags(FLAG_WINDOW_HIDDEN);
    InitWindow(960, 540, "Open Arena - Linux anticheat lab");
    if (!IsWindowReady()) return 1;
    SetTargetFPS(60);
    viewer_t viewer = { .message = "Connected", .face_x = 1 };
    double start = GetTime(), last_input = start;
    unsigned frames = 0, scripted_step = 0;
    bool ok = true;
    while (!WindowShouldClose() && GetTime() - start < (double)seconds) {
        if (receive(&viewer) < 0) { ok = false; break; }
        double elapsed = GetTime() - start;
        unsigned char action = 0;
        if (viewer.ready && GetTime() - last_input >= 0.1) {
            if (scripted) {
                if (scripted_step == 0 && elapsed > 0.6) {
                    action = viewer.view.slot == 0 ? 'e' : 'w'; ++scripted_step;
                } else if (scripted_step == 1 && elapsed > 1.0) {
                    action = viewer.view.slot == 0 ? 'f' : '.'; ++scripted_step;
                }
            } else {
                if (IsKeyDown(KEY_W)) action = 'n';
                else if (IsKeyDown(KEY_S)) action = 's';
                else if (IsKeyDown(KEY_A)) action = 'w';
                else if (IsKeyDown(KEY_D)) action = 'e';
                else if (IsKeyDown(KEY_SPACE)) action = 'f';
            }
            if (action) {
                if (write(STDOUT_FILENO, &action, 1) != 1) { ok = false; break; }
                last_input = GetTime();
            }
        }
        draw(&viewer); ++frames;
    }
    if (screenshot && frames && viewer.ready) {
        Image capture = LoadImageFromScreen();
        if (!capture.data || !ExportImage(capture, screenshot)) ok = false;
        UnloadImage(capture);
    }
    fprintf(stderr, "{\"event\":\"renderer_exit\",\"frames\":%u,\"updates\":%u,\"player\":%u,"
            "\"tick\":%" PRIu64 ",\"sequence\":%" PRIu32 ",\"x_mm\":%" PRId32 ",\"y_mm\":%" PRId32 ",\"health\":%u,\"ammo\":%u}\n",
            frames, viewer.updates, viewer.view.slot, viewer.view.tick, viewer.view.sequence,
            viewer.view.players[viewer.view.slot].x_mm,
            viewer.view.players[viewer.view.slot].y_mm, viewer.view.players[viewer.view.slot].health,
            viewer.view.players[viewer.view.slot].ammo);
    CloseWindow();
    return ok && viewer.ready && frames > 0 ? 0 : 1;
}
