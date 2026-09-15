/*
 * lab/server/server.c
 *
 * Servidor del laboratorio: UDP en loopback. Valida y decide:
 *  - HELLO primero, luego PING/BYE, RST cierra
 *  - session 128 bits desde getrandom; fallo de entropía rechaza HELLO
 *  - seq por dirección (ventana 8, replay 16)
 *  - timeout por inactividad (default 2000 ms)
 *  - observability: JSON por evento (sin credenciales/PII)
 *
 * No fuerza aceptaciones: HELLO_ACK/RST son la decisión.
 */
#define _POSIX_C_SOURCE 200809L
#include "../contracts/lab.h"
#include "../contracts/evidence.h"

#include <stdio.h>

#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <errno.h>
#include <signal.h>
#include <poll.h>
#include <time.h>
#include <sys/socket.h>
#include <sys/types.h>
#include <sys/random.h>
#include <netinet/in.h>
#include <arpa/inet.h>

#define MAX_CLIENTS 32

enum { ST_NEW = 0, ST_OPEN = 1 };

typedef struct {
  int  used;
  int  state;
  uint8_t  session[LAB_SESSION_LEN];
  uint8_t  cnonce[16];
  lab_sequence_t sequence;
  lab_evidence_state_t evidence;
  uint8_t snonce[16];
  uint8_t hello[LAB_HELLO_LEN];
  uint32_t nrst;
  uint64_t open_t;
  uint64_t last_rx;
  char     name[24];
  struct sockaddr_in addr;
} client_t;

typedef struct {
  int  fd;
  char host[16];
  uint16_t port;
  uint32_t timeout_ms;
  uint32_t max_clients;
  int  verbose;
  lab_policy_t policy;

  client_t c[MAX_CLIENTS];
  uint64_t n_rx;
  uint64_t n_acks;
  uint64_t n_rst;
  uint64_t n_timeout;
  int      running;
  int      io_error;
} server_t;

static volatile sig_atomic_t stopping;
static void stop_server(int signo) { (void)signo; stopping = 1; }

static int send_datagram(server_t *s, const client_t *c, const uint8_t *buf, size_t size) {
  ssize_t sent;
  do { sent = sendto(s->fd, buf, size, 0, (const struct sockaddr *)&c->addr, sizeof c->addr); }
  while (sent < 0 && errno == EINTR && !stopping);
  if (sent == (ssize_t)size) return 1;
  perror("sendto"); s->io_error = 1; s->running = 0; return 0;
}

static const char *state_name(int st) {
  static const char *nm[] = { "NEW", "OPEN", "CLOSED", "?" };
  return nm[st & 3];
}

static void log_json(server_t *s, const char *ev, const client_t *c,
                     int has_hdr, const lab_hdr_t *h, uint32_t reason, const char *why) {
  if (!s->verbose) return;
  char host[48] = "?";
  inet_ntop(AF_INET, &c->addr.sin_addr, host, sizeof host);
  uint64_t t = c->open_t ? lab_now_ms() - c->open_t : 0;
  printf("{\"ev\":\"%s\",\"t\":%llu,\"peer\":\"%s:%u\",\"kind\":\"%s\",\"seq\":%u,\"len\":%u,\"state\":\"%s\",\"reason\":%u,\"reason_name\":\"%s\",\"why\":\"%s\"}\n",
          ev, (unsigned long long)t,
          host, (unsigned)ntohs(c->addr.sin_port),
          has_hdr ? lab_kind_name(h->kind) : "?",
          has_hdr ? (unsigned)h->seq : 0,
          has_hdr ? (unsigned)h->len : 0,
          state_name(c->state),
          reason, lab_reason_name(reason), why ? why : "");
  fflush(stdout);
}

