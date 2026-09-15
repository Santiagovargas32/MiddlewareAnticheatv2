#pragma once
#include <stddef.h>
#include <stdint.h>
/* A local observation only. UNKNOWN must never become DISABLED or trusted. */
enum { LAB_HOST_UNKNOWN=0, LAB_HOST_DISABLED=1, LAB_HOST_ENABLED=2 };
int lab_host_secure_boot_value(const uint8_t *bytes, size_t length);
/* Open only the canonical IMA list or a known in-directory kernel alias.
 * directory_fd remains caller-owned; a returned fd is caller-owned. On error
 * return -1 with errno preserved. Does not read or export any measurements. */
int lab_host_open_ima(int directory_fd);
