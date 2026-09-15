"""lab-attest/1: one-use challenges and verification against an operator-pinned AK.

A verified signature is NOT proof of genuine TPM hardware or a cheat-free host.
PCR 0/7 values are informational in pinned-ak-quote-v1; selection is required.
"""
import argparse
import asyncio
import base64
import hashlib
import json
from pathlib import Path
import secrets
import signal
import struct
import subprocess
import tempfile
import time
import threading
from bridge_transport import tls_context

PROTOCOL='lab-attest/1'
POLICY='pinned-ak-quote-v1'
MAX_FRAME=16384


def no_duplicates(pairs):
    out={}
    for key,value in pairs:
        if key in out: raise ValueError('DUPLICATE_FIELD')
        out[key]=value
    return out


def decode(raw):
    if not 0<len(raw)<=MAX_FRAME: raise ValueError('FRAME_SIZE')
    def invalid_number(value): raise ValueError('INVALID_NUMBER')
    try:
        value=json.loads(raw.decode('utf-8','strict'),object_pairs_hook=no_duplicates,parse_constant=invalid_number,parse_float=invalid_number)
    except RecursionError as error: raise ValueError('JSON_DEPTH') from error
    def validate(item,depth=0):
        if depth>4: raise ValueError('JSON_DEPTH')
        if isinstance(item,str): item.encode('utf-8','strict')
        elif isinstance(item,dict):
            for key,child in item.items(): validate(key,depth+1);validate(child,depth+1)
        elif isinstance(item,list):
            for child in item: validate(child,depth+1)
    validate(value)
    if not isinstance(value,dict): raise ValueError('OBJECT_REQUIRED')
    return value


def encode(value):
    raw=json.dumps(value,separators=(',',':'),allow_nan=False).encode()
    if not 0<len(raw)<=MAX_FRAME: raise ValueError('FRAME_SIZE')
    return struct.pack('!I',len(raw))+raw


async def receive(reader, timeout=4):
    async def read():
        size=struct.unpack('!I',await reader.readexactly(4))[0]
        if not 0<size<=MAX_FRAME: raise ValueError('FRAME_SIZE')
        return decode(await reader.readexactly(size))
    return await asyncio.wait_for(read(),timeout)


def qualification(challenge):
    # Fixed binary input, not a signature over ambiguous JSON serialization.
    data=(b'lab-attest/1\0'+bytes.fromhex(challenge['session_id'])+bytes.fromhex(challenge['nonce'])+
          struct.pack('!QQ',challenge['created_at'],challenge['expires_at'])+
          hashlib.sha256(challenge['policy_id'].encode('ascii')).digest()+bytes.fromhex(challenge['ak_sha256']))
    return hashlib.sha256(data).hexdigest()


class PcrReference:
    """Immutable operator-provided PCR values; never enroll remote values."""
    def __init__(self,path):
        with Path(path).open('rb') as source: value=decode(source.read(MAX_FRAME+1))
        if set(value)!={'policy_version','sha256'} or value['policy_version']!='pcr-reference/1':
            raise ValueError('INVALID_PCR_POLICY')
        bank=value['sha256']
        if not isinstance(bank,dict) or set(bank)!={'0','7'}: raise ValueError('INVALID_PCR_POLICY')
        parts=[]
        for index in ('0','7'):
            encoded=bank[index]
            if not isinstance(encoded,str) or len(encoded)!=64 or any(c not in '0123456789abcdef' for c in encoded):
                raise ValueError('INVALID_PCR_POLICY')
            parts.append(bytes.fromhex(encoded))
        self.expected=b''.join(parts)
        self.policy_id='pcr-reference-v1:'+hashlib.sha256(self.expected).hexdigest()


