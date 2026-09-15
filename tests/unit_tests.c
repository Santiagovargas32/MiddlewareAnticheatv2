/* Tests of the public wire helpers. Server sessions belong in integration tests. */
#include "../lab/contracts/lab.h"
#include <stdio.h>
#include <string.h>

#define CHECK(expression) do { \
  if (!(expression)) { \
    fprintf(stderr, "%s:%d: %s\n", __FILE__, __LINE__, #expression); \
    return 0; \
  } \
} while (0)

/* Independent v2 PONG fixture: kind 0x11, little-endian sequence and length. */
static const uint8_t pong_wire[16] = {
  0x4c, 0x02, 0x11, 0x00, 0x78, 0x56, 0x34, 0x12,
  0x1c, 0x00, 0x00, 0x00, 0xaa, 0xaa, 0xaa, 0xaa
};

static int encode_pong(void) {
  lab_hdr_t h = { .magic = LAB_MAGIC, .version = LAB_VERSION,
    .kind = LAB_PONG, .seq = 0x12345678, .len = LAB_PONG_LEN };
  uint8_t bytes[18];
  memset(bytes, 0x5a, sizeof bytes);
  CHECK(lab_hdr_pack(bytes + 1, &h));
  CHECK(memcmp(bytes + 1, pong_wire, sizeof pong_wire) == 0);
  CHECK(bytes[0] == 0x5a && bytes[17] == 0x5a);
  return 1;
}

static int decode_pong(void) {
  lab_hdr_t h;
  memset(&h, 0x5a, sizeof h); /* Parser must not read the destination's padding. */
  CHECK(lab_hdr_parse(pong_wire, sizeof pong_wire, &h));
  CHECK(h.magic == LAB_MAGIC && h.version == LAB_VERSION);
  CHECK(h.kind == LAB_PONG && h.flags == 0);
  CHECK(h.seq == 0x12345678 && h.len == 28);
  CHECK(memcmp(h.pad, pong_wire + 12, sizeof h.pad) == 0);
  uint8_t encoded[16];
  CHECK(lab_hdr_pack(encoded, &h));
  CHECK(memcmp(encoded, pong_wire, sizeof encoded) == 0);
  return 1;
}

static int reject_bad_headers(void) {
  lab_hdr_t out, before;
  memset(&out, 0x5a, sizeof out);
  memcpy(&before, &out, sizeof before);
  for (size_t n = 0; n < sizeof pong_wire; n++) {
    CHECK(!lab_hdr_parse(pong_wire, n, &out));
    CHECK(memcmp(&out, &before, sizeof out) == 0);
  }
  for (size_t i = 12; i < sizeof pong_wire; i++) {
    uint8_t malformed[16];
    memcpy(malformed, pong_wire, sizeof malformed);
    malformed[i] = 0;
    CHECK(!lab_hdr_parse(malformed, sizeof malformed, &out));
    CHECK(memcmp(&out, &before, sizeof out) == 0);
  }
  return 1;
}

static int null_arguments(void) {
  lab_hdr_t h = {0};
  uint8_t wire[16] = {0};
  CHECK(!lab_hdr_pack(NULL, &h));
  CHECK(!lab_hdr_pack(wire, NULL));
  CHECK(!lab_hdr_parse(NULL, sizeof wire, &h));
  CHECK(!lab_hdr_parse(wire, sizeof wire, NULL));
  return 1;
}

static int wire_catalog(void) {
  const uint8_t kinds[] = {0x01, 0x02, 0x10, 0x11, 0x20, 0x30};
  const size_t lengths[] = {60, 56, 40, 28, 60, 24};
  const char *names[] = {"HELLO", "HELLO_ACK", "PING", "PONG", "RST", "BYE"};
  for (size_t i = 0; i < sizeof kinds; i++) {
    CHECK(lab_payload_len(kinds[i]) == lengths[i]);
    CHECK(strcmp(lab_kind_name(kinds[i]), names[i]) == 0);
  }
  CHECK(lab_payload_len(0) == 0 && lab_payload_len(0xff) == 0);
  CHECK(strcmp(lab_kind_name(0xff), "?") == 0);
  CHECK(strcmp(lab_reason_name(LAB_OK), "OK") == 0);
  CHECK(strcmp(lab_reason_name(LAB_TIMEOUT), "TIMEOUT") == 0);
  CHECK(strcmp(lab_reason_name(UINT32_MAX), "?") == 0);
  for (uint32_t i = 0; i < LAB_REASON_COUNT; i++) {
    CHECK(strcmp(lab_reason_name(i), "?") != 0);
    for (uint32_t j = i + 1; j < LAB_REASON_COUNT; j++)
      CHECK(strcmp(lab_reason_name(i), lab_reason_name(j)) != 0);
  }
  return 1;
}

static int sequence_history(void) {
  lab_sequence_t seq = { .next = 1 };
  CHECK(lab_sequence_accept(&seq, 1) == LAB_OK);
  CHECK(lab_sequence_accept(&seq, 1) == LAB_REPLAY);
  CHECK(lab_sequence_accept(&seq, 3) == LAB_OK);
  CHECK(lab_sequence_accept(&seq, 2) == LAB_OK);
  CHECK(lab_sequence_accept(&seq, 2) == LAB_REPLAY);
  for (uint32_t i = 4; i < 50; ++i) CHECK(lab_sequence_accept(&seq, i) == LAB_OK);
  CHECK(lab_sequence_accept(&seq, 1) == LAB_BAD_SEQ);
  CHECK(lab_sequence_accept(&seq, 40) == LAB_REPLAY);
  CHECK(lab_sequence_accept(&seq, 58) == LAB_OK);
  CHECK(lab_sequence_accept(&seq, 55) == LAB_OK);
  CHECK(lab_sequence_accept(&seq, 55) == LAB_REPLAY);
  CHECK(lab_sequence_accept(&seq, 68) == LAB_BAD_SEQ);
  seq.next = UINT32_MAX - 1u;
  CHECK(lab_sequence_accept(&seq, UINT32_MAX - 1u) == LAB_OK);
  CHECK(lab_sequence_accept(&seq, UINT32_MAX) == LAB_CLOSING);
  CHECK(lab_sequence_accept(&seq, 1) == LAB_CLOSING);
  CHECK(seq.next == UINT32_MAX);
  return 1;
}

int main(void) {
  const char *names[] = {"encode PONG", "decode PONG", "reject malformed headers",
                         "null arguments", "wire catalog", "sequence history"};
  int (*tests[])(void) = {encode_pong, decode_pong, reject_bad_headers,
                        null_arguments, wire_catalog, sequence_history};
  int failed = 0;
  for (size_t i = 0; i < sizeof tests / sizeof tests[0]; i++) {
    int ok = tests[i]();
    printf("[%s] %s\n", ok ? "PASS" : "FAIL", names[i]);
    failed += !ok;
  }
  return failed ? 1 : 0;
}
