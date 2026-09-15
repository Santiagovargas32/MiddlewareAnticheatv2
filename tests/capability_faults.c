#define _POSIX_C_SOURCE 200809L
#include "../lab/platform/capabilities.h"
#include <dirent.h>
#include <errno.h>
#include <stdio.h>
#include <sys/resource.h>
#include <sys/types.h>
#include <unistd.h>
static int fail_fork;
pid_t __real_fork(void);
pid_t __wrap_fork(void);
pid_t __wrap_fork(void) { if (fail_fork) { errno=EAGAIN;return -1; } return __real_fork(); }
static int descriptors(void) {
  DIR *directory=opendir("/proc/self/fd");if(!directory)return -1;
  int count=0;while(readdir(directory))count++;
  if(closedir(directory))return -1;
  return count;
}
#define CHECK(x) do { if(!(x)){fprintf(stderr,"%d: %s\n",__LINE__,#x);return 1;} }while(0)
int main(void) {
  lab_cap_result_t result;
  struct rlimit saved,limited;
  CHECK(getrlimit(RLIMIT_NOFILE,&saved)==0);
  limited=saved;limited.rlim_cur=0;
  CHECK(setrlimit(RLIMIT_NOFILE,&limited)==0);
  int file=lab_cap_run(LAB_CAP_FILE,37,100,0,0,&result);
  int file_error=result.error==EMFILE;
  int proc=lab_cap_run(LAB_CAP_PROC,37,100,0,0,&result);
  int proc_error=result.error==EMFILE;
  CHECK(setrlimit(RLIMIT_NOFILE,&saved)==0);
  CHECK(!file&&!proc&&file_error&&proc_error);
  int before=descriptors();CHECK(before>=0);
  fail_fork=1;
  for(int i=0;i<16;++i)CHECK(!lab_cap_run(LAB_CAP_PROC,37,100,0,0,&result)&&result.error==EAGAIN);
  fail_fork=0;
  for(int i=0;i<8;++i) {
    CHECK(lab_cap_run(LAB_CAP_FILE,37,100,0,0,&result));
    CHECK(lab_cap_run(LAB_CAP_PROC,37,2000,0,0,&result));
    CHECK(!lab_cap_run(LAB_CAP_SYNC,37,10,1000,0,&result)&&result.error==ETIMEDOUT);
  }
  CHECK(descriptors()==before);
  puts("PASS: file/pipe exhaustion, fork failure, cancelled synchronization, descriptor ownership");return 0;
}
