/* Read-only discovery, not an integrity assertion or TPM attestation. */
#define _POSIX_C_SOURCE 200809L
#include "../platform/host_status.h"
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

static ssize_t read_small(const char *path, uint8_t *bytes, size_t capacity, int *error) {
  int fd=open(path,O_RDONLY|O_CLOEXEC|O_NOFOLLOW);
  if (fd<0) { *error=errno; return -1; }
  size_t total=0;
  while(total<capacity) {
    ssize_t n=read(fd,bytes+total,capacity-total);
    if(n<0&&errno==EINTR)continue;
    if(n<0) { *error=errno;close(fd);return -1; }
    if(!n)break;
    total+=(size_t)n;
  }
  if(close(fd)) { *error=errno;return -1; }
  *error=0;return (ssize_t)total;
}
static void device(const char *key,const char *path) {
  struct stat status;
  int present=stat(path,&status)==0;
  int error=present?0:errno;
  printf("\"%s\":{\"visible_character_device\":%s,\"error\":%d}",key,
         present&&S_ISCHR(status.st_mode)?"true":"false",error);
}
int main(int argc,char **argv) {
  if(argc!=1 && !(argc==2 && !strcmp(argv[1],"--diagnose")))return 2;
  uint8_t bytes[32];int error=0;
  ssize_t n=read_small("/sys/firmware/efi/efivars/SecureBoot-8be4df61-93ca-11d2-aa0d-00e098032b8c",bytes,sizeof bytes,&error);
  int secure=n<0?LAB_HOST_UNKNOWN:lab_host_secure_boot_value(bytes,(size_t)n);
  if(n>=0&&secure==LAB_HOST_UNKNOWN)error=EPROTO;
  printf("{\"protocol\":\"lab-host-diagnostic/1\",\"origin_os\":\"linux\",\"evidence_class\":\"self_reported_lab\",\"host_integrity\":\"not_attested\",\"cheat_absence\":\"not_proven\",\"secure_boot\":{\"reported_state\":\"%s\",\"error\":%d},",
         secure==LAB_HOST_ENABLED?"enabled":secure==LAB_HOST_DISABLED?"disabled":"unknown",error);
  n=read_small("/sys/class/tpm/tpm0/tpm_version_major",bytes,sizeof bytes,&error);
  int version=n==2 && bytes[1]=='\n' && (bytes[0]=='1'||bytes[0]=='2') ? bytes[0]-'0' : 0;
  if(n>=0&&!version)error=EPROTO;
  printf("\"tpm_sysfs\":{\"reported_version\":%d,\"error\":%d},",version,error);
  device("tpmrm0","/dev/tpmrm0");putchar(',');device("tpm0","/dev/tpm0");
  /* Only test opening the measurement list; never print file names or hashes. */
  /* New kernels expose ima as an alias of integrity/ima. Use the canonical
   * directory first; old kernels may still expose the directory directly. */
  int directory_fd=open("/sys/kernel/security/integrity/ima",O_RDONLY|O_CLOEXEC|O_DIRECTORY|O_NOFOLLOW);
  if(directory_fd<0 && errno==ENOENT)
    directory_fd=open("/sys/kernel/security/ima",O_RDONLY|O_CLOEXEC|O_DIRECTORY|O_NOFOLLOW);
  int fd=directory_fd<0?-1:lab_host_open_ima(directory_fd);
  error=fd<0?errno:0;
  if(directory_fd>=0 && close(directory_fd) && !error)error=errno;
  int readable=fd>=0 && !error;
  if(fd>=0&&close(fd)) { readable=0;error=errno; }
  printf(",\"ima\":{\"measurement_list_openable\":%s,\"error\":%d},\"attestation_verified\":false}\n",readable?"true":"false",error);
  return fflush(stdout)==EOF?1:0;
}
