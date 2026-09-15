#define _POSIX_C_SOURCE 200809L
#include "capabilities.h"
#include "../contracts/lab.h"
#include <errno.h>
#include <fcntl.h>
#include <openssl/evp.h>
#include <poll.h>
#include <pthread.h>
#include <signal.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/prctl.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

const char *lab_origin_os(void) { return "linux"; }
static int file_operation(uint32_t seed, lab_cap_result_t *result) {
  char path[] = "/tmp/lab-cap-XXXXXX";
  int fd = mkstemp(path);
  if (fd < 0) { result->error = (uint32_t)errno; return 0; }
  if (unlink(path) < 0) { result->error = (uint32_t)errno; close(fd); return 0; }
  uint8_t expected[4096], observed[4096];
  for (size_t i = 0; i < sizeof expected; ++i) expected[i] = (uint8_t)(i * 7u + seed);
  int ok = 1;
  size_t offset = 0;
  while (offset < sizeof expected) {
    ssize_t n = write(fd, expected + offset, sizeof expected - offset);
    if (n < 0 && errno == EINTR) continue;
    if (n <= 0) { ok = 0; break; } offset += (size_t)n;
  }
  if (ok && lseek(fd, 0, SEEK_SET) < 0) ok = 0;
  offset = 0;
  while (ok && offset < sizeof observed) {
    ssize_t n = read(fd, observed + offset, sizeof observed - offset);
    if (n < 0 && errno == EINTR) continue;
    if (n <= 0) { ok = 0; break; } offset += (size_t)n;
  }
  unsigned int length = 0;
  if (ok) ok = !memcmp(observed, expected, sizeof expected) &&
               EVP_Digest(observed, sizeof observed, result->digest, &length, EVP_sha256(), NULL) == 1 && length == 32;
  if (!ok) result->error = errno ? (uint32_t)errno : EIO;
  if (close(fd) < 0) { ok = 0; result->error = (uint32_t)errno; }
  result->size = ok ? sizeof observed : 0;
  return ok;
}
static int process_operation(uint32_t seed, uint32_t timeout, uint32_t delay, lab_cap_result_t *result) {
  int pipefd[2];
  if (pipe(pipefd) < 0) { result->error = (uint32_t)errno; return 0; }
  pid_t parent = getpid();
  pid_t pid = fork();
  if (pid < 0) { result->error = (uint32_t)errno; close(pipefd[0]); close(pipefd[1]); return 0; }
  if (!pid) {
    if (prctl(PR_SET_PDEATHSIG, SIGKILL) < 0 || getppid() != parent) _exit(1);
    close(pipefd[0]);
    struct timespec pause = { .tv_sec = delay / 1000, .tv_nsec = (long)(delay % 1000) * 1000000 };
    while (nanosleep(&pause, &pause) < 0 && errno == EINTR) {}
    lab_cap_result_t child = {0};
    child.generation = lab_now_ms(); child.process_id = (uint64_t)getpid();
    child.ok = lab_random_bytes(child.subject, 16) && file_operation(seed, &child);
    memset(child.digest, 0, sizeof child.digest);
    ssize_t n;
    do { n = write(pipefd[1], &child, sizeof child); } while (n < 0 && errno == EINTR);
    close(pipefd[1]); _exit(child.ok && n == (ssize_t)sizeof child ? 0 : 1);
  }
  close(pipefd[1]);
  uint64_t deadline = lab_now_ms() + timeout;
  uint8_t received[sizeof *result]; size_t offset = 0;
  while (offset < sizeof received && lab_now_ms() < deadline) {
    struct pollfd p = { .fd = pipefd[0], .events = POLLIN };
    uint64_t now = lab_now_ms();
    if (now >= deadline) break;
    int ready = poll(&p, 1, (int)(deadline - now));
    if (ready < 0 && errno == EINTR) continue;
    if (ready <= 0) break;
    ssize_t n = read(pipefd[0], received + offset, sizeof received - offset);
    if (n < 0 && errno == EINTR) continue;
    if (n <= 0) break;
    offset += (size_t)n;
  }
  close(pipefd[0]);
  int status = 0, exited = 0;
  while (lab_now_ms() < deadline) {
    pid_t waited = waitpid(pid, &status, WNOHANG);
    if (waited == pid) { exited = 1; break; }
    if (waited < 0 && errno != EINTR) break;
    struct timespec pause = { .tv_nsec = 1000000 }; nanosleep(&pause, NULL);
  }
  if (!exited) {
    kill(pid, SIGKILL);
    while (waitpid(pid, &status, 0) < 0 && errno == EINTR) {}
    result->error = ETIMEDOUT; result->process_id = (uint64_t)pid; return 0;
  }
  if (offset != sizeof *result || !WIFEXITED(status) || WEXITSTATUS(status)) { result->error = ECHILD; return 0; }
  memcpy(result, received, sizeof *result);
  return result->ok == 1;
}
typedef struct { pthread_mutex_t mutex; pthread_cond_t event; int ready, stop, error; uint32_t delay; } sync_t;
static void *signal_event(void *argument) {
  sync_t *state = argument;
  struct timespec due;
  if (clock_gettime(CLOCK_MONOTONIC, &due)) return NULL;
  due.tv_sec += state->delay / 1000;
  due.tv_nsec += (long)(state->delay % 1000) * 1000000;
  if (due.tv_nsec >= 1000000000) { due.tv_nsec -= 1000000000; due.tv_sec++; }
  pthread_mutex_lock(&state->mutex);
  int status = 0;
  while (!state->stop && !status) status = pthread_cond_timedwait(&state->event, &state->mutex, &due);
  if (!state->stop && status == ETIMEDOUT) state->ready = 1;
  else if (status && status != ETIMEDOUT) state->error = status;
  pthread_cond_broadcast(&state->event);
  pthread_mutex_unlock(&state->mutex);
  return NULL;
}
static int sync_operation(uint32_t timeout, uint32_t delay, lab_cap_result_t *result) {
  sync_t state = { .delay = delay };
  pthread_condattr_t attributes;
  int error = pthread_mutex_init(&state.mutex, NULL);
  if (error) { result->error = (uint32_t)error; return 0; }
  error = pthread_condattr_init(&attributes);
  if (error) { pthread_mutex_destroy(&state.mutex); result->error = (uint32_t)error; return 0; }
  error = pthread_condattr_setclock(&attributes, CLOCK_MONOTONIC);
  if (!error) error = pthread_cond_init(&state.event, &attributes);
  pthread_condattr_destroy(&attributes);
  if (error) { pthread_mutex_destroy(&state.mutex); result->error = (uint32_t)error; return 0; }
  pthread_t thread;
  error = pthread_create(&thread, NULL, signal_event, &state);
  if (error) { pthread_cond_destroy(&state.event); pthread_mutex_destroy(&state.mutex); result->error = (uint32_t)error; return 0; }
  struct timespec due = {0};
  if (clock_gettime(CLOCK_MONOTONIC, &due)) error = errno;
  due.tv_sec += timeout / 1000; due.tv_nsec += (long)(timeout % 1000) * 1000000;
  if (due.tv_nsec >= 1000000000) { due.tv_nsec -= 1000000000; due.tv_sec++; }
  pthread_mutex_lock(&state.mutex);
  while (!state.ready && !state.error && !error) error = pthread_cond_timedwait(&state.event, &state.mutex, &due);
  int ok = state.ready;
  if (state.error) error = state.error;
  state.stop = 1; pthread_cond_broadcast(&state.event); pthread_mutex_unlock(&state.mutex);
  int joined = pthread_join(thread, NULL);
  pthread_cond_destroy(&state.event); pthread_mutex_destroy(&state.mutex);
  result->error = (uint32_t)(ok ? joined : error);
  return ok && !joined;
}
int lab_cap_run(uint32_t capability, uint32_t seed, uint32_t timeout, uint32_t delay, int child, lab_cap_result_t *result) {
  (void)child;
  memset(result, 0, sizeof *result);
  if (!lab_random_bytes(result->subject, 16)) { result->error = EIO; return 0; }
  result->process_id = (uint64_t)getpid(); result->generation = lab_now_ms();
  if (capability == LAB_CAP_FILE) result->ok = file_operation(seed, result);
  else if (capability == LAB_CAP_PROC) result->ok = process_operation(seed, timeout, delay, result);
  else if (capability == LAB_CAP_SYNC) result->ok = sync_operation(timeout, delay, result);
  else result->error = EINVAL;
  return result->ok == 1;
}
