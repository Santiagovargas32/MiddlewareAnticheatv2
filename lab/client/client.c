/* Bounded UDP client. Each recv consumes exactly one datagram. */
#define _POSIX_C_SOURCE 200809L
#include "../contracts/lab.h"
#include "../contracts/evidence.h"
#include "../platform/capabilities.h"
#include "../platform/net.h"
#include <arpa/inet.h>
#include <errno.h>
#include <stdio.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

static int receive_kind(int fd, uint8_t kind, void *payload, uint32_t timeout_ms) {
  uint8_t wire[LAB_MAX_DATAGRAM];
  ssize_t n = lab_receive(fd, wire, sizeof wire, timeout_ms);
  lab_hdr_t h;
  if (n < 16 || !lab_hdr_parse(wire, (size_t)n, &h) || h.magic != LAB_MAGIC ||
      h.version != LAB_VERSION || h.flags || h.kind != kind || h.len != (uint32_t)n - 16u)
    return 0;
  return lab_payload_parse(wire + 16, h.len, kind, payload);
}
static int send_message(int fd, uint8_t kind, uint32_t sequence, const void *payload) {
  uint8_t wire[LAB_MAX_DATAGRAM];
  lab_hdr_t h = { .magic = LAB_MAGIC, .version = LAB_VERSION, .kind = kind,
                  .seq = sequence, .len = (uint32_t)lab_payload_len(kind) };
  return lab_hdr_pack(wire, &h) && lab_payload_pack(wire + 16, sizeof wire - 16, kind, payload) &&
         lab_send(fd, wire, 16 + h.len);
}
static void usage(void) {
  fprintf(stderr, "lab_client --host 127.0.0.1 --port 7777 [--count 3] [--delay 50] [--timeout-ms 1000] [--name demo] [-v]\n");
}
int main(int argc, char **argv) {
  const char *host = "127.0.0.1", *name = "demo";
  uint32_t port = 7777, count = 3, delay = 50, timeout = 1000, capability = 0, seed = 37;
  int verbose = 0;
  for (int i = 1; i < argc; ++i) {
    if (!strcmp(argv[i], "-v")) { verbose = 1; continue; }
    if (i + 1 == argc) { usage(); return 2; }
    const char *option = argv[i++], *value = argv[i];
    if (!strcmp(option, "--host")) host = value;
    else if (!strcmp(option, "--name")) name = value;
    else if (!strcmp(option, "--op")) {
      if (!strcmp(value,"file")) capability = LAB_CAP_FILE;
      else if (!strcmp(value,"proc")) capability = LAB_CAP_PROC;
      else if (!strcmp(value,"sync")) capability = LAB_CAP_SYNC;
      else return 2;
    }
    else if (!strcmp(option,"--seed")) { if (!lab_parse_u32(value,0,UINT32_MAX,&seed)) return 2; }
    else if (!strcmp(option, "--port")) { if (!lab_parse_u32(value, 1, 65535, &port)) return 2; }
    else if (!strcmp(option, "--count")) { if (!lab_parse_u32(value, 1, 64, &count)) return 2; }
    else if (!strcmp(option, "--delay")) { if (!lab_parse_u32(value, 0, 5000, &delay)) return 2; }
    else if (!strcmp(option, "--timeout-ms")) { if (!lab_parse_u32(value, 1, 60000, &timeout)) return 2; }
    else { usage(); return 2; }
  }
  if (!*name || strlen(name) >= 24 || strlen(host) > 15) return 2;
  for (const unsigned char *p = (const unsigned char *)name; *p; ++p)
    if (*p < 0x21 || *p > 0x7e) return 2;
  char endpoint[24];
  snprintf(endpoint, sizeof endpoint, "%s:%u", host, port);
  struct sockaddr_in peer, local = { .sin_family = AF_INET, .sin_addr.s_addr = htonl(INADDR_LOOPBACK) };
  if (!lab_endpoint(endpoint, &peer)) return 2;
  int fd = lab_udp_bound(&local);
  if (fd < 0) { perror("socket"); return 1; }
  int ok = 0;
  if (connect(fd, (struct sockaddr *)&peer, sizeof peer) < 0) goto done;
  lab_hello_t hello = { .app_id = LAB_APP_ID };
  memcpy(hello.app, LAB_APP_NAME, sizeof LAB_APP_NAME);
  memcpy(hello.name, name, strlen(name));
  if (!lab_random_bytes(hello.nonce, sizeof hello.nonce)) goto done;
  lab_hello_ack_t ack;
  if (!send_message(fd, LAB_HELLO, 0, &hello) || !receive_kind(fd, LAB_HELLO_ACK, &ack, timeout) ||
      ack.result != 1 || ack.reason != LAB_OK || memcmp(ack.cnonce, hello.nonce, 16)) goto done;
  for (uint32_t i = 1; i <= count; ++i) {
    if (i > 1 && delay) {
      struct timespec remaining = { .tv_sec = delay / 1000, .tv_nsec = (long)(delay % 1000) * 1000000 };
      while (nanosleep(&remaining, &remaining) < 0 && errno == EINTR) {}
    }
    lab_ping_t ping = { .stamp = lab_now_ms() };
    lab_pong_t pong;
    memcpy(ping.session, ack.session, 16);
    if (!lab_random_bytes(ping.nonce, 16) || !send_message(fd, LAB_PING, i, &ping) ||
        !receive_kind(fd, LAB_PONG, &pong, timeout) || pong.pad || pong.stamp != ping.stamp ||
        memcmp(pong.echo, ping.nonce, 16)) goto done;
    if (verbose) printf("{\"ev\":\"pong\",\"sequence\":%u,\"ok\":true}\n", i);
  }
  if (capability) {
    lab_request_t request = { .request_id = 1, .origin = LAB_ORIGIN_LINUX,
                              .capability = (uint8_t)capability, .evidence_class = LAB_SELF_REPORTED, .seed = seed };
    memcpy(request.session,ack.session,16); memcpy(request.instance,hello.nonce,16);
    lab_decision_t decision;
    if (!send_message(fd,LAB_REQUEST,count+1,&request) || !receive_kind(fd,LAB_DECISION,&decision,timeout) ||
        memcmp(decision.session,ack.session,16) || decision.request_id != 1 || decision.status != LAB_PENDING || decision.reason) goto done;
    lab_cap_result_t measured;
    uint64_t start = lab_now_ms();
    int measured_ok = lab_cap_run(capability,seed,timeout,delay,0,&measured);
    lab_observation_t observation = { .request_id = 1, .origin = request.origin, .capability = request.capability,
                                     .evidence_class = LAB_SELF_REPORTED, .ok = (uint8_t)measured_ok, .seed = seed,
                                     .elapsed_ms = (uint32_t)(lab_now_ms()-start), .error = measured.error };
    memcpy(observation.session,ack.session,16); memcpy(observation.instance,hello.nonce,16); memcpy(observation.subject,measured.subject,16);
    if (capability == LAB_CAP_FILE) {
      for (unsigned i=0;i<4;++i) observation.data[i] = (uint8_t)(measured.size >> (8*i));
      memcpy(observation.data+4,measured.digest,32);
    } else if (capability == LAB_CAP_PROC) {
      for (unsigned i=0;i<8;++i) {
        observation.data[i] = (uint8_t)(measured.process_id >> (8*i));
        observation.data[8+i] = (uint8_t)(measured.generation >> (8*i));
      }
    }
    if (!send_message(fd,LAB_OBSERVATION,count+2,&observation) || !receive_kind(fd,LAB_DECISION,&decision,timeout) ||
        memcmp(decision.session,ack.session,16) || decision.request_id != 1) goto done;
    printf("{\"ev\":\"evidence\",\"origin_os\":\"linux\",\"evidence_class\":\"self_reported_lab\",\"capability\":%u,\"status\":%u,\"reason\":%u}\n", capability,decision.status,decision.reason);
    if (decision.status != LAB_ACCEPTED || decision.reason) goto done;
  }
  lab_bye_t bye = {0}; lab_rst_t rst;
  memcpy(bye.session, ack.session, 16);
  if (!send_message(fd, LAB_BYE, count + 1, &bye) || !receive_kind(fd, LAB_RST, &rst, timeout) ||
      rst.reason != LAB_OK || rst.len != 3 || memcmp(rst.msg, "bye", 3) ||
      memcmp(rst.session, ack.session, 16)) goto done;
  ok = 1;
done:
  if (close(fd) < 0) ok = 0;
  printf("{\"ev\":\"done\",\"ok\":%s,\"count\":%u}\n", ok ? "true" : "false", count);
  if (fflush(stdout) == EOF) return 1;
  return ok ? 0 : 1;
}
