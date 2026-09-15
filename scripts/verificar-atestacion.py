"""Offline TPM-format fixtures signed by a SOFTWARE test key, never hardware proof."""
import argparse
import asyncio
import base64
import hashlib
import importlib.util
import json
import random
import ssl
from pathlib import Path
import struct
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
import tpm_attestation as a


def command(arguments):
    return subprocess.run(arguments,capture_output=True,check=True,timeout=10)


def fixture(challenge,directory,pcrs=None,nonce=None,selection=b'\x81\0\0'):
    pcrs=pcrs or bytes(range(64))
    extra=bytes.fromhex(nonce or a.qualification(challenge))
    # Independent TPMS_ATTEST fixture, big endian, SHA256 PCRs 0 and 7.
    quote=(struct.pack('!IH',0xff544347,0x8018)+struct.pack('!H',0)+struct.pack('!H',len(extra))+extra+
           struct.pack('!QIIBQ',0,0,0,1,0)+struct.pack('!IHB',1,0x000b,3)+selection+
           struct.pack('!H',32)+hashlib.sha256(pcrs).digest())
    (directory/'quote').write_bytes(quote)
    command(['openssl','dgst','-sha256','-sign',str(directory/'private.pem'),'-out',str(directory/'signature'),str(directory/'quote')])
    raw=(directory/'signature').read_bytes()
    signature=struct.pack('!HHH',0x0014,0x000b,len(raw))+raw
    return dict(protocol_version=a.PROTOCOL,session_id=challenge['session_id'],quote=base64.b64encode(quote).decode(),signature=base64.b64encode(signature).decode(),pcrs=base64.b64encode(pcrs).decode())



async def tls_case(folder,verifier):
    spec=importlib.util.spec_from_file_location('bridge_checks',Path(__file__).with_name('verificar-puente.py'))
    helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper)
    helper.certificates(folder)
    service=a.AttestationServer(verifier)
    server=await asyncio.start_server(service.handle,'127.0.0.1',0,ssl=a.tls_context(folder/'server.crt',folder/'server.key',folder/'ca.crt',True),ssl_handshake_timeout=3,ssl_shutdown_timeout=1)
    async def exchange(replayed=None):
        reader,writer=await asyncio.open_connection('127.0.0.1',server.sockets[0].getsockname()[1],ssl=a.tls_context(folder/'client.crt',folder/'client.key',folder/'ca.crt'),server_hostname='localhost')
        try:
            writer.write(a.encode({'protocol_version':a.PROTOCOL,'message_type':'session'}));await writer.drain()
            challenge=await a.receive(reader)
            evidence=replayed or fixture(challenge,folder)
            writer.write(a.encode(evidence));await writer.drain()
            return await a.receive(reader),evidence
        finally:
            writer.close();await writer.wait_closed()
    try:
        # Trusted server without a client certificate must never issue a challenge.
        reader=None;writer=None
        try:
            reader,writer=await asyncio.wait_for(asyncio.open_connection('127.0.0.1',server.sockets[0].getsockname()[1],ssl=ssl.create_default_context(cafile=str(folder/'ca.crt')),server_hostname='localhost'),2)
            assert await asyncio.wait_for(reader.read(1),2)==b''
        except (ssl.SSLError,ConnectionError): pass
        finally:
            if writer:
                writer.close()
                try: await asyncio.wait_for(writer.wait_closed(),1)
                except (ssl.SSLError,ConnectionError): pass
        assert not service.sessions, 'unauthenticated connection created session'
        result,evidence=await exchange();assert result['decision']=='ALLOW',result
        result,_=await exchange(evidence);assert result['reasons']==['CHALLENGE_REUSED'],result
    finally:
        server.close();await server.wait_closed();await service.close()



