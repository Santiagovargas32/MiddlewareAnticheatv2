#ifndef LAB_NET_H
#define LAB_NET_H
#include <netinet/in.h>
#include <stddef.h>
#include <stdint.h>
#include <sys/types.h>
int lab_endpoint(const char *text, struct sockaddr_in *out);
int lab_udp_bound(const struct sockaddr_in *address);
ssize_t lab_receive(int fd, void *buffer, size_t capacity, uint32_t timeout_ms);
int lab_send(int fd, const void *buffer, size_t length);
int lab_same_peer(const struct sockaddr_in *a, const struct sockaddr_in *b);
#endif
