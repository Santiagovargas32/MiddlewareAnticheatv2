/* Test-only linker wrapper: never linked into lab_server. */
#include <errno.h>
#include <stddef.h>
#include <string.h>
#include <sys/types.h>

ssize_t __wrap_getrandom(void *buffer, size_t length, unsigned int flags);

ssize_t __wrap_getrandom(void *buffer, size_t length, unsigned int flags) {
  static unsigned int calls;
  (void)flags;
  calls++;
  if (calls == 1) {
    errno = EINTR;
    return -1;
  }
  if (calls <= 3) {
    size_t count = length > 16 ? 16 : length;
    memset(buffer, 0x42, count);
    return (ssize_t)count;
  }
  if (calls == 4) {
    errno = EIO;
    return -1;
  }
  return 0;
}