async def framing_cases():
    # A producer deliberately yields between fragments; no timing assumptions.
    value={'protocol_version':a.PROTOCOL,'message_type':'session'}
    frame=a.encode(value);reader=asyncio.StreamReader()
    async def feed():
        for byte in frame:
            reader.feed_data(bytes([byte]));await asyncio.sleep(0)
    producer=asyncio.create_task(feed())
    assert await a.receive(reader)==value
    await producer
    reader.feed_data(frame+frame)
    assert await a.receive(reader)==value and await a.receive(reader)==value
    for raw in [struct.pack('!I',0),struct.pack('!I',a.MAX_FRAME+1),frame[:2],frame[:-1]]:
        reader=asyncio.StreamReader();reader.feed_data(raw);reader.feed_eof()
        try: await a.receive(reader);raise AssertionError('invalid frame accepted')
        except (ValueError,asyncio.IncompleteReadError): pass
    # An already idle reader must hit its own deadline, with no polling/retries.
    try: await a.receive(asyncio.StreamReader(),timeout=0.02);raise AssertionError('no deadline')
    except asyncio.TimeoutError: pass


def state_cases(verifier,folder):
    now=[0.0]
    server=a.AttestationServer(verifier,ttl_ms=100,maximum=1,clock=lambda:now[0])
    challenge=server.issue('client');evidence=fixture(challenge,folder)
    try:server.issue('client');raise AssertionError('capacity ignored')
    except ValueError as error: assert str(error)=='SESSION_LIMIT'
    malformed=dict(evidence,quote='not base64')
    assert server.submit('client',malformed)['reasons']==['INVALID_PAYLOAD']
    assert server.submit('client',evidence)['reasons']==['CHALLENGE_REUSED']
    now[0]=61
    fresh=server.issue('client')
    assert len(server.sessions)==1 and fresh['session_id']!=challenge['session_id']
    assert server.submit('client',evidence)['reasons']==['UNKNOWN_SESSION']
    # Expiration DURING a cryptographically successful verification cannot ALLOW.
    class DelayedVerifier:
        ak_sha256=verifier.ak_sha256
        def verify(self,evidence,challenge):
            result=verifier.verify(evidence,challenge);now[0]+=1;return result
    server=a.AttestationServer(DelayedVerifier(),ttl_ms=100,clock=lambda:now[0])
    challenge=server.issue('client');result=server.submit('client',fixture(challenge,folder))
    assert result['decision']=='DENY' and result['reasons']==['CHALLENGE_EXPIRED'],result
    assert result['cryptographic_validity']=='verified' and result['freshness_validity']=='failed'
    # Tool/runtime failure has a distinct non-accepting state.
    class UnavailableVerifier:
        ak_sha256=verifier.ak_sha256
        def verify(self,evidence,challenge): raise OSError('test verifier unavailable')
    server=a.AttestationServer(UnavailableVerifier())
    challenge=server.issue('client');result=server.submit('client',fixture(challenge,folder))
    assert result['decision']=='INDETERMINATE' and result['reasons']==['VERIFIER_ERROR']