class QuoteVerifier:
    def __init__(self,public_key,inspector,pcr_policy=None,*,pcr_selection="sha256:0,7"):
        if pcr_selection not in ('sha256:0,7','sha256:10'): raise ValueError('PCR_SELECTION_UNSUPPORTED')
        if pcr_policy is not None and pcr_selection!='sha256:0,7': raise ValueError('PCR_POLICY_SELECTION')
        self.pcr_selection=pcr_selection
        self.pcr_size=64 if pcr_selection=='sha256:0,7' else 32
        self.selection_field='pcr_selection_matches' if self.pcr_size==64 else 'pcr10_selection_matches'
        self.public_key=Path(public_key).read_bytes()
        if not 0<len(self.public_key)<=8192: raise ValueError('AK_SIZE')
        self.ak_sha256=hashlib.sha256(self.public_key).hexdigest()
        self.inspector=str(Path(inspector).resolve())
        self.reference=PcrReference(pcr_policy) if pcr_policy is not None else None
        self.policy_id=self.reference.policy_id if self.reference else POLICY if self.pcr_size==64 else 'pinned-ak-pcr10-quote-v1'

    def verify(self,evidence,challenge):
        started=time.perf_counter()
        decoded={}
        for field,limit in [('quote',4096),('signature',1024),('pcrs',self.pcr_size)]:
            value=evidence[field]
            if not isinstance(value,str): raise ValueError('INVALID_PAYLOAD')
            data=base64.b64decode(value,validate=True)
            if not 0<len(data)<=limit: raise ValueError('INVALID_PAYLOAD')
            decoded[field]=data
        if len(decoded['pcrs'])!=self.pcr_size: raise ValueError('PCR_SIZE')
        with tempfile.TemporaryDirectory(prefix='lab-quote-verify-') as directory:
            folder=Path(directory)
            (folder/'ak.pem').write_bytes(self.public_key)
            for key,data in decoded.items(): (folder/key).write_bytes(data)
            inspected=subprocess.run([self.inspector,str(folder/'quote')],capture_output=True,text=True,timeout=3)
            if inspected.returncode: return dict(cryptographic_validity='failed',freshness_validity='not_verified',policy_validity='not_evaluated',reason='MALFORMED_QUOTE')
            structure=json.loads(inspected.stdout)
            # No TPM access in verification. The public key came from enrollment,
            # never from the evidence request or a remote path.
            result=subprocess.run(['tpm2_checkquote','-u',str(folder/'ak.pem'),'-m',str(folder/'quote'),'-s',str(folder/'signature'),
                                   '-f',str(folder/'pcrs'),'-l',self.pcr_selection,'-g','sha256','-q',structure['qualification']],capture_output=True,timeout=3)
        crypto=result.returncode==0
        fresh=secrets.compare_digest(structure['qualification'],qualification(challenge))
        selection=structure[self.selection_field]
        reference_matches=self.reference is None or secrets.compare_digest(decoded['pcrs'],self.reference.expected)
        policy=selection and reference_matches
        reference_validity=('not_configured' if self.reference is None else
                            'not_evaluated' if not (crypto and fresh and selection) else
                            'matched' if reference_matches else 'mismatch')
        reason='SIGNATURE_OR_PCR_DIGEST_INVALID' if not crypto else 'NONCE_MISMATCH' if not fresh else 'PCR_SELECTION_MISMATCH' if not selection else 'PCR_REFERENCE_MISMATCH' if not reference_matches else 'SCOPED_POLICY_PASS'
        return dict(cryptographic_validity='verified' if crypto else 'failed',freshness_validity='verified' if crypto and fresh else 'failed' if crypto else 'not_verified',
                    policy_validity='passed' if crypto and fresh and policy else 'failed' if crypto and fresh else 'not_evaluated',reason=reason,pcr_reference_validity=reference_validity,
                    quote_verification_ms=round((time.perf_counter()-started)*1000))


