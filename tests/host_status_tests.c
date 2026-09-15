#define _POSIX_C_SOURCE 200809L
#include "../lab/platform/host_status.h"
#include <stdio.h>
#include <stdlib.h>
#include <errno.h>
#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>

static int ima_paths(void) {
  char directory[]="/tmp/lab-ima-paths-XXXXXX";
  if(!mkdtemp(directory))return 1;
  int root=open(directory,O_RDONLY|O_DIRECTORY|O_CLOEXEC);
  int failed=1,fd=-1;
  if(root<0)goto done;
  if(lab_host_open_ima(root)!=-1 || errno!=ENOENT)goto done;
  fd=openat(root,"ascii_runtime_measurements_sha1",O_CREAT|O_EXCL|O_WRONLY|O_CLOEXEC,0600);
  if(fd<0)goto done;
  if(close(fd)) { fd=-1;goto done; } fd=-1;
  if(symlinkat("ascii_runtime_measurements_sha1",root,"ascii_runtime_measurements"))goto done;
  fd=lab_host_open_ima(root);
  if(fd<0)goto done;
  if(close(fd)) { fd=-1;goto done; } fd=-1;
  if(unlinkat(root,"ascii_runtime_measurements",0))goto done;
  const char *bad[]={"/etc/passwd","../outside","ascii_runtime_measurements_sha1_staged","unknown"};
  for(size_t i=0;i<sizeof bad/sizeof bad[0];++i) {
    if(symlinkat(bad[i],root,"ascii_runtime_measurements"))goto done;
    fd=lab_host_open_ima(root);
    if(fd!=-1 || errno!=ELOOP)goto done;
    if(unlinkat(root,"ascii_runtime_measurements",0))goto done;
  }
  /* Known alias must not resolve a second link, even within the directory. */
  if(unlinkat(root,"ascii_runtime_measurements_sha1",0))goto done;
  if(symlinkat("/etc/passwd",root,"ascii_runtime_measurements_sha1"))goto done;
  if(symlinkat("ascii_runtime_measurements_sha1",root,"ascii_runtime_measurements"))goto done;
  fd=lab_host_open_ima(root);
  if(fd!=-1 || errno!=ELOOP)goto done;
  if(unlinkat(root,"ascii_runtime_measurements",0))goto done;
  if(mkfifoat(root,"ascii_runtime_measurements",0600))goto done;
  fd=lab_host_open_ima(root);
  if(fd!=-1 || errno!=EINVAL)goto done;
  if(unlinkat(root,"ascii_runtime_measurements",0))goto done;
  fd=openat(root,"ascii_runtime_measurements",O_CREAT|O_EXCL|O_WRONLY|O_CLOEXEC,0600);
  if(fd<0)goto done;
  if(close(fd)) { fd=-1;goto done; } fd=-1;
  fd=lab_host_open_ima(root);
  if(fd<0)goto done;
  if(close(fd)) { fd=-1;goto done; } fd=-1;
  failed=0;
done:
  if(fd>=0 && close(fd))failed=1;
  if(root>=0) {
    (void)unlinkat(root,"ascii_runtime_measurements",0);
    (void)unlinkat(root,"ascii_runtime_measurements_sha1",0);
    if(close(root))failed=1;
  }
  if(rmdir(directory))failed=1;
  return failed;
}
int main(void) {
  if(ima_paths()) { fputs("FAIL: IMA path ownership/limits\n",stderr);return 1; }
  uint8_t bytes[7]={7,0,0,0,0,0,0};
  if(lab_host_secure_boot_value(bytes,5)!=LAB_HOST_DISABLED)return 1;
  bytes[4]=1;
  if(lab_host_secure_boot_value(bytes,5)!=LAB_HOST_ENABLED)return 1;
  for(size_t length=0;length<sizeof bytes;++length)
    if(length!=5 && lab_host_secure_boot_value(bytes,length)!=LAB_HOST_UNKNOWN)return 1;
  for(unsigned value=2;value<256;++value) {
    bytes[4]=(uint8_t)value;
    if(lab_host_secure_boot_value(bytes,5)!=LAB_HOST_UNKNOWN)return 1;
  }
  if(lab_host_secure_boot_value(NULL,5)!=LAB_HOST_UNKNOWN)return 1;
  puts("PASS: IMA regular/alias/missing/escape/symlink/FIFO; EFI fixture; truncation, extra bytes and invalid values remain unknown");return 0;
}