static void send_rst(server_t *s, client_t *c, uint32_t reason, const char *msg) {
  lab_hdr_t h;
  memset(&h, 0, sizeof h);
  h.magic = LAB_MAGIC; h.version = LAB_VERSION;
  h.kind = LAB_RST;
  h.seq = c->nrst++;
  h.len = LAB_RST_LEN;

  lab_rst_t p;
  memset(&p, 0, sizeof p);
  memcpy(p.session, c->session, sizeof p.session);
  p.reason = reason;
  p.len = (uint32_t)strnlen(msg ? msg : "", 36);
  if (p.len > 36) p.len = 36;
  if (p.len) memcpy(p.msg, msg, p.len);

  uint8_t buf[16 + LAB_RST_LEN];
  lab_hdr_pack(buf, &h);
  (void)lab_payload_pack(buf + 16, sizeof buf - 16, h.kind, &p);
  if (!send_datagram(s, c, buf, sizeof buf)) return;
  s->n_rst++;

  if (s->verbose) {
    char host[48] = "?";
    inet_ntop(AF_INET, &c->addr.sin_addr, host, sizeof host);
    printf("{\"ev\":\"rst\",\"peer\":\"%s:%u\",\"reason\":%u,\"reason_name\":\"%s\"",
            host, (unsigned)ntohs(c->addr.sin_port),
            reason, lab_reason_name(reason));
    if (msg && *msg) {
      printf(",\"msg\":\"");
      for (const unsigned char *q = (const unsigned char *)msg; *q; q++) {
        if (*q == '"' || *q == '\\') putchar('\\');
        if (*q >= 0x21 && *q <= 0x7e) putchar(*q);
        else printf("\\u%04x", (unsigned)*q);
      }
      printf("\"");
    }
    printf("}\n");
    fflush(stdout);
  }
}

static int send_hello_ack(server_t *s, const client_t *c, const uint8_t snonce[16]) {
  lab_hdr_t h;
  memset(&h, 0, sizeof h);
  h.magic = LAB_MAGIC; h.version = LAB_VERSION;
  h.kind = LAB_HELLO_ACK;
  h.seq = 0;
  h.len = LAB_HELLO_ACK_LEN;

  lab_hello_ack_t p;
  memset(&p, 0, sizeof p);
  p.result = 1u;
  p.reason = LAB_OK;
  memcpy(p.cnonce, c->cnonce, 16);
  memcpy(p.session, c->session, sizeof p.session);
  memcpy(p.snonce, snonce, sizeof p.snonce);

  uint8_t buf[16 + LAB_HELLO_ACK_LEN];
  lab_hdr_pack(buf, &h);
  (void)lab_payload_pack(buf + 16, sizeof buf - 16, h.kind, &p);
  if (!send_datagram(s, c, buf, sizeof buf)) return 0;
  s->n_acks++;
  return 1;
}

static int valid_nonce(const uint8_t *n) {
  uint8_t any = 0;
  for (size_t i = 0; i < 16; i++) any |= n[i];
  return any != 0;
}

/* Each slot owns all session state; releasing it also clears its peer/sequence. */
static void release_client(client_t *c) {
  memset(c, 0, sizeof *c);
}

