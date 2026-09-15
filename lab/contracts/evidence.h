#pragma once
#include "lab.h"

/* Protocol lab-udp/2. Request lifetime is measured only by the verifier clock. */
enum { LAB_REQUEST = 0x40, LAB_OBSERVATION = 0x41, LAB_DECISION = 0x42 };
enum { LAB_ORIGIN_LINUX = 1, LAB_ORIGIN_WINDOWS = 2, LAB_SELF_REPORTED = 1 };
enum { LAB_REJECTED = 0, LAB_PENDING = 1, LAB_ACCEPTED = 2 };
#define LAB_REQUEST_LEN 44u
#define LAB_OBSERVATION_LEN 104u
#define LAB_DECISION_LEN 28u

typedef struct {
  uint8_t session[16]; uint32_t request_id; uint8_t instance[16];
  uint8_t origin, capability, evidence_class, reserved; uint32_t seed;
} lab_request_t;
typedef struct {
  uint8_t session[16]; uint32_t request_id; uint8_t instance[16], subject[16];
  uint8_t origin, capability, evidence_class, ok;
  uint32_t seed, elapsed_ms, error;
  /* file: size LE32 + SHA256; proc: PID LE64 + generation LE64 + zero20;
     sync: zero36. Subject is a fresh random resource instance in every case. */
  uint8_t data[36];
} lab_observation_t;
typedef struct { uint8_t session[16]; uint32_t request_id, status, reason; } lab_decision_t;

typedef struct { uint8_t origin, capabilities, evidence_class; uint32_t request_timeout_ms; } lab_policy_t;
typedef struct {
  int open, pending;
  uint8_t session[16], instance[16];
  uint32_t last_request;
  uint64_t deadline;
  lab_request_t request;
} lab_evidence_state_t;
int lab_evidence_pack(uint8_t *out, size_t capacity, uint8_t kind, const void *payload);
int lab_evidence_parse(const uint8_t *in, size_t length, uint8_t kind, void *payload);
uint32_t lab_policy_request(lab_evidence_state_t *state, const lab_policy_t *policy,
                            const lab_request_t *request, uint64_t now);
uint32_t lab_policy_observation(lab_evidence_state_t *state, const lab_policy_t *policy,
                                const lab_observation_t *observation, uint64_t now);
