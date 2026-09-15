#ifndef LAB_CAPABILITIES_H
#define LAB_CAPABILITIES_H
#include <stdint.h>
enum { LAB_CAP_FILE = 1, LAB_CAP_PROC = 2, LAB_CAP_SYNC = 3 };
typedef struct {
  uint32_t ok, error, size;
  uint8_t digest[32], subject[16];
  uint64_t process_id, generation;
} lab_cap_result_t;
int lab_cap_run(uint32_t capability, uint32_t seed, uint32_t timeout_ms,
                uint32_t delay_ms, int child, lab_cap_result_t *result);
const char *lab_origin_os(void);
#endif
