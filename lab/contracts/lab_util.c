/*
 * lab/contracts/lab_util.c
 * Tablas y helpers del contrato.
 */
#define _POSIX_C_SOURCE 200809L
#include "../contracts/lab.h"
#include "evidence.h"
#include <time.h>
#include <errno.h>
#ifdef _WIN32
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <bcrypt.h>
#else
#include <sys/random.h>
#endif

uint64_t lab_now_ms(void) {
#ifdef _WIN32
  return GetTickCount64();
#else
  struct timespec ts;
  if (clock_gettime(CLOCK_MONOTONIC, &ts) != 0) return 0;
  return (uint64_t)ts.tv_sec * 1000ull + (uint64_t)ts.tv_nsec / 1000000ull;
#endif
}


static const char *const kind_names[256] = {
  [LAB_HELLO]      = "HELLO",
  [LAB_HELLO_ACK]  = "HELLO_ACK",
  [LAB_PING]       = "PING",
  [LAB_PONG]       = "PONG",
  [LAB_RST]        = "RST",
  [LAB_BYE]        = "BYE",
  [LAB_REQUEST] = "REQUEST", [LAB_OBSERVATION] = "OBSERVATION", [LAB_DECISION] = "DECISION",
};

static const char *const reason_names[256] = {
  [LAB_OK]               = "OK",
  [LAB_BAD_MAGIC]        = "BAD_MAGIC",
  [LAB_BAD_VERSION]      = "BAD_VERSION",
  [LAB_BAD_KIND]         = "BAD_KIND",
  [LAB_BAD_LEN]          = "BAD_LEN",
  [LAB_BAD_PAYLOAD]      = "BAD_PAYLOAD",
  [LAB_DUP_SESSION]      = "DUP_SESSION",
  [LAB_UNKNOWN_SESSION]  = "UNKNOWN_SESSION",
  [LAB_BAD_SESSION]      = "BAD_SESSION",
  [LAB_BAD_SEQ]          = "BAD_SEQ",
  [LAB_REPLAY]           = "REPLAY",
  [LAB_TOO_BIG]          = "TOO_BIG",
  [LAB_TRUNCATED]        = "TRUNCATED",
  [LAB_STALE]            = "STALE",
  [LAB_BUSY]             = "BUSY",
  [LAB_DUP_NONCE]        = "DUP_NONCE",
  [LAB_CLOSING]          = "CLOSING",
  [LAB_TIMEOUT]          = "TIMEOUT",
  [LAB_ECHO]             = "ECHO",
  [LAB_ORIGIN_MISMATCH] = "ORIGIN_MISMATCH", [LAB_UNSUPPORTED] = "UNSUPPORTED",
  [LAB_INSUFFICIENT] = "INSUFFICIENT", [LAB_OLD_INSTANCE] = "OLD_INSTANCE",
  [LAB_EXPIRED] = "EXPIRED", [LAB_UNKNOWN_REQUEST] = "UNKNOWN_REQUEST",
};

const char *lab_kind_name(uint8_t kind) {
  return kind_names[kind] ? kind_names[kind] : "?";
}

const char *lab_reason_name(uint32_t reason) {
  return reason < LAB_REASON_COUNT && reason_names[reason]
    ? reason_names[reason] : "?";
}

static void put32(uint8_t *p, uint32_t v) {
  p[0] = (uint8_t)(v);
  p[1] = (uint8_t)(v >> 8);
  p[2] = (uint8_t)(v >> 16);
  p[3] = (uint8_t)(v >> 24);
}

static uint32_t get32(const uint8_t *p) {
  return (uint32_t)p[0] | ((uint32_t)p[1] << 8) |
         ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}

int lab_hdr_pack(uint8_t *out, const lab_hdr_t *h) {
  if (!out || !h) return 0;
  out[0] = h->magic;
  out[1] = h->version;
  out[2] = h->kind;
  out[3] = h->flags;
  put32(out + 4, h->seq);
  put32(out + 8, h->len);
  for (int i = 0; i < 4; i++) out[12 + i] = 0xAA;
  return 1;
}

int lab_hdr_parse(const uint8_t *in, size_t n, lab_hdr_t *out) {
  if (!in || !out || n < 16) return 0;
  for (int i = 0; i < 4; i++) {
    if (in[12 + i] != 0xAA) return 0;
  }
  out->magic   = in[0];
  out->version = in[1];
  out->kind    = in[2];
  out->flags   = in[3];
  out->seq     = get32(in + 4);
  out->len     = get32(in + 8);
  memcpy(out->pad, in + 12, sizeof out->pad);
  return 1;
}

size_t lab_payload_len(uint8_t kind) {
  switch (kind) {
    case LAB_HELLO:      return LAB_HELLO_LEN;
    case LAB_HELLO_ACK:  return LAB_HELLO_ACK_LEN;
    case LAB_PING:       return LAB_PING_LEN;
    case LAB_PONG:       return LAB_PONG_LEN;
    case LAB_RST:        return LAB_RST_LEN;
    case LAB_BYE:        return LAB_BYE_LEN;
    case LAB_REQUEST: return LAB_REQUEST_LEN;
    case LAB_OBSERVATION: return LAB_OBSERVATION_LEN;
    case LAB_DECISION: return LAB_DECISION_LEN;
    default:             return 0;
  }
}

