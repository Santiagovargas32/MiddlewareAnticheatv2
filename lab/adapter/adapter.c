/* Local UDP relay: one upstream socket per downstream peer, bounded queues. */
#define _POSIX_C_SOURCE 200809L
#include "../contracts/lab.h"
#include "../contracts/evidence.h"
#include "../platform/net.h"
#include <errno.h>
#include <poll.h>
#include <signal.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>

#define ROUTES 32
#define QUEUE 32

typedef struct { uint8_t data[LAB_MAX_DATAGRAM]; size_t size; uint64_t due; } pending_t;
typedef struct {
  int used, fd;
  struct sockaddr_in peer;
  uint64_t activity;
  uint8_t session[16];
  pending_t queue[QUEUE];
  size_t head, count;
} route_t;
static volatile sig_atomic_t stopping;
static void stop_adapter(int signo) { (void)signo; stopping = 1; }

static int reject(int fd, const struct sockaddr_in *peer, const uint8_t session[16], uint32_t reason, const char *message) {
  uint8_t wire[16 + LAB_RST_LEN];
  lab_hdr_t h = { .magic = LAB_MAGIC, .version = LAB_VERSION, .kind = LAB_RST, .len = LAB_RST_LEN };
  lab_rst_t rst = { .reason = reason, .len = (uint32_t)strlen(message) };
  if (session) memcpy(rst.session, session, 16);
  memcpy(rst.msg, message, rst.len);
  lab_hdr_pack(wire, &h); lab_payload_pack(wire + 16, LAB_RST_LEN, LAB_RST, &rst);
  return sendto(fd, wire, sizeof wire, 0, (const struct sockaddr *)peer, sizeof *peer) == (ssize_t)sizeof wire;
}
static void release(route_t *route) {
  if (route->used) close(route->fd);
  memset(route, 0, sizeof *route);
}
static int enqueue(route_t *route, const uint8_t *data, size_t size, uint64_t due) {
  if (route->count == QUEUE) return 0;
  pending_t *p = &route->queue[(route->head + route->count) % QUEUE];
  memcpy(p->data, data, size); p->size = size; p->due = due; route->count++;
  return 1;
}
static void usage(void) {
  fprintf(stderr, "lab_adapter --listen 127.0.0.1:7778 --upstream 127.0.0.1:7777 [--max-clients 32] [--idle-ms 10000] [--truncate N] [--drop-every N] [--delay-ms N] [--replay-last] [-v]\n");
}
int main(int argc, char **argv) {
  struct sockaddr_in listen_address, upstream;
  uint32_t max_clients = ROUTES, idle = 10000, truncate = 0, drop = 0, delay = 0;
  int verbose = 0, replay = 0;
  if (!lab_endpoint("127.0.0.1:7778", &listen_address) || !lab_endpoint("127.0.0.1:7777", &upstream)) return 1;
  for (int i = 1; i < argc; ++i) {
    if (!strcmp(argv[i], "-v")) { verbose = 1; continue; }
    if (!strcmp(argv[i], "--replay-last")) { replay = 1; continue; }
    if (i + 1 == argc) { usage(); return 2; }
    const char *option = argv[i++], *value = argv[i];
    if (!strcmp(option, "--listen")) { if (!lab_endpoint(value, &listen_address)) return 2; }
    else if (!strcmp(option, "--upstream")) { if (!lab_endpoint(value, &upstream)) return 2; }
    else if (!strcmp(option, "--max-clients")) { if (!lab_parse_u32(value, 1, ROUTES, &max_clients)) return 2; }
    else if (!strcmp(option, "--idle-ms")) { if (!lab_parse_u32(value, 1, 60000, &idle)) return 2; }
    else if (!strcmp(option, "--truncate")) { if (!lab_parse_u32(value, 0, 4096, &truncate)) return 2; }
    else if (!strcmp(option, "--drop-every")) { if (!lab_parse_u32(value, 1, 4096, &drop)) return 2; }
    else if (!strcmp(option, "--delay-ms")) { if (!lab_parse_u32(value, 0, 5000, &delay)) return 2; }
    else { usage(); return 2; }
  }
  struct sigaction action = {0}; action.sa_handler = stop_adapter; sigemptyset(&action.sa_mask);
  if (sigaction(SIGINT, &action, NULL) || sigaction(SIGTERM, &action, NULL)) return 1;
  int fd = lab_udp_bound(&listen_address);
  if (fd < 0) { perror("adapter bind"); return 1; }
  route_t routes[ROUTES] = {0};
  uint64_t received = 0, forwarded = 0, discarded = 0;
  int failed = 0;
  printf("{\"ev\":\"boot\",\"port\":%u,\"max\":%u}\n", ntohs(listen_address.sin_port), max_clients); fflush(stdout);
  while (!stopping && !failed) {
    struct pollfd items[1 + ROUTES] = {{ .fd = fd, .events = POLLIN }};
    for (size_t i = 0; i < ROUTES; ++i) items[i + 1] = (struct pollfd){ .fd = routes[i].used ? routes[i].fd : -1, .events = POLLIN };
    int ready = poll(items, 1 + ROUTES, 10);
    if (ready < 0) { if (errno == EINTR) continue; failed = 1; break; }
    uint64_t now = lab_now_ms();
    /* Read upstream first. No response can be assigned to a different socket. */
    for (size_t i = 0; i < ROUTES; ++i) {
      route_t *r = &routes[i];
      if (!r->used) continue;
      if (items[i + 1].revents & (POLLIN | POLLERR)) {
        for (size_t work = 0; work < 16; ++work) {
          uint8_t data[LAB_MAX_DATAGRAM];
          ssize_t n = recv(r->fd, data, sizeof data, MSG_TRUNC);
          if (n < 0) {
            if (errno == EAGAIN || errno == EINTR) break;
            if (!reject(fd, &r->peer, r->session, LAB_CLOSING, "upstream unavailable")) failed = 1;
            release(r); break;
          }
          if ((size_t)n > sizeof data) { discarded++; continue; }
          lab_hdr_t h;
          if (lab_hdr_parse(data, (size_t)n, &h) && h.version == LAB_VERSION && h.kind == LAB_HELLO_ACK && h.len == LAB_HELLO_ACK_LEN && n == 16 + LAB_HELLO_ACK_LEN)
            memcpy(r->session, data + 24, 16);
          if (sendto(fd, data, (size_t)n, 0, (struct sockaddr *)&r->peer, sizeof r->peer) != n) { failed = 1; break; }
          forwarded++;
          lab_rst_t reset;
          if (lab_hdr_parse(data, (size_t)n, &h) && h.magic == LAB_MAGIC && h.version == LAB_VERSION &&
              h.kind == LAB_RST && h.len == LAB_RST_LEN && n == 16 + LAB_RST_LEN &&
              lab_payload_parse(data + 16, LAB_RST_LEN, LAB_RST, &reset) &&
              !memcmp(reset.session, r->session, 16) &&
              ((reset.reason == LAB_OK && reset.len == 3 &&
                (!memcmp(reset.msg, "bye", 3) || !memcmp(reset.msg, "rst", 3))) ||
               reset.reason == LAB_TIMEOUT || reset.reason == LAB_CLOSING)) {
            release(r); break;
          }
        }
      }
      if (!r->used) continue;
      if (now - r->activity >= idle) { release(r); continue; }
      for (size_t work = 0; work < 16 && r->count; ++work) {
        pending_t *p = &r->queue[r->head];
        if (p->due > now) break;
        if (!lab_send(r->fd, p->data, p->size)) {
          if (errno == EAGAIN) break;
          if (!reject(fd, &r->peer, r->session, LAB_CLOSING, "upstream unavailable")) failed = 1;
          release(r); break;
        }
        r->head = (r->head + 1) % QUEUE; r->count--; forwarded++;
      }
    }
    if (items[0].revents & (POLLERR | POLLNVAL | POLLHUP)) { failed = 1; break; }
    if (!(items[0].revents & POLLIN)) continue;
    for (size_t work = 0; work < 16; ++work) {
      uint8_t data[LAB_MAX_DATAGRAM];
      struct sockaddr_in peer = {0}; socklen_t size = sizeof peer;
      ssize_t n = recvfrom(fd, data, sizeof data, MSG_TRUNC, (struct sockaddr *)&peer, &size);
      if (n < 0) { if (errno == EAGAIN || errno == EINTR) break; failed = 1; break; }
      if (size != sizeof peer || peer.sin_family != AF_INET || (ntohl(peer.sin_addr.s_addr) >> 24) != 127) continue;
      received++;
      route_t *route = NULL, *free_slot = NULL;
      size_t active = 0;
      for (size_t i = 0; i < ROUTES; ++i) {
        if (routes[i].used) { active++; if (lab_same_peer(&routes[i].peer, &peer)) route = &routes[i]; }
        else if (!free_slot) free_slot = &routes[i];
      }
      if ((size_t)n > sizeof data) {
        if (!reject(fd, &peer, route ? route->session : NULL, LAB_TOO_BIG, ">128 B")) failed = 1;
        discarded++; continue;
      }
      if (!route) {
        lab_hdr_t header;
        if (lab_hdr_parse(data, (size_t)n, &header) && header.magic == LAB_MAGIC &&
            header.version == LAB_VERSION &&
            (header.kind == LAB_PING || header.kind == LAB_BYE || header.kind == LAB_RST ||
             header.kind == LAB_REQUEST || header.kind == LAB_OBSERVATION)) {
          if (!reject(fd, &peer, NULL, LAB_BAD_KIND, "HELLO primero")) failed = 1;
          discarded++; continue;
        }
        if (!free_slot || active >= max_clients) {
          if (!reject(fd, &peer, NULL, LAB_BUSY, "adapter full")) failed = 1;
          discarded++; continue;
        }
        struct sockaddr_in local = { .sin_family = AF_INET, .sin_addr.s_addr = htonl(INADDR_LOOPBACK) };
        int upstream_fd = lab_udp_bound(&local);
        if (upstream_fd < 0) { failed = 1; break; }
        if (connect(upstream_fd, (struct sockaddr *)&upstream, sizeof upstream) < 0) { close(upstream_fd); failed = 1; break; }
        route = free_slot; route->fd = upstream_fd; route->peer = peer; route->used = 1;
      }
      route->activity = now;
      if (drop && (received - 1) % drop == 0) { discarded++; continue; }
      size_t length = (size_t)n;
      if (truncate) { if (length >= 8) length -= 8; truncate--; }
      if (!enqueue(route, data, length, now + delay)) {
        if (!reject(fd, &peer, route->session, LAB_BUSY, "adapter queue full")) failed = 1;
        discarded++; continue;
      }
      if (replay && n >= 16 && data[2] == LAB_PING && !enqueue(route, data, length, now + delay + 100)) discarded++;
    }
  }
  for (size_t i = 0; i < ROUTES; ++i) release(&routes[i]);
  if (close(fd) < 0) failed = 1;
  if (verbose) printf("{\"ev\":\"exit\",\"received\":%llu,\"forwarded\":%llu,\"discarded\":%llu}\n", (unsigned long long)received, (unsigned long long)forwarded, (unsigned long long)discarded);
  return failed ? 1 : 0;
}
