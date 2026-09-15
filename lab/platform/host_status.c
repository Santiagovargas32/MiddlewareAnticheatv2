#define _POSIX_C_SOURCE 200809L
#include "host_status.h"
#include <errno.h>
#include <fcntl.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>
int lab_host_secure_boot_value(const uint8_t *bytes, size_t length) {
  /* efivarfs prepends four attribute bytes; SecureBoot is a UINT8. */
  if (!bytes || length!=5 || bytes[4]>1) return LAB_HOST_UNKNOWN;
  return bytes[4] ? LAB_HOST_ENABLED : LAB_HOST_DISABLED;
}

int lab_host_open_ima(int directory_fd) {
  static const char name[]="ascii_runtime_measurements";
  const int flags=O_RDONLY|O_CLOEXEC|O_NOFOLLOW|O_NONBLOCK;
  int fd=openat(directory_fd,name,flags);
  if(fd<0 && errno==ELOOP) {
    char target[128];
    ssize_t length=readlinkat(directory_fd,name,target,sizeof target);
    if(length<0)return -1;
    const char *allowed[]={"ascii_runtime_measurements_sha1",
                           "ascii_runtime_measurements_sha256",
                           "ascii_runtime_measurements_sha384",
                           "ascii_runtime_measurements_sha512"};
    size_t i;
    for(i=0;i<sizeof allowed/sizeof allowed[0];++i)
      if((size_t)length==strlen(allowed[i]) && !memcmp(target,allowed[i],(size_t)length))break;
    if(i==sizeof allowed/sizeof allowed[0]) { errno=ELOOP;return -1; }
    /* Refuse a second symlink and all paths outside the opened directory. */
    fd=openat(directory_fd,allowed[i],flags);
  }
  if(fd<0)return -1;
  struct stat status;
  if(fstat(fd,&status)<0) {
    int saved=errno;(void)close(fd);errno=saved;return -1;
  }
  if(!S_ISREG(status.st_mode)) { (void)close(fd);errno=EINVAL;return -1; }
  return fd;
}
