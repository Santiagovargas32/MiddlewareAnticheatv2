/*
 * lab/contracts/lab.h
 *
 * Contrato del laboratorio: mensajes propios entre cliente, adaptador y
 * servidor. No es EAC/EOS: campos de nuestro diseño.
 *
 * Datagrama = header (16 B) + payload acotado por kind.
 * Todo little-endian.
 */
#pragma once

#include <stdint.h>
#include <stddef.h>
#include <string.h>

#define LAB_MAGIC   0x4Cu /* 'L' */
#define LAB_VERSION 2u

#define LAB_MAX_DATAGRAM 128u
#define LAB_SESSION_LEN  16u

/* Kinds */
enum {
  LAB_HELLO      = 0x01u,
  LAB_HELLO_ACK  = 0x02u,
  LAB_PING       = 0x10u,
  LAB_PONG       = 0x11u,
  LAB_RST        = 0x20u,
  LAB_BYE        = 0x30u,
};

/* Reasons (los lleva RST / HELLO_ACK) */
enum {
  LAB_OK               = 0u,
  LAB_BAD_MAGIC        = 1u,
  LAB_BAD_VERSION      = 2u,
  LAB_BAD_KIND         = 3u,
  LAB_BAD_LEN          = 4u,
  LAB_BAD_PAYLOAD      = 5u,
  LAB_DUP_SESSION      = 6u,
  LAB_UNKNOWN_SESSION  = 7u,
  LAB_BAD_SESSION      = 8u,
  LAB_BAD_SEQ          = 9u,
  LAB_REPLAY           = 10u,
  LAB_TOO_BIG          = 11u,
  LAB_TRUNCATED        = 12u,
  LAB_STALE            = 13u,
  LAB_BUSY             = 14u,
  LAB_DUP_NONCE        = 15u,
  LAB_CLOSING          = 16u,
  LAB_TIMEOUT          = 17u,
  LAB_ECHO             = 18u,
  LAB_ORIGIN_MISMATCH   = 19u,
  LAB_UNSUPPORTED       = 20u,
  LAB_INSUFFICIENT      = 21u,
  LAB_OLD_INSTANCE      = 22u,
  LAB_EXPIRED           = 23u,
  LAB_UNKNOWN_REQUEST   = 24u,
  LAB_REASON_COUNT     = 25u
};

#define LAB_HELLO_LEN    60u
#define LAB_HELLO_ACK_LEN 56u
#define LAB_PING_LEN     40u
#define LAB_PONG_LEN     28u
#define LAB_RST_LEN      60u
#define LAB_BYE_LEN      24u

#define LAB_APP_NAME "LabClient"

#define LAB_APP_ID 0x4C414201u /* 'LAB1' */

/* Header: 16 B */
typedef struct {
  uint8_t  magic;
  uint8_t  version;
  uint8_t  kind;
  uint8_t  flags;
  uint32_t seq;
  uint32_t len;
  uint8_t  pad[4];
} lab_hdr_t;

/* HELLO (cliente -> servidor), 60 B */
typedef struct {
  uint32_t app_id;
  char      app[16];
  char      name[24];
  uint8_t   nonce[16];
} lab_hello_t;

/* HELLO_ACK (servidor -> cliente), 56 B */
typedef struct {
  uint32_t result;  /* 1 = aceptado */
  uint32_t reason;
  uint8_t  session[LAB_SESSION_LEN];
  uint8_t  snonce[16];
  uint8_t  cnonce[16]; /* echo del nonce del cliente */
} lab_hello_ack_t;

/* PING, 40 B */
typedef struct {
  uint8_t  session[LAB_SESSION_LEN];
  uint8_t  nonce[16];
  uint64_t stamp;
} lab_ping_t;

/* PONG, 28 B */
typedef struct {
  uint64_t stamp;  /* echo del stamp del PING */
  uint8_t  echo[16]; /* echo del nonce */
  uint32_t pad;
} lab_pong_t;

/* RST, 60 B */
typedef struct {
  uint8_t session[LAB_SESSION_LEN];
  uint32_t reason;
  uint32_t len;   /* strlen(msg), <= 36 */
  char      msg[36];
} lab_rst_t;

/* BYE, 24 B */
typedef struct {
  uint8_t session[LAB_SESSION_LEN];
  uint32_t reason;
  uint32_t pad;
} lab_bye_t;


/* Utilidades (lab_util.c) */
uint64_t lab_now_ms(void);
const char *lab_kind_name(uint8_t kind);
const char *lab_reason_name(uint32_t reason);
int  lab_hdr_pack(uint8_t *out, const lab_hdr_t *h);
int  lab_hdr_parse(const uint8_t *in, size_t n, lab_hdr_t *out);
size_t lab_payload_len(uint8_t kind); /* 0 = no payload */

/* Sequence zero is reserved for HELLO. UINT32_MAX requires a new session. */
typedef struct { uint32_t next; uint32_t seen[16]; } lab_sequence_t;
uint32_t lab_sequence_accept(lab_sequence_t *state, uint32_t seq);
int lab_parse_u32(const char *text, uint32_t minimum, uint32_t maximum, uint32_t *out);

/* Native structs are never copied to/from untrusted wire bytes. */
int lab_payload_pack(uint8_t *out, size_t capacity, uint8_t kind, const void *payload);
int lab_payload_parse(const uint8_t *in, size_t length, uint8_t kind, void *payload);

int lab_random_bytes(uint8_t *out, size_t size);
