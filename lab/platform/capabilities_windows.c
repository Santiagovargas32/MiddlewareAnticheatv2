/* Owned resources only. No platform impersonation or host inspection. */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <bcrypt.h>
#include "capabilities.h"
#include "../contracts/lab.h"
#include <stdio.h>
#include <string.h>

const char *lab_origin_os(void) { return "windows"; }
static int file_operation(uint32_t seed, lab_cap_result_t *result) {
  WCHAR directory[MAX_PATH], path[MAX_PATH];
  DWORD length = GetTempPathW(MAX_PATH, directory);
  uint8_t token[16];
  if (!length || length >= MAX_PATH || !lab_random_bytes(token, sizeof token)) { result->error = ERROR_GEN_FAILURE; return 0; }
  WCHAR suffix[33];
  for (size_t i = 0; i < sizeof token; ++i) swprintf(suffix + i * 2, 3, L"%02x", token[i]);
  if (swprintf(path, MAX_PATH, L"%lslab-cap-%ls.tmp", directory, suffix) < 0) { result->error = ERROR_BUFFER_OVERFLOW; return 0; }
  HANDLE file = CreateFileW(path, GENERIC_READ | GENERIC_WRITE, 0, NULL, CREATE_NEW,
                            FILE_ATTRIBUTE_TEMPORARY | FILE_FLAG_DELETE_ON_CLOSE, NULL);
  if (file == INVALID_HANDLE_VALUE) { result->error = GetLastError(); return 0; }
  uint8_t expected[4096], observed[4096];
  for (size_t i = 0; i < sizeof expected; ++i) expected[i] = (uint8_t)(i * 7u + seed);
  DWORD done = 0; size_t offset = 0; int ok = 1;
  while (offset < sizeof expected) {
    if (!WriteFile(file, expected + offset, (DWORD)(sizeof expected - offset), &done, NULL) || !done) { ok = 0; break; }
    offset += done;
  }
  LARGE_INTEGER start = {0};
  if (ok && !SetFilePointerEx(file, start, NULL, FILE_BEGIN)) ok = 0;
  offset = 0;
  while (ok && offset < sizeof observed) {
    if (!ReadFile(file, observed + offset, (DWORD)(sizeof observed - offset), &done, NULL) || !done) { ok = 0; break; }
    offset += done;
  }
  if (!ok) result->error = GetLastError();
  BCRYPT_ALG_HANDLE algorithm = NULL; BCRYPT_HASH_HANDLE hash = NULL;
  if (ok) ok = memcmp(expected, observed, sizeof expected) == 0 &&
               BCryptOpenAlgorithmProvider(&algorithm, BCRYPT_SHA256_ALGORITHM, NULL, 0) >= 0 &&
               BCryptCreateHash(algorithm, &hash, NULL, 0, NULL, 0, 0) >= 0 &&
               BCryptHashData(hash, observed, sizeof observed, 0) >= 0 &&
               BCryptFinishHash(hash, result->digest, sizeof result->digest, 0) >= 0;
  if (hash && BCryptDestroyHash(hash) < 0) ok = 0;
  if (algorithm && BCryptCloseAlgorithmProvider(algorithm, 0) < 0) ok = 0;
  if (!CloseHandle(file)) ok = 0;
  if (!ok && !result->error) result->error = ERROR_GEN_FAILURE;
  result->size = ok ? sizeof observed : 0;
  return ok;
}
static int process_operation(uint32_t seed, uint32_t timeout, uint32_t delay, lab_cap_result_t *result) {
  WCHAR executable[32768], command[32896];
  DWORD size = GetModuleFileNameW(NULL, executable, 32768);
  if (!size || size >= 32768) { result->error = ERROR_BUFFER_OVERFLOW; return 0; }
  if (swprintf(command, 32896, L"\"%ls\" --op file --seed %u --delay-ms %u --child", executable, seed, delay) < 0) {
    result->error = ERROR_BUFFER_OVERFLOW; return 0;
  }
  HANDLE job = CreateJobObjectW(NULL, NULL);
  if (!job) { result->error = GetLastError(); return 0; }
  JOBOBJECT_EXTENDED_LIMIT_INFORMATION limits = {0};
  limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
  if (!SetInformationJobObject(job, JobObjectExtendedLimitInformation, &limits, sizeof limits)) {
    result->error = GetLastError(); CloseHandle(job); return 0;
  }
  /* Windows 10+: associate atomically at creation, including parent crash paths. */
  SIZE_T bytes = 0;
  InitializeProcThreadAttributeList(NULL, 1, 0, &bytes);
  STARTUPINFOEXW startup = { .StartupInfo.cb = sizeof startup };
  startup.lpAttributeList = HeapAlloc(GetProcessHeap(), 0, bytes);
  if (!startup.lpAttributeList) { result->error = ERROR_NOT_ENOUGH_MEMORY; CloseHandle(job); return 0; }
  int initialized = InitializeProcThreadAttributeList(startup.lpAttributeList, 1, 0, &bytes) != 0;
  int configured = initialized && UpdateProcThreadAttribute(startup.lpAttributeList, 0,
                        PROC_THREAD_ATTRIBUTE_JOB_LIST, &job, sizeof job, NULL, NULL);
  PROCESS_INFORMATION process = {0};
  int created = configured && CreateProcessW(executable, command, NULL, NULL, FALSE,
                  CREATE_NO_WINDOW | EXTENDED_STARTUPINFO_PRESENT, NULL, NULL, &startup.StartupInfo, &process);
  if (!created) result->error = GetLastError();
  if (initialized) DeleteProcThreadAttributeList(startup.lpAttributeList);
  HeapFree(GetProcessHeap(), 0, startup.lpAttributeList);
  if (!created) { CloseHandle(job); return 0; }
  result->process_id = process.dwProcessId;
  FILETIME creation, exit_time, kernel, user;
  int ok = GetProcessTimes(process.hProcess, &creation, &exit_time, &kernel, &user) != 0;
  if (ok) result->generation = ((uint64_t)creation.dwHighDateTime << 32) | creation.dwLowDateTime;
  DWORD wait = WaitForSingleObject(process.hProcess, timeout), code = 1;
  if (wait != WAIT_OBJECT_0) {
    result->error = wait == WAIT_TIMEOUT ? ERROR_TIMEOUT : GetLastError();
    if (!TerminateProcess(process.hProcess, 1)) result->error = GetLastError();
    if (WaitForSingleObject(process.hProcess, 2000) != WAIT_OBJECT_0) result->error = ERROR_PROCESS_ABORTED;
    ok = 0;
  } else if (!GetExitCodeProcess(process.hProcess, &code) || code) {
    result->error = ERROR_PROCESS_ABORTED; ok = 0;
  }
  if (!CloseHandle(process.hThread)) ok = 0;
  if (!CloseHandle(process.hProcess)) ok = 0;
  if (!CloseHandle(job)) ok = 0;
  if (!ok && !result->error) result->error = ERROR_GEN_FAILURE;
  return ok;
}
typedef struct { HANDLE ready, cancel; DWORD delay; volatile LONG references; } sync_state_t;
static int sync_release(sync_state_t *state) {
  if (InterlockedDecrement(&state->references)) return 1;
  int ok = 1;
  if (state->ready && !CloseHandle(state->ready)) ok = 0;
  if (state->cancel && !CloseHandle(state->cancel)) ok = 0;
  if (!HeapFree(GetProcessHeap(), 0, state)) ok = 0;
  return ok;
}
static DWORD WINAPI signal_event(LPVOID argument) {
  sync_state_t *state = argument;
  DWORD waited = WaitForSingleObject(state->cancel, state->delay);
  DWORD code = 0;
  if (waited != WAIT_OBJECT_0 && (waited != WAIT_TIMEOUT || !SetEvent(state->ready))) code = 1;
  if (!sync_release(state)) code = 1;
  return code;
}
static int sync_operation(uint32_t timeout, uint32_t delay, lab_cap_result_t *result) {
  sync_state_t *state = HeapAlloc(GetProcessHeap(), HEAP_ZERO_MEMORY, sizeof *state);
  if (!state) { result->error = ERROR_NOT_ENOUGH_MEMORY; return 0; }
  state->references = 1; state->delay = delay;
  state->ready = CreateEventW(NULL, TRUE, FALSE, NULL);
  state->cancel = CreateEventW(NULL, TRUE, FALSE, NULL);
  HANDLE thread = NULL;
  int ok = state->ready && state->cancel;
  if (ok) {
    InterlockedIncrement(&state->references);
    thread = CreateThread(NULL, 0, signal_event, state, 0, NULL);
    if (!thread) { InterlockedDecrement(&state->references); ok = 0; }
  }
  if (ok) {
    DWORD waited = WaitForSingleObject(state->ready, timeout);
    ok = waited == WAIT_OBJECT_0;
    if (!ok) result->error = waited == WAIT_TIMEOUT ? ERROR_TIMEOUT : GetLastError();
  }
  if (!ok && !result->error) result->error = GetLastError();
  if (state->cancel && !SetEvent(state->cancel)) { result->error = GetLastError(); ok = 0; }
  if (thread) {
    DWORD waited = WaitForSingleObject(thread, 2000), code = 1;
    if (waited != WAIT_OBJECT_0) { result->error = waited == WAIT_TIMEOUT ? ERROR_TIMEOUT : GetLastError(); ok = 0; }
    else if (!GetExitCodeThread(thread, &code) || code) ok = 0;
    if (!CloseHandle(thread)) ok = 0;
  }
  /* On a cancellation failure, the live thread retains its own state/handles.
     No stack pointer or freed object outlives the bounded caller wait. */
  if (!sync_release(state)) ok = 0;
  if (!ok && !result->error) result->error = ERROR_GEN_FAILURE;
  return ok;
}

int lab_cap_run(uint32_t capability, uint32_t seed, uint32_t timeout, uint32_t delay, int child, lab_cap_result_t *result) {
  memset(result, 0, sizeof *result);
  if (!lab_random_bytes(result->subject, 16)) { result->error = ERROR_GEN_FAILURE; return 0; }
  result->process_id = GetCurrentProcessId();
  FILETIME creation, exit_time, kernel, user;
  if (!GetProcessTimes(GetCurrentProcess(), &creation, &exit_time, &kernel, &user)) { result->error = GetLastError(); return 0; }
  result->generation = ((uint64_t)creation.dwHighDateTime << 32) | creation.dwLowDateTime;
  if (capability == LAB_CAP_FILE) { if (child) Sleep(delay); result->ok = file_operation(seed, result); }
  else if (capability == LAB_CAP_PROC) result->ok = process_operation(seed, timeout, delay, result);
  else if (capability == LAB_CAP_SYNC) result->ok = sync_operation(timeout, delay, result);
  else result->error = ERROR_INVALID_PARAMETER;
  return result->ok == 1;
}
