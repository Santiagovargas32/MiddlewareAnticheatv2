/* Console collector. Origin is selected by the compiled platform backend. */
#include "../contracts/lab.h"
#include "../platform/capabilities.h"
#include "worker.h"
#include <stdio.h>
#include <string.h>

static void hex(const uint8_t *bytes, size_t size) {
  for (size_t i = 0; i < size; ++i) printf("%02x", bytes[i]);
}
int main(int argc, char **argv) {
  if (argc==2 && !strcmp(argv[1],"--worker")) return lab_worker_stdio();
  uint32_t capability = 0, seed = 0, timeout = 2000, delay = 10;
  const char *operation = NULL;
  int child = 0;
  for (int i = 1; i < argc; ++i) {
    if (!strcmp(argv[i], "--child")) { child = 1; continue; }
    if (i + 1 == argc) return 2;
    const char *option = argv[i++], *value = argv[i];
    if (!strcmp(option, "--op")) operation = value;
    else if (!strcmp(option, "--seed")) { if (!lab_parse_u32(value, 0, UINT32_MAX, &seed)) return 2; }
    else if (!strcmp(option, "--timeout-ms")) { if (!lab_parse_u32(value, 1, 60000, &timeout)) return 2; }
    else if (!strcmp(option, "--delay-ms")) { if (!lab_parse_u32(value, 0, 60000, &delay)) return 2; }
    else return 2;
  }
  if (!operation) { fprintf(stderr, "lab_app --op file|proc|sync [--seed N] [--timeout-ms 2000] [--delay-ms 10]\n"); return 2; }
  if (!strcmp(operation, "file")) capability = LAB_CAP_FILE;
  else if (!strcmp(operation, "proc")) capability = LAB_CAP_PROC;
  else if (!strcmp(operation, "sync")) capability = LAB_CAP_SYNC;
  else return 2;
  uint8_t instance[16];
  if (!lab_random_bytes(instance, sizeof instance)) return 1;
  lab_cap_result_t result;
  uint64_t start = lab_now_ms();
  int ok = lab_cap_run(capability, seed, timeout, delay, child, &result);
  if (child) return ok ? 0 : 1;
  printf("{\"protocol\":\"lab-observation/1\",\"origin_os\":\"%s\",\"origin_instance\":\"", lab_origin_os());
  hex(instance, 16); printf("\",\"subject_id\":\""); hex(result.subject, 16);
  printf("\",\"evidence_class\":\"self_reported_lab\",\"op\":\"%s\",\"seed\":%u,\"ok\":%s,\"size\":%u,\"error\":%u,\"process_id\":%llu,\"generation\":%llu,\"elapsed_ms\":%llu,\"sha256\":\"",
         operation, seed, ok ? "true" : "false", result.size, result.error,
         (unsigned long long)result.process_id, (unsigned long long)result.generation,
         (unsigned long long)(lab_now_ms() - start));
  hex(result.digest, 32); printf("\"}\n");
  if (fflush(stdout) == EOF) return 1;
  return ok ? 0 : 1;
}