def reference_cases(folder,inspector):
    path=folder/'reference.json'
    value={'policy_version':'pcr-reference/1','sha256':{'0':bytes(range(32)).hex(),'7':bytes(range(32,64)).hex()}}
    path.write_text(json.dumps(value))
    verifier=a.QuoteVerifier(folder/'ak.pem',inspector,path)
    server=a.AttestationServer(verifier)
    challenge=server.issue('client');evidence=fixture(challenge,folder)
    result=server.submit('client',evidence)
    assert result['decision']=='ALLOW' and result['pcr_reference_validity']=='matched',result
    assert challenge['policy_id'].startswith('pcr-reference-v1:')
    # A valid signature and fresh nonce with different PCRs must be DENIED.
    challenge=server.issue('client');evidence=fixture(challenge,folder,pcrs=bytes([99])*64)
    result=server.submit('client',evidence)
    assert result['decision']=='DENY' and result['reasons']==['PCR_REFERENCE_MISMATCH'],result
    assert result['cryptographic_validity']=='verified' and result['freshness_validity']=='verified'
    assert result['policy_validity']=='failed' and result['pcr_reference_validity']=='mismatch'
    # Replacing the configured file cannot change an already enrolled policy.
    value['sha256']['0']='ff'*32;path.write_text(json.dumps(value))
    replacement=a.QuoteVerifier(folder/'ak.pem',inspector,path)
    assert replacement.policy_id!=verifier.policy_id
    challenge=server.issue('client');assert server.submit('client',fixture(challenge,folder))['decision']=='ALLOW'
    invalid=[{},dict(value,extra=True),dict(value,sha256={'0':'00'*32}),dict(value,sha256={'0':True,'7':'00'*32}),dict(value,sha256={'0':'g'*64,'7':'00'*32})]
    for bad in invalid:
        path.write_text(json.dumps(bad))
        try:a.PcrReference(path);raise AssertionError('invalid policy accepted')
        except ValueError:pass


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path);parser.add_argument('--inspector',type=Path,default=Path('build-tpm/lab_quote_inspect'));args=parser.parse_args()
    results=dict(scope='offline software-signed TPM-format fixtures; hardware quote NOT tested',cases=[],passed=False)
    try:
        with tempfile.TemporaryDirectory(prefix='lab-attestation-fixtures-') as temp:
            folder=Path(temp)
            command(['openssl','genpkey','-algorithm','RSA','-pkeyopt','rsa_keygen_bits:2048','-out',str(folder/'private.pem')])
            command(['openssl','pkey','-in',str(folder/'private.pem'),'-pubout','-out',str(folder/'ak.pem')])
            verifier=a.QuoteVerifier(folder/'ak.pem',args.inspector)
            now=[1.0];server=a.AttestationServer(verifier,ttl_ms=100,clock=lambda:now[0],wall=lambda:1000)
            c=server.issue('client');e=fixture(c,folder);r=server.submit('client',e)
            assert r['decision']=='ALLOW' and r['cryptographic_validity']=='verified' and r['freshness_validity']=='verified' and r['tpm_identity_validity']=='not_proven',r
            assert server.submit('client',e)['reasons']==['CHALLENGE_REUSED']
            results['cases'].append('valid_signature_pcr_nonce_pinned_key_and_replay')
            for kind,reason in [('nonce','NONCE_MISMATCH'),('signature','SIGNATURE_OR_PCR_DIGEST_INVALID'),('pcrs','SIGNATURE_OR_PCR_DIGEST_INVALID')]:
                c=server.issue('client');e=fixture(c,folder,nonce='00'*32 if kind=='nonce' else None)
                if kind!='nonce':
                    raw=bytearray(base64.b64decode(e[kind]));raw[-1]^=1;e[kind]=base64.b64encode(raw).decode()
                r=server.submit('client',e);assert r['decision']=='DENY' and r['reasons']==[reason],r
            results['cases'].append('wrong_nonce_modified_signature_and_pcr_digest')
            c=server.issue('client');e=fixture(c,folder)
            assert server.submit('other',e)['reasons']==['UNKNOWN_SESSION']
            now[0]+=0.1
            assert server.submit('client',e)['reasons']==['CHALLENGE_EXPIRED']
            results['cases'].append('client_binding_and_local_monotonic_expiry')
            c=server.issue('client');other=server.issue('client');e=fixture(c,folder);e['session_id']=other['session_id']
            assert server.submit('client',e)['reasons']==['NONCE_MISMATCH']
            results['cases'].append('quote_cannot_move_to_another_session')
            # An AK supplied in a request is forbidden, not implicitly enrolled.
            e['ak_public']='untrusted'
            try: server.submit('client',e);raise AssertionError('extra key accepted')
            except ValueError: pass
            for raw in [b'{"x":1,"x":2}',b'{"x":NaN}',b'{"x":1.5}',b'{"x":"\\ud800"}',b'{"x":'+b'['*1000+b'0'+b']'*1000+b'}',b'{}x',b'"string"',b'{"x":"\xff"}']:
                try:a.decode(raw);raise AssertionError('malformed accepted')
                except (ValueError,UnicodeError):pass
            results['cases'].append('closed_schema_duplicate_keys_utf8_trailing_bytes_numbers')
            c=server.issue('client');e=fixture(c,folder)
            q=base64.b64decode(e['quote']);(folder/'trailing').write_bytes(q+b'junk')
            assert subprocess.run([str(args.inspector),str(folder/'trailing')],capture_output=True,timeout=2).returncode==1
            for size in [0,1,5,len(q)-1,4097]:
                (folder/'bad').write_bytes(q[:size] if size<4097 else bytes(size))
                assert subprocess.run([str(args.inspector),str(folder/'bad')],capture_output=True,timeout=2).returncode==1
            results['cases'].append('maintained_C_decoder_bounds_and_trailing_data')
            randomizer=random.Random(92026)
            for _ in range(64):
                mutated=bytearray(q)
                for _ in range(randomizer.randint(1,5)):
                    index=randomizer.randrange(len(mutated));mutated[index]^=randomizer.randint(1,255)
                (folder/'mutation').write_bytes(mutated)
                result=subprocess.run([str(args.inspector),str(folder/'mutation')],capture_output=True,timeout=2)
                assert result.returncode in (0,1), result.stderr.decode(errors='replace')
                assert b'AddressSanitizer' not in result.stderr and b'runtime error:' not in result.stderr
                if result.returncode==0: assert json.loads(result.stdout)['cryptographic_validity']=='not_verified'
            results['cases'].append('bounded_seeded_C_parser_mutations')
            now[0]=2
            c=server.issue('client');e=fixture(c,folder)
            with ThreadPoolExecutor(max_workers=2) as pool:
                decisions=list(pool.map(lambda _:server.submit('client',e),range(2)))
            assert sorted(x['decision'] for x in decisions)==['ALLOW','DENY'],decisions
            assert [x['reasons'] for x in decisions if x['decision']=='DENY']==[['CHALLENGE_REUSED']]
            results['cases'].append('atomic_challenge_consumption_concurrent_submissions')
            asyncio.run(tls_case(folder,verifier))
            results['cases'].append('real_mutual_tls_server_challenge_verify_and_replay')
            asyncio.run(framing_cases())
            results['cases'].append('partial_concatenated_oversized_eof_and_frame_timeout')
            state_cases(verifier,folder)
            results['cases'].append('bounded_sessions_cleanup_invalid_payload_and_expiry_during_verify')
            spec=importlib.util.spec_from_file_location('hardware_checks',Path(__file__).with_name('verificar-tpm-hardware.py'))
            hardware=importlib.util.module_from_spec(spec);spec.loader.exec_module(hardware)
            for fail in [False,True]:
                report={'cleanup':[]}
                try:
                    with hardware.hardware_workspace(report) as owned:
                        (owned/'ak.ctx').write_bytes(b'fixture context, not TPM')
                        if fail: raise RuntimeError('injected failure')
                except RuntimeError as error:
                    assert fail and str(error)=='injected failure'
                assert not owned.exists() and report['cleanup'][0]['temporary_directory_removed']
            results['cases'].append('owned_context_files_removed_on_success_and_exception')
            reference_cases(folder,args.inspector)
            results['cases'].append('operator_pcr_reference_match_mismatch_immutable_and_closed_schema')
            results['passed']=True
    except (OSError,ValueError,AssertionError,subprocess.SubprocessError) as error:results['error']=str(error)
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(results,indent=2)+'\n')
    print(f"PASS: {len(results['cases'])} grupos offline; TPM hardware no ejecutado" if results['passed'] else json.dumps(results,indent=2))
    return 0 if results['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
