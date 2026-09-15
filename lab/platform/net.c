#define _POSIX_C_SOURCE 200809L
#include "net.h"
#include "../contracts/lab.h"
#include <arpa/inet.h>
#include <errno.h>
#include <poll.h>
#include <string.h>
#include <sys/socket.h>
#include <unistd.h>

int lab_endpoint(const char *text, struct sockaddr_in *out) {
  char host[16];
  const char *colon = text ? strchr(text, ':') : NULL;
  if (!colon || colon == text || (size_t)(colon - text) >= sizeof host) return 0;
  memcpy(host, text, (size_t)(colon - text)); host[colon - text] = 0;
  uint32_t port;
  struct sockaddr_in address = { .sin_family = AF_INET };
  if (!lab_parse_u32(colon + 1, 1, 65535, &port) || inet_pton(AF_INET, host, &address.sin_addr) != 1 ||
      (ntohl(address.sin_addr.s_addr) >> 24) != 127) return 0;
  address.sin_port = htons((uint16_t)port);
  *out = address;
  return 1;
}
int lab_udp_bound(const struct sockaddr_in *address) {
  int fd = socket(AF_INET, SOCK_DGRAM | SOCK_CLOEXEC | SOCK_NONBLOCK, 0);
  if (fd < 0) return -1;
  if (bind(fd, (const struct sockaddr *)address, sizeof *address) < 0) {
    int saved = errno; close(fd); errno = saved; return -1;
  }
  return fd;
}
int lab_same_peer(const struct sockaddr_in *a, const struct sockaddr_in *b) {
  return a->sin_family == b->sin_family && a->sin_port == b->sin_port &&
         a->sin_addr.s_addr == b->sin_addr.s_addr;
}
ssize_t lab_receive(int fd, void *buffer, size_t capacity, uint32_t timeout_ms) {
  uint64_t deadline = lab_now_ms() + timeout_ms;
  for (;;) {
    uint64_t now = lab_now_ms();
    if (now >= deadline) { errno = ETIMEDOUT; return -1; }
    struct pollfd item = { .fd = fd, .events = POLLIN };
    int ready = poll(&item, 1, (int)(deadline - now));
    if (ready < 0 && errno == EINTR) continue;
    if (ready < 0) return -1;
    if (!ready) { errno = ETIMEDOUT; return -1; }
    ssize_t size = recv(fd, buffer, capacity, MSG_TRUNC);
    if (size < 0 && (errno == EINTR || errno == EAGAIN)) continue;
    if (size > (ssize_t)capacity) { errno = EMSGSIZE; return -1; }
    return size;
  }
}
int lab_send(int fd, const void *buffer, size_t length) {
  ssize_t sent;
  do { sent = send(fd, buffer, length, MSG_NOSIGNAL); } while (sent < 0 && errno == EINTR);
  return sent == (ssize_t)length;
}