/* HELLO en estado NEW: valida payload y acepta */
static void do_hello(server_t *s, client_t *c, const uint8_t *pay, uint32_t n) {
  if (n != LAB_HELLO_LEN) {
    uint32_t r = n > 64 ? (n <= 128 ? LAB_TOO_BIG : LAB_BAD_LEN)
                                  : LAB_BAD_LEN;
    send_rst(s, c, r, "hello len");
    return;
  }
  lab_hello_t hello;
  if (!lab_payload_parse(pay, n, LAB_HELLO, &hello)) return;
  const lab_hello_t *p = &hello;

  if (p->app_id != LAB_APP_ID) {
    send_rst(s, c, LAB_BAD_PAYLOAD, "app_id != LAB1"); return;
  }
  if (strnlen(p->app, sizeof p->app) != sizeof LAB_APP_NAME - 1 ||
      memcmp(p->app, LAB_APP_NAME, sizeof LAB_APP_NAME)) {
    send_rst(s, c, LAB_BAD_PAYLOAD, "app != LabClient"); return;
  }
  uint32_t nlen = strnlen(p->name, 24);
  for (uint32_t i = 0; i < nlen; i++) {
    unsigned char ch = (unsigned char)p->name[i];
    if (ch < 0x21 || ch > 0x7e) {
      send_rst(s, c, LAB_BAD_PAYLOAD, "name bytes"); return;
    }
  }
  if (!valid_nonce(p->nonce)) {
    send_rst(s, c, LAB_BAD_PAYLOAD, "nonce cero"); return;
  }

  for (size_t i = 0; i < MAX_CLIENTS; i++) {
    if (s->c[i].used && !memcmp(s->c[i].cnonce, p->nonce, 16)) {
      send_rst(s, c, LAB_DUP_NONCE, "duplicate nonce");
      return;
    }
  }
  uint8_t rnd[32];
  if (!lab_random_bytes(rnd, sizeof rnd)) {
    send_rst(s, c, LAB_BUSY, "entropy unavailable");
    return;
  }
  memcpy(c->session, rnd, sizeof c->session);
  memcpy(c->cnonce, p->nonce, sizeof c->cnonce);
  memcpy(c->snonce, rnd + LAB_SESSION_LEN, sizeof c->snonce);
  memcpy(c->hello, pay, sizeof c->hello);
  if (!send_hello_ack(s, c, c->snonce)) return;
  c->used = 1;
  c->state = ST_OPEN;
  c->evidence.open = 1;
  memcpy(c->evidence.session, c->session, 16);
  memcpy(c->evidence.instance, c->cnonce, 16);
  c->sequence.next = 1;
  memset(c->sequence.seen, 0, sizeof c->sequence.seen);
  memcpy(c->name, p->name, 24);
  c->open_t = lab_now_ms();
  c->last_rx = c->open_t;
}

/* Validate against copies: rejected evidence never consumes sequence or request. */
static void do_evidence(server_t *s, client_t *c, const lab_hdr_t *h, const uint8_t *payload) {
  lab_evidence_state_t next = c->evidence;
  lab_sequence_t sequence = c->sequence;
  lab_decision_t result = { .status = LAB_REJECTED };
  memcpy(result.session,c->session,16);
  if (h->kind == LAB_REQUEST) {
    lab_request_t request;
    if (!lab_payload_parse(payload,h->len,h->kind,&request)) return;
    result.request_id = request.request_id;
    result.reason = lab_policy_request(&next,&s->policy,&request,lab_now_ms());
  } else {
    lab_observation_t observation;
    if (!lab_payload_parse(payload,h->len,h->kind,&observation)) return;
    result.request_id = observation.request_id;
    result.reason = lab_policy_observation(&next,&s->policy,&observation,lab_now_ms());
  }
  if (!result.reason) result.reason = lab_sequence_accept(&sequence,h->seq);
  if (!result.reason) {
    c->evidence = next; c->sequence = sequence; c->last_rx = lab_now_ms();
    result.status = h->kind == LAB_REQUEST ? LAB_PENDING : LAB_ACCEPTED;
  }
  lab_hdr_t response = { .magic = LAB_MAGIC, .version = LAB_VERSION, .kind = LAB_DECISION,
                         .seq = h->seq, .len = LAB_DECISION_LEN };
  uint8_t wire[16 + LAB_DECISION_LEN];
  lab_hdr_pack(wire,&response); lab_payload_pack(wire+16,LAB_DECISION_LEN,LAB_DECISION,&result);
  (void)send_datagram(s,c,wire,sizeof wire);
  log_json(s,"decision",c,1,h,result.reason,lab_reason_name(result.reason));
  if (result.reason == LAB_CLOSING) release_client(c);
}

