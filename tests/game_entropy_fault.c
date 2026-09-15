#include "lab/contracts/lab.h"

int __wrap_lab_random_bytes(uint8_t *out, size_t size);
int __wrap_lab_random_bytes(uint8_t *out, size_t size) {
    (void)out;
    (void)size;
    return 0;
}
