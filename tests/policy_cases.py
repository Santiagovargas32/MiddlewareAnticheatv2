"""Independent struct fixtures for the evidence transaction and rejection policy."""
import json
import socket
import struct
import time


def request(h, session, instance, request_id=1, origin=1, cap=1, evidence=1, seed=37, sequence=1):
    return h.packet(0x40,struct.pack('<16sI16sBBBBI',session,request_id,instance,origin,cap,evidence,0,seed),sequence)


def observation(h,session,instance,request_id=1,origin=1,cap=1,evidence=1,sequence=2):
    import hashlib
    digest=hashlib.sha256(bytes((i*7+37)&255 for i in range(4096))).digest()
    payload=struct.pack('<16sI16s16sBBBBIII36s',session,request_id,instance,b's'*16,origin,cap,evidence,1,37,10,0,struct.pack('<I32s',4096,digest))
    return h.packet(0x41,payload,sequence)


def decision(h,response,session,request_id,status,reason,sequence):
    h.require(response==h.packet(0x42,struct.pack('<16sIII',session,request_id,status,reason),sequence),f'decision unexpected: {response.hex()}')


def cases(h,build,directory,evidence):
    with h.server(build/'lab_server',directory,evidence) as peer:
        with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as c:
            c.settimeout(1); instance=b'i'*16; session=h.open_session(c,peer,instance)
            # All rejections leave both request and sequence available.
            for changes, reason in [({'origin':7},19),({'cap':8},20),({'evidence':2},21),({'instance':b'j'*16},22)]:
                values={'session':session,'instance':instance};values.update(changes)
                decision(h,h.exchange(c,peer,request(h,**values)),session,1,0,reason,1)
            decision(h,h.exchange(c,peer,request(h,session,instance)),session,1,1,0,1)
            decision(h,h.exchange(c,peer,request(h,session,instance)),session,1,0,10,1)
            decision(h,h.exchange(c,peer,request(h,session,instance,request_id=2,sequence=2)),session,2,0,14,2)
            good=observation(h,session,instance)
            malformed=bytearray(good);malformed[71]=0 # ok=false at header16+55
            decision(h,h.exchange(c,peer,malformed),session,1,0,5,2)
            decision(h,h.exchange(c,peer,observation(h,session,instance,request_id=2)),session,2,0,24,2)
            decision(h,h.exchange(c,peer,observation(h,session,instance,sequence=1)),session,1,0,10,1)
            decision(h,h.exchange(c,peer,good),session,1,2,0,2)
            decision(h,h.exchange(c,peer,good),session,1,0,24,2)
            h.ping_session(c,peer,session,3)
            evidence['cases'].append('evidence_rejections_preserve_request_and_sequence')
            decision(h,h.exchange(c,peer,request(h,session,instance,request_id=2,sequence=4)),session,2,1,0,4)
            time.sleep(1.1)
            decision(h,h.exchange(c,peer,observation(h,session,instance,request_id=2,sequence=5)),session,2,0,23,5)
            decision(h,h.exchange(c,peer,request(h,session,instance,request_id=3,sequence=5)),session,3,1,0,5)
            decision(h,h.exchange(c,peer,observation(h,session,instance,request_id=3,sequence=6)),session,3,2,0,6)
            evidence['cases'].append('expired_request_replaced_without_sequence_consumption')
        for op in ['file','proc','sync']:
            result=h.build_checks.run([str(build/'lab_client'),'--port',str(peer[1]),'--op',op,'--count','1','--delay','10'],4)
            lines=[json.loads(line) for line in result['stdout'].splitlines()]
            h.require(result['exit_code']==0 and len(lines)==2 and lines[0]['status']==2 and lines[0]['origin_os']=='linux' and lines[1]['ok'],f'native capability {op} failed: {result}')
            evidence['checks'].append(result)
            evidence['cases'].append('native_evidence_'+op)