/* datagrama en estado OPEN */
static void do_open(server_t *s, client_t *c, const uint8_t *dat, uint32_t n) {
  if (n > LAB_MAX_DATAGRAM) {
    send_rst(s, c, LAB_TOO_BIG, ">128 B");
    log_json(s, "drop", c, 0, 0, LAB_TOO_BIG, ">128 B");
    return;
  }
  lab_hdr_t h;
  if (!lab_hdr_parse(dat, n, &h)) {
    send_rst(s, c, LAB_BAD_MAGIC, "hdr");
    log_json(s, "drop", c, 0, 0, LAB_BAD_MAGIC, "hdr");
    return;
  }
  if (h.magic != LAB_MAGIC || h.version != LAB_VERSION) {
    uint32_t r = h.magic != LAB_MAGIC ? LAB_BAD_MAGIC : LAB_BAD_VERSION;
    send_rst(s, c, r, h.magic != LAB_MAGIC ? "magic" : "version");
    log_json(s, "drop", c, 1, &h, r, "hdr");
    return;
  }

  if (h.len != n - 16 || lab_payload_len(h.kind) != h.len) {
    send_rst(s, c, LAB_BAD_LEN, h.kind == LAB_BYE ? "bye len" : h.kind == LAB_RST ? "rst len" : "len != real"); return;
  }
  if (h.flags) { send_rst(s, c, LAB_BAD_PAYLOAD, "flags"); return; }
  const uint8_t *pay = dat + 16;
  if (h.kind == LAB_HELLO) {
    if (!h.seq && !memcmp(pay, c->hello, LAB_HELLO_LEN)) {
      (void)send_hello_ack(s, c, c->snonce);
      return;
    }
    send_rst(s, c, LAB_DUP_SESSION, "otro HELLO");
    log_json(s, "drop", c, 1, &h, LAB_DUP_SESSION, "otro HELLO");
    return;
  }
  if (h.kind == LAB_REQUEST || h.kind == LAB_OBSERVATION) { do_evidence(s,c,&h,pay); return; }
  if (h.kind == LAB_HELLO_ACK || h.kind == LAB_PONG || h.kind == LAB_DECISION) {
    send_rst(s, c, LAB_BAD_KIND, "kind c2s");
    log_json(s, "drop", c, 1, &h, LAB_BAD_KIND, "kind c2s");
    return;
  }
  if (h.kind == LAB_PING) {
    if (n - 16 > LAB_PING_LEN) {
      send_rst(s, c, LAB_TOO_BIG, "ping >40");
      log_json(s, "drop", c, 1, &h, LAB_TOO_BIG, "ping >40");
      return;
    }
    if (n - 16 < LAB_PING_LEN) {
      send_rst(s, c, LAB_TRUNCATED, "ping corto");
      log_json(s, "drop", c, 1, &h, LAB_TRUNCATED, "ping corto");
      return;
    }
    lab_ping_t ping;
    if (!lab_payload_parse(pay, n - 16, LAB_PING, &ping)) return;
    const lab_ping_t *p = &ping;
    if (memcmp(p->session, c->session, 16)) {
      send_rst(s, c, LAB_BAD_SESSION, "session !=");
      log_json(s, "drop", c, 1, &h, LAB_BAD_SESSION, "session !=");
      return;
    }
    uint32_t reason = lab_sequence_accept(&c->sequence, h.seq);
    if (reason != LAB_OK) {
      send_rst(s, c, reason, lab_reason_name(reason));
      if (reason == LAB_CLOSING) release_client(c);
      return;
    }
    c->last_rx = lab_now_ms();

    lab_pong_t pp;
    memset(&pp, 0, sizeof pp);
    pp.stamp = p->stamp;
    memcpy(pp.echo, p->nonce, 16);
    lab_hdr_t ph;
    memset(&ph, 0, sizeof ph);
    ph.magic = LAB_MAGIC; ph.version = LAB_VERSION;
    ph.kind = LAB_PONG;
    ph.len = LAB_PONG_LEN;
    uint8_t buf[16 + LAB_PONG_LEN];
    lab_hdr_pack(buf, &ph);
    (void)lab_payload_pack(buf + 16, sizeof buf - 16, LAB_PONG, &pp);
    if (!send_datagram(s, c, buf, sizeof buf)) return;
    log_json(s, "pong", c, 1, &h, LAB_OK, "ping");
    return;
  }
  if (h.kind == LAB_BYE) {
    if (h.len != LAB_BYE_LEN || n - 16 != LAB_BYE_LEN) {
      send_rst(s, c, LAB_BAD_LEN, "bye len");
      log_json(s, "drop", c, 1, &h, LAB_BAD_LEN, "bye len");
      return;
    }
    if (memcmp(pay, c->session, LAB_SESSION_LEN)) {
      send_rst(s, c, LAB_BAD_SESSION, "session !="); return;
    }
    send_rst(s, c, LAB_OK, "bye");
    log_json(s, "bye", c, 1, &h, LAB_OK, "bye");
    release_client(c);
    return;
  }
  if (h.kind == LAB_RST) {
    if (h.len != LAB_RST_LEN || n - 16 != LAB_RST_LEN) {
      send_rst(s, c, LAB_BAD_LEN, "rst len");
      log_json(s, "drop", c, 1, &h, LAB_BAD_LEN, "rst len");
      return;
    }
    lab_rst_t rst;
    if (!lab_payload_parse(pay, n - 16, LAB_RST, &rst)) return;
    if (memcmp(rst.session, c->session, LAB_SESSION_LEN)) {
      send_rst(s, c, LAB_BAD_SESSION, "session !="); return;
    }
    if (rst.len > sizeof rst.msg) {
      send_rst(s, c, LAB_BAD_PAYLOAD, "rst msg len");
      log_json(s, "drop", c, 1, &h, LAB_BAD_PAYLOAD, "rst msg len");
      return;
    }
    send_rst(s, c, LAB_OK, "rst");
    log_json(s, "ack", c, 1, &h, LAB_OK, "rst");
    release_client(c);
    return;
  }
  send_rst(s, c, LAB_BAD_KIND, "kind");
  log_json(s, "drop", c, 1, &h, LAB_BAD_KIND, "kind");
}

