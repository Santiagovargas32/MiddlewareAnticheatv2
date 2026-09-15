#include "evidence.h"
static void put32(uint8_t *p, uint32_t v) {
  for (unsigned i = 0; i < 4; ++i) p[i] = (uint8_t)(v >> (8 * i));
}
static uint32_t get32(const uint8_t *p) {
  uint32_t v = 0; for (unsigned i = 0; i < 4; ++i) v |= (uint32_t)p[i] << (8 * i); return v;
}
static int nonzero(const uint8_t *data, size_t n) {
  uint8_t any = 0; for (size_t i = 0; i < n; ++i) any |= data[i]; return any != 0;
}
int lab_evidence_pack(uint8_t *out, size_t capacity, uint8_t kind, const void *payload) {
  size_t size = kind == LAB_REQUEST ? LAB_REQUEST_LEN : kind == LAB_OBSERVATION ? LAB_OBSERVATION_LEN : kind == LAB_DECISION ? LAB_DECISION_LEN : 0;
  if (!out || !payload || !size || capacity < size) return 0;
  if (kind == LAB_REQUEST) {
    const lab_request_t *p = payload;
    memcpy(out,p->session,16); put32(out+16,p->request_id); memcpy(out+20,p->instance,16);
    out[36]=p->origin; out[37]=p->capability; out[38]=p->evidence_class; out[39]=p->reserved; put32(out+40,p->seed);
  } else if (kind == LAB_OBSERVATION) {
    const lab_observation_t *p = payload;
    memcpy(out,p->session,16); put32(out+16,p->request_id); memcpy(out+20,p->instance,16); memcpy(out+36,p->subject,16);
    out[52]=p->origin; out[53]=p->capability; out[54]=p->evidence_class; out[55]=p->ok;
    put32(out+56,p->seed); put32(out+60,p->elapsed_ms); put32(out+64,p->error); memcpy(out+68,p->data,36);
  } else {
    const lab_decision_t *p = payload;
    memcpy(out,p->session,16); put32(out+16,p->request_id); put32(out+20,p->status); put32(out+24,p->reason);
  }
  return 1;
}
int lab_evidence_parse(const uint8_t *in, size_t length, uint8_t kind, void *payload) {
  size_t size = kind == LAB_REQUEST ? LAB_REQUEST_LEN : kind == LAB_OBSERVATION ? LAB_OBSERVATION_LEN : kind == LAB_DECISION ? LAB_DECISION_LEN : 0;
  if (!in || !payload || !size || length != size) return 0;
  if (kind == LAB_REQUEST) {
    lab_request_t p = {0};
    memcpy(p.session,in,16); p.request_id=get32(in+16); memcpy(p.instance,in+20,16);
    p.origin=in[36]; p.capability=in[37]; p.evidence_class=in[38]; p.reserved=in[39]; p.seed=get32(in+40);
    *(lab_request_t *)payload=p;
  } else if (kind == LAB_OBSERVATION) {
    lab_observation_t p = {0};
    memcpy(p.session,in,16); p.request_id=get32(in+16); memcpy(p.instance,in+20,16); memcpy(p.subject,in+36,16);
    p.origin=in[52]; p.capability=in[53]; p.evidence_class=in[54]; p.ok=in[55];
    p.seed=get32(in+56); p.elapsed_ms=get32(in+60); p.error=get32(in+64); memcpy(p.data,in+68,36);
    *(lab_observation_t *)payload=p;
  } else {
    lab_decision_t p = {0}; memcpy(p.session,in,16); p.request_id=get32(in+16); p.status=get32(in+20); p.reason=get32(in+24);
    *(lab_decision_t *)payload=p;
  }
  return 1;
}
static uint32_t common(const lab_evidence_state_t *s, const lab_policy_t *policy,
                       const uint8_t session[16], const uint8_t instance[16],
                       uint8_t origin, uint8_t capability, uint8_t evidence_class) {
  if (!s->open) return LAB_CLOSING;
  if (memcmp(s->session,session,16)) return LAB_BAD_SESSION;
  if (memcmp(s->instance,instance,16)) return LAB_OLD_INSTANCE;
  if ((origin != LAB_ORIGIN_LINUX && origin != LAB_ORIGIN_WINDOWS) || (policy->origin && policy->origin != origin)) return LAB_ORIGIN_MISMATCH;
  if (capability < 1 || capability > 3 || !(policy->capabilities & (1u << (capability-1)))) return LAB_UNSUPPORTED;
  if (evidence_class != LAB_SELF_REPORTED || evidence_class != policy->evidence_class) return LAB_INSUFFICIENT;
  return LAB_OK;
}
uint32_t lab_policy_request(lab_evidence_state_t *s, const lab_policy_t *policy, const lab_request_t *r, uint64_t now) {
  uint32_t reason = common(s,policy,r->session,r->instance,r->origin,r->capability,r->evidence_class);
  if (reason) return reason;
  if (r->reserved || !r->request_id) return LAB_BAD_PAYLOAD;
  if (r->request_id <= s->last_request) return LAB_REPLAY;
  if (s->pending && now < s->deadline) return LAB_BUSY;
  if (UINT64_MAX - now < policy->request_timeout_ms) return LAB_BAD_PAYLOAD;
  s->request = *r; s->last_request = r->request_id; s->deadline = now + policy->request_timeout_ms; s->pending = 1;
  return LAB_OK;
}
uint32_t lab_policy_observation(lab_evidence_state_t *s, const lab_policy_t *policy, const lab_observation_t *o, uint64_t now) {
  uint32_t reason = common(s,policy,o->session,o->instance,o->origin,o->capability,o->evidence_class);
  if (reason) return reason;
  if (!s->pending || o->request_id != s->request.request_id) return LAB_UNKNOWN_REQUEST;
  if (now >= s->deadline) return LAB_EXPIRED;
  if (o->capability != s->request.capability || o->origin != s->request.origin || o->seed != s->request.seed ||
      !nonzero(o->subject,16) || o->ok != 1 || o->error || o->elapsed_ms > policy->request_timeout_ms) return LAB_BAD_PAYLOAD;
  if (o->capability == 1 && (get32(o->data) != 4096 || !nonzero(o->data+4,32))) return LAB_BAD_PAYLOAD;
  if (o->capability == 2 && (!nonzero(o->data,8) || !nonzero(o->data+8,8) || nonzero(o->data+16,20))) return LAB_BAD_PAYLOAD;
  if (o->capability == 3 && nonzero(o->data,36)) return LAB_BAD_PAYLOAD;
  s->pending = 0;
  return LAB_OK;
}