uint32_t lab_sequence_accept(lab_sequence_t *state, uint32_t seq) {
  if (!seq) return LAB_BAD_SEQ;
  if (seq == UINT32_MAX || state->next == UINT32_MAX) return LAB_CLOSING;
  if (seq >= state->next) {
    if (seq - state->next > 8u) return LAB_BAD_SEQ;
    state->next = seq + 1u;
  } else if (state->next - seq > 16u) return LAB_BAD_SEQ;
  else if (state->seen[seq % 16u] == seq) return LAB_REPLAY;
  state->seen[seq % 16u] = seq;
  return LAB_OK;
}

int lab_parse_u32(const char *text, uint32_t minimum, uint32_t maximum, uint32_t *out) {
  uint32_t value = 0;
  if (!text || !*text || !out) return 0;
  for (const unsigned char *p = (const unsigned char *)text; *p; ++p) {
    if (*p < '0' || *p > '9') return 0;
    uint32_t digit = (uint32_t)(*p - '0');
    if (value > maximum / 10u || (value == maximum / 10u && digit > maximum % 10u)) return 0;
    value = value * 10u + digit;
  }
  if (value < minimum) return 0;
  *out = value;
  return 1;
}

static void put64(uint8_t *p, uint64_t v) {
  put32(p, (uint32_t)v); put32(p + 4, (uint32_t)(v >> 32));
}
static uint64_t get64(const uint8_t *p) {
  return (uint64_t)get32(p) | ((uint64_t)get32(p + 4) << 32);
}
int lab_payload_pack(uint8_t *out, size_t capacity, uint8_t kind, const void *payload) {
  if (kind >= LAB_REQUEST && kind <= LAB_DECISION) return lab_evidence_pack(out, capacity, kind, payload);
  size_t n = lab_payload_len(kind);
  if (!out || !payload || !n || capacity < n) return 0;
  switch (kind) {
    case LAB_HELLO: {
      const lab_hello_t *p = payload;
      put32(out, p->app_id); memcpy(out+4,p->app,16); memcpy(out+20,p->name,24); memcpy(out+44,p->nonce,16); break;
    }
    case LAB_HELLO_ACK: {
      const lab_hello_ack_t *p = payload;
      put32(out,p->result); put32(out+4,p->reason); memcpy(out+8,p->session,16); memcpy(out+24,p->snonce,16); memcpy(out+40,p->cnonce,16); break;
    }
    case LAB_PING: {
      const lab_ping_t *p = payload;
      memcpy(out,p->session,16); memcpy(out+16,p->nonce,16); put64(out+32,p->stamp); break;
    }
    case LAB_PONG: {
      const lab_pong_t *p = payload;
      put64(out,p->stamp); memcpy(out+8,p->echo,16); put32(out+24,p->pad); break;
    }
    case LAB_RST: {
      const lab_rst_t *p = payload;
      memcpy(out,p->session,16); put32(out+16,p->reason); put32(out+20,p->len); memcpy(out+24,p->msg,36); break;
    }
    case LAB_BYE: {
      const lab_bye_t *p = payload;
      memcpy(out,p->session,16); put32(out+16,p->reason); put32(out+20,p->pad); break;
    }
    default: return 0;
  }
  return 1;
}
int lab_payload_parse(const uint8_t *in, size_t length, uint8_t kind, void *payload) {
  if (kind >= LAB_REQUEST && kind <= LAB_DECISION) return lab_evidence_parse(in, length, kind, payload);
  if (!in || !payload || !length || length != lab_payload_len(kind)) return 0;
  switch (kind) {
    case LAB_HELLO: {
      lab_hello_t p = {0}; p.app_id=get32(in); memcpy(p.app,in+4,16); memcpy(p.name,in+20,24); memcpy(p.nonce,in+44,16); *(lab_hello_t *)payload=p; break;
    }
    case LAB_HELLO_ACK: {
      lab_hello_ack_t p = {0}; p.result=get32(in); p.reason=get32(in+4); memcpy(p.session,in+8,16); memcpy(p.snonce,in+24,16); memcpy(p.cnonce,in+40,16); *(lab_hello_ack_t *)payload=p; break;
    }
    case LAB_PING: {
      lab_ping_t p = {0}; memcpy(p.session,in,16); memcpy(p.nonce,in+16,16); p.stamp=get64(in+32); *(lab_ping_t *)payload=p; break;
    }
    case LAB_PONG: {
      lab_pong_t p = {0}; p.stamp=get64(in); memcpy(p.echo,in+8,16); p.pad=get32(in+24); *(lab_pong_t *)payload=p; break;
    }
    case LAB_RST: {
      lab_rst_t p = {0}; memcpy(p.session,in,16); p.reason=get32(in+16); p.len=get32(in+20); memcpy(p.msg,in+24,36); *(lab_rst_t *)payload=p; break;
    }
    case LAB_BYE: {
      lab_bye_t p = {0}; memcpy(p.session,in,16); p.reason=get32(in+16); p.pad=get32(in+20); *(lab_bye_t *)payload=p; break;
    }
    default: return 0;
  }
  return 1;
}

int lab_random_bytes(uint8_t *out, size_t size) {
#ifdef _WIN32
  if (size > ULONG_MAX) return 0;
  return BCryptGenRandom(NULL, out, (ULONG)size, BCRYPT_USE_SYSTEM_PREFERRED_RNG) >= 0;
#else
  size_t offset = 0;
  while (offset < size) {
    ssize_t count = getrandom(out + offset, size - offset, GRND_NONBLOCK);
    if (count < 0 && errno == EINTR) continue;
    if (count <= 0) return 0;
    offset += (size_t)count;
  }
  return 1;
#endif
}
