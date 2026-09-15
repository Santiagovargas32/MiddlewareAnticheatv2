"""Hardware-only TPM challenge/quote experiment. No persistent handles/NV changes.

Requires existing device access. Never changes device permissions, TPM policies,
boot, SELinux or hierarchy authorization. AK enrollment is operator-pinned lab
trust, not EK certificate validation. All contexts and raw evidence are temporary.
"""
import argparse
import asyncio
import base64
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
from contextlib import contextmanager
import time
import tpm_attestation as a


def run(args,timeout=10):
    result=subprocess.run(args,capture_output=True,timeout=timeout)
    if result.returncode:
        # Do not log tool stdout (keys, contexts, measurements).
        raise RuntimeError(f'{Path(args[0]).name}: exit {result.returncode}; '+result.stderr.decode(errors='replace')[-600:])
    return result


@contextmanager
def hardware_workspace(result):
    """RM owns loaded objects; we own and remove the saved context files.

    tpm2_flushcontext accepts an object HANDLE or a session file, not saved
    object files. Each tool closes its /dev/tpmrm0 connection on exit; the
    kernel resource manager owns that connection's transient objects.
    """
    folder=None
    try:
        with tempfile.TemporaryDirectory(prefix='lab-tpm-hardware-') as directory:
            folder=Path(directory)
            yield folder
    finally:
        if folder is not None:
            removed=not folder.exists()
            result['cleanup'].append(dict(method='kernel_rm_connection_close_and_temporary_directory_removal',
                                          temporary_directory_removed=removed))
            if not removed: raise RuntimeError('CONTEXT_FILES_CLEANUP_UNCONFIRMED')


async def experiment(folder,device,inspector,results):
    spec=importlib.util.spec_from_file_location('bridge_checks',Path(__file__).with_name('verificar-puente.py'))
    helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper);helper.certificates(folder)
    verifier=a.QuoteVerifier(folder/'ak.pem',inspector)
    service=a.AttestationServer(verifier,ttl_ms=10000)
    server=await asyncio.start_server(service.handle,'127.0.0.1',0,ssl=a.tls_context(folder/'server.crt',folder/'server.key',folder/'ca.crt',True),ssl_handshake_timeout=3,ssl_shutdown_timeout=1)
    async def exchange(kind='valid',previous=None):
        reader,writer=await asyncio.open_connection('127.0.0.1',server.sockets[0].getsockname()[1],ssl=a.tls_context(folder/'client.crt',folder/'client.key',folder/'ca.crt'),server_hostname='localhost')
        try:
            writer.write(a.encode({'protocol_version':a.PROTOCOL,'message_type':'session'}));await writer.drain()
            challenge=await a.receive(reader);start=time.perf_counter()
            if previous is None:
                binding='00'*32 if kind=='nonce' else a.qualification(challenge)
                await asyncio.to_thread(run,['tpm2_quote','-T',device,'-c',str(folder/'ak.ctx'),'-l','sha256:0,7','-q',binding,
                                             '-m',str(folder/'quote'),'-s',str(folder/'signature'),'-o',str(folder/'pcrs'),'-F','values','-g','sha256'])
                evidence=dict(protocol_version=a.PROTOCOL,session_id=challenge['session_id'])
                for key in ['quote','signature','pcrs']:
                    data=(folder/key).read_bytes()
                    if kind==key:data=data[:-1]+bytes([data[-1]^1])
                    evidence[key]=base64.b64encode(data).decode()
            else:evidence=previous
            generated=round((time.perf_counter()-start)*1000,3)
            writer.write(a.encode(evidence));await writer.drain();decision=await a.receive(reader)
            results['cases'].append(dict(case=kind,quote_generation_ms=generated,quote_size_bytes=len(base64.b64decode(evidence['quote'])),result=decision))
            return decision,evidence
        finally:writer.close();await writer.wait_closed()
    try:
        decision,evidence=await exchange();assert decision['decision']=='ALLOW',decision
        decision,_=await exchange('replay',evidence);assert decision['reasons']==['CHALLENGE_REUSED'],decision
        for kind,reason in [('signature','SIGNATURE_OR_PCR_DIGEST_INVALID'),('pcrs','SIGNATURE_OR_PCR_DIGEST_INVALID'),('nonce','NONCE_MISMATCH')]:
            decision,_=await exchange(kind);assert decision['reasons']==[reason],decision
        # This reference is deliberately TEST-ONLY. It is never provisioned as
        # approved boot policy or retained outside the temporary experiment.
        observed=base64.b64decode(evidence['pcrs'])
        for matched in (True,False):
            expected=bytearray(observed)
            if not matched: expected[0]^=1
            path=folder/'test-reference.json'
            path.write_text(json.dumps({'policy_version':'pcr-reference/1','sha256':{'0':expected[:32].hex(),'7':expected[32:].hex()}}))
            server.close();await server.wait_closed();await service.close()
            verifier=a.QuoteVerifier(folder/'ak.pem',inspector,path)
            service=a.AttestationServer(verifier)
            server=await asyncio.start_server(service.handle,'127.0.0.1',0,ssl=a.tls_context(folder/'server.crt',folder/'server.key',folder/'ca.crt',True),ssl_handshake_timeout=3,ssl_shutdown_timeout=1)
            if matched:
                decision,_=await exchange('restart_replay',evidence)
                assert decision['reasons']==['UNKNOWN_SESSION'],decision
            decision,_=await exchange('reference_match' if matched else 'reference_mismatch')
            results['cases'][-1]['reference_source']='observed_for_test_only_not_approved_boot'
            assert decision['decision']==('ALLOW' if matched else 'DENY'),decision
            assert decision['cryptographic_validity']=='verified' and decision['freshness_validity']=='verified',decision
            assert decision['pcr_reference_validity']==('matched' if matched else 'mismatch'),decision
            if not matched: assert decision['reasons']==['PCR_REFERENCE_MISMATCH'],decision
    finally:server.close();await server.wait_closed();await service.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--device',choices=['/dev/tpmrm0'],default='/dev/tpmrm0')
    parser.add_argument('--inspector',type=Path,default=Path('build-tpm/lab_quote_inspect'))
    args=parser.parse_args();device='device:'+args.device
    result=dict(scope='hardware TPM via explicitly selected kernel device',status='IN_PROGRESS',cases=[],persistent_tpm_changes=False,
                enrollment='operator_pinned_ak_lab',tpm_manufacturer_identity='not_verified',cleanup=[])
    try:
        run(['tpm2_getcap','-T',device,'properties-fixed'],5)
        with hardware_workspace(result) as folder:
            # Only resource-manager connections; no persistent handles/NV writes.
            run(['tpm2_createek','-T',device,'-G','rsa','-c',str(folder/'ek.ctx')])
            run(['tpm2_createak','-T',device,'-C',str(folder/'ek.ctx'),'-G','rsa','-g','sha256','-s','rsassa',
                 '-c',str(folder/'ak.ctx'),'-u',str(folder/'ak.pem'),'-f','pem'])
            asyncio.run(experiment(folder,device,args.inspector.resolve(),result))
        result['status']='DONE'
    except (OSError,RuntimeError,AssertionError,ValueError,subprocess.SubprocessError,asyncio.TimeoutError,asyncio.IncompleteReadError) as error:
        result.update(status='BLOCKED',error=str(error))
    print(json.dumps(result,indent=2))
    return 0 if result['status']=='DONE' else 2


if __name__=='__main__':raise SystemExit(main())
