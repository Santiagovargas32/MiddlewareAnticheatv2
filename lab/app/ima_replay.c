/* Linux IMA SHA256-bank binary log, explicit little-endian, PCR 10 only.
 * Local replay is not remote attestation or approval of measured files. */
#define _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>
#include <openssl/crypto.h>
#include <openssl/evp.h>

#define MAX_BYTES (64u*1024u*1024u)
#define MAX_DATA 65536u
#define MAX_RECORDS 100000u
struct input { int fd; size_t bytes; struct timespec start; const char *error; };
static uint32_t le32(const uint8_t *p) {
  return (uint32_t)p[0]|(uint32_t)p[1]<<8|(uint32_t)p[2]<<16|(uint32_t)p[3]<<24;
}
static int take(struct input *in,uint8_t *out,size_t length) {
  if(length>MAX_BYTES-in->bytes) { in->error="BYTE_LIMIT";return -1; }
  size_t used=0;
  while(used<length) {
    struct timespec now;
    if(clock_gettime(CLOCK_MONOTONIC,&now)) { in->error="CLOCK_ERROR";return -1; }
    double elapsed=(double)(now.tv_sec-in->start.tv_sec)+(double)(now.tv_nsec-in->start.tv_nsec)/1e9;
    if(elapsed>=3.0) { in->error="TIME_LIMIT";return -1; }
    ssize_t n=read(in->fd,out+used,length-used);
    if(n<0 && errno==EINTR)continue;
    if(n<0) { in->error="READ_ERROR";return -1; }
    if(!n) { in->error="TRUNCATED_RECORD";return used?-1:0; }
    used+=(size_t)n;in->bytes+=(size_t)n;
  }
  return 1;
}
static int hash(const uint8_t *data,size_t size,uint8_t out[32]) {
  unsigned length=0;
  return EVP_Digest(data,size,out,&length,EVP_sha256(),NULL)==1 && length==32;
}
static int digest_field(const uint8_t *data,size_t size) {
  static const char *names[]={"sha1:","sha256:","sha384:","sha512:"};
  static const size_t lengths[]={20,32,48,64};
  for(size_t i=0;i<4;++i) {
    size_t prefix=strlen(names[i])+1;
    if(size==prefix+lengths[i] && !memcmp(data,names[i],prefix))return 1;
  }
  return 0;
}
static int fields_valid(const uint8_t *data,size_t size,unsigned fields) {
  size_t offset=0;
  for(unsigned field=0;field<fields;++field) {
    if(size-offset<4)return 0;
    size_t length=le32(data+offset);offset+=4;
    if(length>size-offset)return 0;
    if(field==0 && !digest_field(data+offset,length))return 0;
    if(field==1 && (!length || length>4096 || data[offset+length-1]!=0 ||
                   memchr(data+offset,0,length-1)!=NULL))return 0;
    offset+=length;
  }
  return offset==size;
}
static int replay(struct input *in,uint8_t pcr[32],size_t *records) {
  uint8_t header[40],name[32],length_bytes[4],data[MAX_DATA],digest[32],extend[64];
  for(;;) {
    int status=take(in,header,4);
    if(status==0)break;
    if(status<0)return 0;
    if(*records>=MAX_RECORDS) { in->error="RECORD_LIMIT";return 0; }
    if(take(in,header+4,36)!=1)return 0;
    if(le32(header)!=10) { in->error="UNSUPPORTED_PCR";return 0; }
    size_t name_length=le32(header+36);
    if(!name_length || name_length>sizeof name) { in->error="TEMPLATE_NAME_SIZE";return 0; }
    if(take(in,name,name_length)!=1)return 0;
    unsigned fields;
    if(name_length==6 && !memcmp(name,"ima-ng",6))fields=2;
    else if(name_length==7 && !memcmp(name,"ima-sig",7))fields=3;
    else { in->error="UNSUPPORTED_TEMPLATE";return 0; }
    if(take(in,length_bytes,4)!=1)return 0;
    size_t length=le32(length_bytes);
    if(!length || length>MAX_DATA) { in->error="TEMPLATE_DATA_SIZE";return 0; }
    if(take(in,data,length)!=1)return 0;
    if(!fields_valid(data,length,fields)) { in->error="INVALID_TEMPLATE_FIELDS";return 0; }
    uint8_t zero[32]={0};
    if(!CRYPTO_memcmp(header+4,zero,32)) { in->error="IMA_VIOLATION";return 0; }
    if(!hash(data,length,digest)) { in->error="CRYPTO_ERROR";return 0; }
    if(CRYPTO_memcmp(digest,header+4,32)) { in->error="TEMPLATE_DIGEST_MISMATCH";return 0; }
    memcpy(extend,pcr,32);memcpy(extend+32,digest,32);
    if(!hash(extend,sizeof extend,pcr)) { in->error="CRYPTO_ERROR";return 0; }
    ++*records;
  }
  if(!*records) { in->error="EMPTY_LOG";return 0; }
  return 1;
}
int main(int argc,char **argv) {
  if(argc!=2)return 2;
  struct input in={.fd=-1,.error="OPEN_ERROR"};
  uint8_t pcr[32]={0};size_t records=0;int success=0;
  in.fd=open(argv[1],O_RDONLY|O_CLOEXEC|O_NOFOLLOW|O_NONBLOCK);
  if(in.fd>=0) {
    struct stat status;
    if(fstat(in.fd,&status) || !S_ISREG(status.st_mode))in.error="NOT_REGULAR_FILE";
    else if(clock_gettime(CLOCK_MONOTONIC,&in.start))in.error="CLOCK_ERROR";
    else success=replay(&in,pcr,&records);
    if(close(in.fd)) { in.error="CLOSE_ERROR";success=0; }
  }
  printf("{\"protocol\":\"lab-ima-replay/1\",\"parsed\":%s,\"records\":%zu,\"bytes\":%zu,\"attestation_verified\":false,\"reason\":\"%s\"",
         success?"true":"false",records,in.bytes,success?"REPLAY_COMPLETE":in.error);
  if(success) {
    printf(",\"replayed_pcr_sha256\":\"");
    for(size_t i=0;i<32;++i)printf("%02x",pcr[i]);
    printf("\"");
  }
  puts("}");
  return fflush(stdout)==EOF?1:success?0:1;
}
