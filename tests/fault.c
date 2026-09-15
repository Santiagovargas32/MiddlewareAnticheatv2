/* Bounded negative UDP client. Exit zero means the expected reason was decoded. */
#define _POSIX_C_SOURCE 200809L
#include "../lab/contracts/lab.h"
#include "../lab/platform/net.h"
#include <stdio.h>
#include <string.h>
#include <unistd.h>

static int message(int fd, uint8_t *wire, size_t size, uint8_t kind, void *payload, uint32_t timeout) {
  if (size && !lab_send(fd,wire,size)) return 0;
  ssize_t n=lab_receive(fd,wire,LAB_MAX_DATAGRAM,timeout);
  lab_hdr_t h;
  return n>=16 && lab_hdr_parse(wire,(size_t)n,&h) && h.magic==LAB_MAGIC && h.version==LAB_VERSION &&
         !h.flags && h.kind==kind && h.len==(uint32_t)n-16 && lab_payload_parse(wire+16,h.len,kind,payload);
}
static size_t encode(uint8_t *wire, uint8_t kind, uint32_t seq, const void *payload) {
  lab_hdr_t h={.magic=LAB_MAGIC,.version=LAB_VERSION,.kind=kind,.seq=seq,.len=(uint32_t)lab_payload_len(kind)};
  lab_hdr_pack(wire,&h); lab_payload_pack(wire+16,LAB_MAX_DATAGRAM-16,kind,payload);return 16+h.len;
}
int main(int argc,char **argv) {
  const char *host="127.0.0.1",*test=NULL;
  uint32_t port=7777,timeout=1000;
  for(int i=1;i<argc;++i) {
    if(i+1==argc)return 2;
    const char *option=argv[i++],*value=argv[i];
    if(!strcmp(option,"--host"))host=value;
    else if(!strcmp(option,"--case"))test=value;
    else if(!strcmp(option,"--port")){if(!lab_parse_u32(value,1,65535,&port))return 2;}
    else if(!strcmp(option,"--timeout-ms")){if(!lab_parse_u32(value,1,60000,&timeout))return 2;}
    else return 2;
  }
  const char *names[]={"bad-magic","bad-version","bad-kind","bad-payload","bad-len","bad-session","dup","replay","trunc","bad-seq","stale","too-big","timeout"};
  int which=-1;
  for(size_t i=0;i<sizeof names/sizeof names[0];++i)if(test&&!strcmp(test,names[i]))which=(int)i;
  if(which<0 || strlen(host)>15)return 2;
  char text[24];snprintf(text,sizeof text,"%s:%u",host,port);
  struct sockaddr_in peer,local={.sin_family=AF_INET,.sin_addr.s_addr=htonl(INADDR_LOOPBACK)};
  if(!lab_endpoint(text,&peer))return 2;
  int fd=lab_udp_bound(&local),ok=0;
  if(fd<0)return 1;
  if(connect(fd,(struct sockaddr *)&peer,sizeof peer)<0)goto done;
  lab_hello_t hello={.app_id=LAB_APP_ID};
  memcpy(hello.app,LAB_APP_NAME,sizeof LAB_APP_NAME);memcpy(hello.name,"fault",6);
  if(!lab_random_bytes(hello.nonce,16))goto done;
  uint8_t wire[LAB_MAX_DATAGRAM+1];
  size_t size=encode(wire,LAB_HELLO,0,&hello);
  uint32_t reason=LAB_OK;
  if(which==0){wire[0]^=1;reason=LAB_BAD_MAGIC;}
  else if(which==1){wire[1]=1;reason=LAB_BAD_VERSION;}
  else if(which==2){wire[2]=LAB_PING;reason=LAB_BAD_KIND;}
  else if(which==3){wire[16]^=1;reason=LAB_BAD_PAYLOAD;}
  else if(which==4){wire[8]--;reason=LAB_BAD_LEN;}
  else if(which==11){memset(wire+size,0,sizeof wire-size);size=sizeof wire;reason=LAB_TOO_BIG;}
  lab_rst_t rst;
  if(reason){ok=message(fd,wire,size,LAB_RST,&rst,timeout)&&rst.reason==reason;goto done;}
  lab_hello_ack_t ack;
  if(!message(fd,wire,size,LAB_HELLO_ACK,&ack,timeout)||ack.result!=1||ack.reason||memcmp(ack.cnonce,hello.nonce,16))goto done;
  lab_ping_t ping={.stamp=1234};memcpy(ping.session,ack.session,16);memset(ping.nonce,'n',16);
  lab_pong_t pong;
  if(which==6){
    hello.nonce[0]^=1;size=encode(wire,LAB_HELLO,0,&hello);reason=LAB_DUP_SESSION;
  }else if(which==12){size=0;reason=LAB_TIMEOUT;
  }else{
    if(which==7){size=encode(wire,LAB_PING,1,&ping);if(!message(fd,wire,size,LAB_PONG,&pong,timeout)||pong.stamp!=1234||memcmp(pong.echo,ping.nonce,16))goto done;}
    if(which==10){
      lab_bye_t bye={0};memcpy(bye.session,ack.session,16);
      size=encode(wire,LAB_BYE,2,&bye);
      if(!message(fd,wire,size,LAB_RST,&rst,timeout)||rst.reason||memcmp(rst.session,ack.session,16))goto done;
    }
    if(which==5)ping.session[0]^=1;
    size=encode(wire,LAB_PING,which==9?10:1,&ping);
    if(which==8)size-=8;
    reason=which==5?LAB_BAD_SESSION:which==7?LAB_REPLAY:which==8?LAB_BAD_LEN:which==9?LAB_BAD_SEQ:LAB_BAD_KIND;
  }
  ok=message(fd,wire,size,LAB_RST,&rst,timeout)&&rst.reason==reason;
  if(ok&&which!=10)ok=!memcmp(rst.session,ack.session,16);
done:
  if(close(fd)<0)ok=0;
  printf("{\"case\":\"%s\",\"ok\":%s}\n",names[which],ok?"true":"false");
  return ok?0:1;
}