/* datagrama en estado NEW: debe ser HELLO */
static void do_new(server_t *s, client_t *c, const uint8_t *dat, uint32_t n) {
  if (n < 16 || n > LAB_MAX_DATAGRAM) {
    send_rst(s, c, n < 16 ? LAB_BAD_MAGIC
                        : (n > (16 + 64) ? LAB_TOO_BIG : LAB_BAD_LEN),
              n < 16 ? "hdr" : (n > (16 + 64) ? ">64 B" : "hello len"));
    log_json(s, "drop", c, 0, 0, n < 16 ? LAB_BAD_MAGIC : (n > 128 ? LAB_TOO_BIG : LAB_BAD_LEN), "tama");
    return;
  }
  if (dat[0] != LAB_MAGIC) {
    send_rst(s, c, LAB_BAD_MAGIC, "magic");
    log_json(s, "drop", c, 0, 0, LAB_BAD_MAGIC, "magic");
    return;
  }
  if (dat[1] != LAB_VERSION) {
    send_rst(s, c, LAB_BAD_VERSION, "version");
    log_json(s, "drop", c, 0, 0, LAB_BAD_VERSION, "version");
    return;
  }
  if (dat[2] != LAB_HELLO) {
    send_rst(s, c, LAB_BAD_KIND, "HELLO primero");
    log_json(s, "drop", c, 0, 0, LAB_BAD_KIND, "HELLO primero");
    return;
  }
  lab_hdr_t h;
  if (!lab_hdr_parse(dat, n, &h)) {
    send_rst(s, c, LAB_BAD_MAGIC, "hdr");
    log_json(s, "drop", c, 0, NULL, LAB_BAD_MAGIC, "hdr");
    return;
  }
  if (h.len != n - 16) {
    send_rst(s, c, LAB_BAD_LEN, "len != real");
    log_json(s, "drop", c, 1, &h, LAB_BAD_LEN, "len != real");
    return;
  }
  if (h.flags || h.seq) { send_rst(s, c, LAB_BAD_PAYLOAD, "hello header"); return; }
  do_hello(s, c, dat + 16, n - 16);
}

static void sweep_timeouts(server_t *s) {
  uint64_t now = lab_now_ms();
  for (int i = 0; i < MAX_CLIENTS; i++) {
    client_t *c = &s->c[i];
    if (!c->used || c->state != ST_OPEN) continue;
    if (now - c->last_rx > s->timeout_ms) {
      send_rst(s, c, LAB_TIMEOUT, "timeout");
      release_client(c);
      s->n_timeout++;
    }
  }
}