class AttestationServer:
    def __init__(self,verifier,ttl_ms=10000,maximum=64,clock=time.monotonic,wall=time.time):
        if not 1<=ttl_ms<=60000: raise ValueError('TTL_RANGE')
        self.policy_id=getattr(verifier,'policy_id',POLICY)
        self.verifier=verifier;self.ttl_ms=ttl_ms;self.maximum=maximum;self.clock=clock;self.wall=wall;self.sessions={};self.lock=threading.RLock();self.tasks=set()

    def issue(self,owner):
        with self.lock: return self._issue(owner)

    def _issue(self,owner):
        now=self.clock()
        self.sessions={sid:session for sid,session in self.sessions.items() if now<session['deadline']+60}
        if len(self.sessions)>=self.maximum: raise ValueError('SESSION_LIMIT')
        sid=secrets.token_hex(16)
        for _ in range(4):
            if sid not in self.sessions: break
            sid=secrets.token_hex(16)
        else: raise ValueError('ENTROPY_COLLISION')
        created=int(self.wall()*1000)
        challenge=dict(protocol_version=PROTOCOL,session_id=sid,nonce=secrets.token_hex(32),created_at=created,expires_at=created+self.ttl_ms,
                       policy_id=self.policy_id,requested_evidence=['tpm_quote',getattr(self.verifier,'pcr_selection','sha256:0,7')],ak_sha256=self.verifier.ak_sha256)
        self.sessions[sid]=dict(owner=owner,challenge=challenge,deadline=now+self.ttl_ms/1000,used=False)
        return json.loads(json.dumps(challenge))

    def submit(self,owner,message):
        expected={'protocol_version','session_id','quote','signature','pcrs'}
        if set(message)!=expected or message['protocol_version']!=PROTOCOL: raise ValueError('INVALID_SCHEMA')
        sid=message['session_id']
        if not isinstance(sid,str) or len(sid)!=32: raise ValueError('INVALID_SESSION')
        with self.lock:
            session=self.sessions.get(sid)
            base=dict(protocol_version=PROTOCOL,session_id=sid,decision='DENY',cryptographic_validity='not_verified',freshness_validity='failed',
                      policy_validity='not_evaluated',tpm_identity_validity='not_proven',enrollment='operator_pinned_ak_lab',policy_id=self.policy_id,
                      pcr_reference_validity='not_evaluated' if self.policy_id!=POLICY else 'not_configured')
            if not session or owner!=session['owner']: return dict(base,reasons=['UNKNOWN_SESSION'])
            if session['used']: return dict(base,reasons=['CHALLENGE_REUSED'])
            if self.clock()>=session['deadline']: return dict(base,reasons=['CHALLENGE_EXPIRED'])
            # One attempt per challenge, including invalid cryptographic evidence.
            session['used']=True
        try: result=self.verifier.verify(message,session['challenge'])
        except ValueError: return dict(base,reasons=['INVALID_PAYLOAD'])
        except (OSError,subprocess.SubprocessError): return dict(base,decision='INDETERMINATE',reasons=['VERIFIER_ERROR'])
        reason=result.pop('reason');base.update(result)
        if self.clock()>=session['deadline']:
            base['freshness_validity']='failed';base['policy_validity']='not_evaluated';reason='CHALLENGE_EXPIRED'
        base.update(reasons=[reason],decision='ALLOW' if reason=='SCOPED_POLICY_PASS' else 'DENY')
        return base

    async def handle(self,reader,writer):
        task=asyncio.current_task()
        if len(self.tasks)>=4:
            writer.close();return
        self.tasks.add(task)
        try:
            cert=writer.get_extra_info('ssl_object').getpeercert(binary_form=True)
            owner=hashlib.sha256(cert).hexdigest()
            request=await receive(reader)
            if request!={'protocol_version':PROTOCOL,'message_type':'session'}: raise ValueError('INVALID_SCHEMA')
            challenge=self.issue(owner);writer.write(encode(challenge));await asyncio.wait_for(writer.drain(),4)
            evidence=await receive(reader,timeout=self.ttl_ms/1000+1)
            result=await asyncio.to_thread(self.submit,owner,evidence)
            writer.write(encode(result));await asyncio.wait_for(writer.drain(),4)
        except (OSError,ValueError,asyncio.TimeoutError,asyncio.IncompleteReadError):
            # Connection failure never emits ALLOW. No raw evidence in logs.
            pass
        finally:
            writer.close()
            try: await asyncio.wait_for(writer.wait_closed(),1)
            except (OSError,asyncio.TimeoutError): pass
            self.tasks.discard(task)

    async def close(self):
        tasks=list(self.tasks)
        for task in tasks: task.cancel()
        await asyncio.gather(*tasks,return_exceptions=True)


async def serve(args):
    verifier=QuoteVerifier(args.ak_public,args.inspector,args.pcr_policy)
    service=AttestationServer(verifier)
    server=await asyncio.start_server(service.handle,args.host,args.port,ssl=tls_context(args.cert,args.key,args.ca,True),ssl_handshake_timeout=3,ssl_shutdown_timeout=1)
    print(json.dumps(dict(ev='boot',port=server.sockets[0].getsockname()[1],protocol_version=PROTOCOL,policy_id=verifier.policy_id,enrollment='operator_pinned_ak_lab')),flush=True)
    stop=asyncio.Event();loop=asyncio.get_running_loop()
    for sig in (signal.SIGINT,signal.SIGTERM): loop.add_signal_handler(sig,stop.set)
    try:
        async with server: await stop.wait()
    finally:
        await service.close()
        for sig in (signal.SIGINT,signal.SIGTERM): loop.remove_signal_handler(sig)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ak-public',type=Path,required=True)
    parser.add_argument('--pcr-policy',type=Path,help='Operator-approved PCR reference JSON; never learned from a client')
    parser.add_argument('--inspector',type=Path,default=Path('build-tpm/lab_quote_inspect'))
    parser.add_argument('--host',default='127.0.0.1');parser.add_argument('--port',type=int,default=9444)
    for name in ['cert','key','ca']:parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args()
    try: asyncio.run(serve(args))
    except KeyboardInterrupt: return 0
    return 0


if __name__=='__main__':raise SystemExit(main())
