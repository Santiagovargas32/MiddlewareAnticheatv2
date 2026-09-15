#include "../lab/contracts/evidence.h"
#include <stdio.h>
#define CHECK(x) do { if (!(x)) { fprintf(stderr,"%d: %s\n",__LINE__,#x); return 1; } } while (0)
int main(void) {
  /* Independent request fixture: LE32 ID and seed, exact byte offsets. */
  const uint8_t fixture[44] = {
    1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0x78,0x56,0x34,0x12,
    2,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,1,3,1,0,0x44,0x33,0x22,0x11
  };
  lab_request_t r = {0};
  CHECK(lab_payload_parse(fixture,sizeof fixture,LAB_REQUEST,&r));
  CHECK(r.request_id==0x12345678 && r.seed==0x11223344 && r.capability==3 && r.session[0]==1 && r.instance[0]==2);
  uint8_t wire[130] = {0};
  CHECK(lab_payload_pack(wire+1,44,LAB_REQUEST,&r) && !memcmp(wire+1,fixture,44) && !wire[0] && !wire[45]);
  lab_request_t before=r;
  for (size_t n=0;n<130;++n) if (n!=44) {
    CHECK(!lab_payload_parse(wire,n,LAB_REQUEST,&r)); CHECK(!memcmp(&r,&before,sizeof r));
  }
  lab_policy_t policy = { .origin=1,.capabilities=7,.evidence_class=1,.request_timeout_ms=100 };
  lab_evidence_state_t state = {0};
  CHECK(lab_policy_request(&state,&policy,&r,0)==LAB_CLOSING);
  state.open=1;memcpy(state.session,r.session,16);memcpy(state.instance,r.instance,16);
  policy.origin=2; CHECK(lab_policy_request(&state,&policy,&r,0)==LAB_ORIGIN_MISMATCH);
  policy.origin=1;policy.capabilities=1; CHECK(lab_policy_request(&state,&policy,&r,0)==LAB_UNSUPPORTED);
  policy.capabilities=7;policy.evidence_class=2; CHECK(lab_policy_request(&state,&policy,&r,0)==LAB_INSUFFICIENT);
  policy.evidence_class=1; CHECK(lab_policy_request(&state,&policy,&r,UINT64_MAX)==LAB_BAD_PAYLOAD);
  CHECK(lab_policy_request(&state,&policy,&r,0)==LAB_OK);
  lab_observation_t o = { .request_id=r.request_id,.origin=1,.capability=3,.evidence_class=1,.ok=1,.seed=r.seed };
  memcpy(o.session,r.session,16);memcpy(o.instance,r.instance,16);o.subject[0]=1;
  CHECK(lab_policy_observation(&state,&policy,&o,100)==LAB_EXPIRED && state.pending);
  CHECK(lab_policy_observation(&state,&policy,&o,99)==LAB_OK && !state.pending);
  /* All kinds and lengths, aligned native destination, deliberately unaligned wire. */
  union { lab_hdr_t h; lab_hello_t hello; lab_hello_ack_t ack; lab_ping_t ping; lab_pong_t pong;
          lab_rst_t rst; lab_bye_t bye; lab_request_t req; lab_observation_t obs; lab_decision_t decision; } out;
  uint32_t rng=1;
  for (unsigned iteration=0;iteration<10000;++iteration) {
    for (size_t i=0;i<sizeof wire;++i) { rng=rng*1664525u+1013904223u;wire[i]=(uint8_t)(rng>>24); }
    (void)lab_hdr_parse(wire+1,iteration%129,&out.h);
    for (unsigned kind=0;kind<256;++kind) (void)lab_payload_parse(wire+1,iteration%129,(uint8_t)kind,&out);
  }
  puts("PASS: evidence fixtures, policy boundaries, bounded parser fuzz (2560000 payloads)");
  return 0;
}
