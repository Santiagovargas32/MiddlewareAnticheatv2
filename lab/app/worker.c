/* Binary lab-udp/2 records over a supervised stdio pipe. The supervisor owns
 * framing deadlines and authenticated network transport. One job per process. */
#include "worker.h"
#include "../contracts/evidence.h"
#include "../platform/capabilities.h"
#include <stdio.h>
#ifdef _WIN32
#include <io.h>
#include <fcntl.h>
#endif

static int frame_write(const uint8_t *data, size_t n) {
  uint8_t prefix[4] = { (uint8_t)(n>>24),(uint8_t)(n>>16),(uint8_t)(n>>8),(uint8_t)n };
  return fwrite(prefix,1,4,stdout)==4 && fwrite(data,1,n,stdout)==n && fflush(stdout)==0;
}
static int frame_read(uint8_t *data, size_t capacity, size_t *size) {
  uint8_t prefix[4];
  if (fread(prefix,1,4,stdin)!=4) return 0;
  uint32_t n = (uint32_t)prefix[0]<<24 | (uint32_t)prefix[1]<<16 | (uint32_t)prefix[2]<<8 | prefix[3];
  if (n>capacity || !n || fread(data,1,n,stdin)!=n) return 0;
  *size=n; return 1;
}
static int packet(uint8_t *wire, uint8_t kind, uint32_t sequence, const void *payload) {
  lab_hdr_t h = {.magic=LAB_MAGIC,.version=LAB_VERSION,.kind=kind,.seq=sequence,.len=(uint32_t)lab_payload_len(kind)};
  return lab_hdr_pack(wire,&h) && lab_payload_pack(wire+16,LAB_MAX_DATAGRAM-16,kind,payload);
}
static int header(const uint8_t *wire, size_t size, uint8_t kind, lab_hdr_t *h) {
  return lab_hdr_parse(wire,size,h) && h->magic==LAB_MAGIC && h->version==LAB_VERSION &&
         h->kind==kind && !h->flags && h->len==lab_payload_len(kind) && h->len+16==size;
}
int lab_worker_stdio(void) {
#ifdef _WIN32
  if (_setmode(_fileno(stdin),_O_BINARY)==-1 || _setmode(_fileno(stdout),_O_BINARY)==-1) return 1;
#endif
  lab_hello_t hello={.app_id=LAB_APP_ID};
  memcpy(hello.app,LAB_APP_NAME,sizeof LAB_APP_NAME);memcpy(hello.name,"worker",7);
  if (!lab_random_bytes(hello.nonce,16)) return 1;
  uint8_t wire[256];
  if (!packet(wire,LAB_HELLO,0,&hello) || !frame_write(wire,16+LAB_HELLO_LEN)) return 1;
  size_t size=0;
  if (!frame_read(wire,sizeof wire,&size) || (size!=16+LAB_REQUEST_LEN && size!=32+LAB_REQUEST_LEN+LAB_OBSERVATION_LEN)) return 1;
  lab_hdr_t h;
  if (!header(wire,16+LAB_REQUEST_LEN,LAB_REQUEST,&h) || !h.seq || h.seq>=UINT32_MAX-1) return 1;
  lab_request_t request;
  if (!lab_payload_parse(wire+16,LAB_REQUEST_LEN,LAB_REQUEST,&request) || memcmp(request.instance,hello.nonce,16)) return 1;
  uint8_t origin = !strcmp(lab_origin_os(),"windows") ? LAB_ORIGIN_WINDOWS : LAB_ORIGIN_LINUX;
  lab_policy_t policy={.origin=origin,.capabilities=7,.evidence_class=LAB_SELF_REPORTED,.request_timeout_ms=2000};
  lab_evidence_state_t state={.open=1}; memcpy(state.session,request.session,16);memcpy(state.instance,hello.nonce,16);
  if (lab_policy_request(&state,&policy,&request,lab_now_ms())) return 1;
  uint8_t source[LAB_MAX_DATAGRAM]; size_t source_size=0;
  if (size>16+LAB_REQUEST_LEN) {
    source_size=16+LAB_OBSERVATION_LEN;memcpy(source,wire+16+LAB_REQUEST_LEN,source_size);
    lab_hdr_t source_header;lab_observation_t observation;
    if (!header(source,source_size,LAB_OBSERVATION,&source_header) ||
        !lab_payload_parse(source+16,LAB_OBSERVATION_LEN,LAB_OBSERVATION,&observation) ||
        observation.origin!=LAB_ORIGIN_LINUX || observation.capability!=request.capability || observation.seed!=request.seed) return 1;
    lab_request_t original={.request_id=observation.request_id,.origin=LAB_ORIGIN_LINUX,.capability=observation.capability,.evidence_class=LAB_SELF_REPORTED,.seed=observation.seed};
    memcpy(original.session,observation.session,16);memcpy(original.instance,observation.instance,16);
    lab_evidence_state_t imported={.open=1};memcpy(imported.session,original.session,16);memcpy(imported.instance,original.instance,16);
    lab_policy_t imported_policy=policy;imported_policy.origin=LAB_ORIGIN_LINUX;
    if (lab_policy_request(&imported,&imported_policy,&original,0) || lab_policy_observation(&imported,&imported_policy,&observation,1)) return 1;
  }
  uint64_t start=lab_now_ms();
  lab_cap_result_t result;
  int ok=lab_cap_run(request.capability,request.seed,1500,10,0,&result);
  lab_observation_t observation={.request_id=request.request_id,.origin=origin,.capability=request.capability,.evidence_class=LAB_SELF_REPORTED,
                                .ok=(uint8_t)ok,.seed=request.seed,.elapsed_ms=(uint32_t)(lab_now_ms()-start),.error=result.error};
  memcpy(observation.session,request.session,16);memcpy(observation.instance,hello.nonce,16);memcpy(observation.subject,result.subject,16);
  if (request.capability==LAB_CAP_FILE) {
    for (unsigned i=0;i<4;++i) observation.data[i]=(uint8_t)(result.size>>(8*i));
    memcpy(observation.data+4,result.digest,32);
  } else if (request.capability==LAB_CAP_PROC) {
    for (unsigned i=0;i<8;++i) { observation.data[i]=(uint8_t)(result.process_id>>(8*i));observation.data[8+i]=(uint8_t)(result.generation>>(8*i)); }
  }
  if (source_size && !frame_write(source,source_size)) return 1; /* byte-for-byte preservation */
  if (!packet(wire,LAB_OBSERVATION,h.seq+1,&observation) || !frame_write(wire,16+LAB_OBSERVATION_LEN)) return 1;
  return ok ? 0 : 1;
}