static void usage(void) {
  fprintf(stderr,
    "lab-server --host 127.0.0.1 --port 7777 [--timeout-ms 2000] [--max 32] [-v]\n");
}

int main(int argc, char **argv) {
  server_t s;
  memset(&s, 0, sizeof s);
  s.port = 7777;
  s.timeout_ms = 2000;
  s.max_clients = MAX_CLIENTS;
  s.policy = (lab_policy_t){ .capabilities = 7, .evidence_class = LAB_SELF_REPORTED, .request_timeout_ms = 1000 };

  for (int i = 1; i < argc; i++) {
    if (!strcmp(argv[i], "--host") && i + 1 < argc) {
      if (strlen(argv[++i]) >= 16 ||
          inet_pton(AF_INET, argv[i], &s.c[0].addr.sin_addr) != 1 ||
          (ntohl(s.c[0].addr.sin_addr.s_addr) >> 24) != 127) {
        fprintf(stderr, "host\n"); return 2;
      }
      strncpy(s.host, argv[i], 15);
    } else if (!strcmp(argv[i], "--port") && i + 1 < argc) {
      uint32_t port;
      if (!lab_parse_u32(argv[++i], 1, 65535, &port)) { usage(); return 2; }
      s.port = (uint16_t)port;
    } else if (!strcmp(argv[i], "--timeout-ms") && i + 1 < argc) {
      if (!lab_parse_u32(argv[++i], 1, 60000, &s.timeout_ms)) { usage(); return 2; }
    } else if (!strcmp(argv[i], "--max") && i + 1 < argc) {
      if (!lab_parse_u32(argv[++i], 1, MAX_CLIENTS, &s.max_clients)) { usage(); return 2; }
    } else if (!strcmp(argv[i], "--origin") && i + 1 < argc) {
      const char *origin = argv[++i];
      if (!strcmp(origin,"linux")) s.policy.origin = LAB_ORIGIN_LINUX;
      else if (!strcmp(origin,"windows")) s.policy.origin = LAB_ORIGIN_WINDOWS;
      else if (!strcmp(origin,"any")) s.policy.origin = 0;
      else return 2;
    } else if (!strcmp(argv[i], "--capabilities") && i + 1 < argc) {
      uint32_t mask;
      if (!lab_parse_u32(argv[++i],0,7,&mask)) return 2;
      s.policy.capabilities = (uint8_t)mask;
    } else if (!strcmp(argv[i], "--request-ms") && i + 1 < argc) {
      if (!lab_parse_u32(argv[++i],1,60000,&s.policy.request_timeout_ms)) return 2;
    } else if (!strcmp(argv[i], "--require-attestation")) {
      s.policy.evidence_class = 2; /* No attestation provider is implemented. */
    } else if (!strcmp(argv[i], "-v") || !strcmp(argv[i], "--verbose")) {
      s.verbose = 1;
    } else { usage(); return 2; }
  }
  if (s.max_clients > MAX_CLIENTS) s.max_clients = MAX_CLIENTS;

  struct sigaction action = {0};
  action.sa_handler = stop_server;
  sigemptyset(&action.sa_mask);
  if (sigaction(SIGINT, &action, NULL) || sigaction(SIGTERM, &action, NULL)) return 1;

  s.fd = socket(AF_INET, SOCK_DGRAM | SOCK_CLOEXEC, 0);
  if (s.fd < 0) { perror("socket"); return 1; }

  struct sockaddr_in ba;
  memset(&ba, 0, sizeof ba);
  ba.sin_family = AF_INET;
  ba.sin_addr.s_addr = inet_addr(s.host[0] ? s.host : "127.0.0.1");
  ba.sin_port = htons(s.port);
  if (bind(s.fd, (struct sockaddr *)&ba, sizeof ba) < 0) {
    fprintf(stderr, "bind %s:%u: %s\n", s.host, s.port, strerror(errno));
    close(s.fd); return 1;
  }

  if (s.verbose) {
    printf("{\"ev\":\"boot\",\"host\":\"%s\",\"port\":%u,\"timeout_ms\":%u,\"max\":%u}\n",
            s.host, s.port, s.timeout_ms, s.max_clients);
    fflush(stdout);
  }

  struct pollfd pfd = { .fd = s.fd, .events = POLLIN };

  s.running = 1;
  while (s.running && !stopping) {
    pfd.revents = 0;
    int pr = poll(&pfd, 1, 100);
    if (pr < 0) {
      if (errno == EINTR) continue;
      s.io_error = 1; break;
    }
    sweep_timeouts(&s);
    if (!s.running) break;
    if (pr == 0) continue;
    if (pfd.revents & POLLIN) {
      for (int k = 0; k < 16; k++) {
        uint8_t dat[LAB_MAX_DATAGRAM];
        struct sockaddr_in from;
        socklen_t flen = sizeof from;
        ssize_t n = recvfrom(s.fd, dat, sizeof dat, MSG_DONTWAIT | MSG_TRUNC,
                              (struct sockaddr *)&from, &flen);
        if (n < 0) {
          if (errno == EAGAIN || errno == EINTR) break;
          s.io_error = 1; s.running = 0; break;
        }

        s.n_rx++;

        /* loopback only: 127.x.x.x */
        if ((ntohl(from.sin_addr.s_addr) >> 24u) != 127u) {
          client_t tmp; memset(&tmp, 0, sizeof tmp);
          tmp.addr = from;
          send_rst(&s, &tmp, LAB_BAD_MAGIC, "no loopback");
          continue;
        }

        client_t *c = 0;
        for (int i = 0; i < MAX_CLIENTS; i++) {
          if (s.c[i].used &&
              s.c[i].addr.sin_family == from.sin_family &&
              s.c[i].addr.sin_addr.s_addr == from.sin_addr.s_addr &&
              s.c[i].addr.sin_port == from.sin_port) { c = &s.c[i]; break; }
        }
        if (!c) {
          uint32_t n_used = 0;
          for (int i = 0; i < MAX_CLIENTS; i++) n_used += s.c[i].used != 0;
          if (n_used >= s.max_clients) {
            client_t tmp; memset(&tmp, 0, sizeof tmp);
            tmp.addr = from;
            send_rst(&s, &tmp, LAB_BUSY, "max alcanzado");
            continue;
          }
          for (int i = 0; i < MAX_CLIENTS; i++)
            if (!s.c[i].used) { c = &s.c[i]; break; }
        }
        if (!c) {
          client_t tmp; memset(&tmp, 0, sizeof tmp);
          tmp.addr = from;
          send_rst(&s, &tmp, LAB_BUSY, "max alcanzado");
          continue;
        }
        if (!c->used) {
          /* slot nuevo: validar primero, marcar used en do_hello */
          memset(c, 0, sizeof *c);
        }
        c->addr = from;

        if ((size_t)n > sizeof dat) {
          send_rst(&s, c, LAB_TOO_BIG, ">128 B");
          continue;
        }
        if (c->state == ST_NEW)       do_new(&s, c, dat, (uint32_t)n);
        else if (c->state == ST_OPEN) do_open(&s, c, dat, (uint32_t)n);

      }
    }
    if (pfd.revents & (POLLHUP | POLLERR | POLLNVAL)) { s.io_error = 1; break; }
  }

  for (int i = 0; i < MAX_CLIENTS; i++)
    if (s.c[i].used)
      send_rst(&s, &s.c[i], LAB_CLOSING, "shutdown");

  if (s.verbose) {
    printf("{\"ev\":\"exit\",\"rx\":%llu,\"acks\":%llu,\"rst\":%llu,\"timeout\":%llu}\n",
            (unsigned long long)s.n_rx,             (unsigned long long)s.n_acks,
            (unsigned long long)s.n_rst, (unsigned long long)s.n_timeout);
    fflush(stdout);
  }
  if (close(s.fd) < 0) s.io_error = 1;
  return s.io_error ? 1 : 0;
}
