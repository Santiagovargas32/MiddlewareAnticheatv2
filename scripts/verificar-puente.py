"""Real local C workers over mutual TLS; this does not emulate Windows."""
import argparse
import asyncio
import json
from pathlib import Path
import platform
import ssl
import struct
import subprocess
import tempfile
from bridge_transport import WorkerService, encode_frame, read_frame, tls_context, worker, execute
import lab


def certificates(directory):
    def run(*args):
        subprocess.run(['openssl',*map(str,args)],cwd=directory,check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,timeout=10)
    run('req','-x509','-newkey','rsa:2048','-nodes','-keyout','ca.key','-out','ca.crt','-subj','/CN=Lab temporary CA','-days','1','-addext','basicConstraints=critical,CA:TRUE','-addext','keyUsage=critical,keyCertSign,cRLSign')
    for name,usage in [('server','serverAuth'),('client','clientAuth')]:
        run('req','-new','-newkey','rsa:2048','-nodes','-keyout',name+'.key','-out',name+'.csr','-subj','/CN='+name)
        (directory/(name+'.ext')).write_text(f'basicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature,keyEncipherment\nextendedKeyUsage={usage}\nsubjectAltName=DNS:localhost\n')
        run('x509','-req','-in',name+'.csr','-CA','ca.crt','-CAkey','ca.key','-CAcreateserial','-out',name+'.crt','-days','1','-extfile',name+'.ext')


async def checks(build,directory,results):
    # Read partial/concatenated frames, reject EOF, oversize and absolute timeout.
    reader=asyncio.StreamReader()
    async def feed():
        for byte in encode_frame(b'abc')+encode_frame(b'def'):
            reader.feed_data(bytes([byte]));await asyncio.sleep(0)
    feeding=asyncio.create_task(feed())
    assert await read_frame(reader)==b'abc' and await read_frame(reader)==b'def'
    await feeding
    for data,expected in [(b'\x00\x00',asyncio.IncompleteReadError),(struct.pack('!I',257),ValueError)]:
        reader=asyncio.StreamReader();reader.feed_data(data);reader.feed_eof()
        try: await read_frame(reader);raise AssertionError('frame accepted')
        except expected: pass
    reader=asyncio.StreamReader();reader.feed_data(b'\x00')
    try: await read_frame(reader,0.03);raise AssertionError('frame timeout not enforced')
    except asyncio.TimeoutError: pass
    results['cases'].append('partial_concatenated_eof_oversize_frame_deadline')
    context=tls_context(directory/'server.crt',directory/'server.key',directory/'ca.crt',True)
    service=WorkerService(build/'lab_app')
    server=await asyncio.start_server(service.handle,'127.0.0.1',0,ssl=context,ssl_handshake_timeout=1,ssl_shutdown_timeout=1)
    remote=argparse.Namespace(remote_host='127.0.0.1',remote_port=server.sockets[0].getsockname()[1],server_name='localhost',
                              remote_origin='linux',cert=directory/'client.crt',key=directory/'client.key',ca=directory/'ca.crt')
    try:
        for bad_name in ['wrong.invalid']:
            try:
                await asyncio.wait_for(asyncio.open_connection('127.0.0.1',remote.remote_port,ssl=tls_context(remote.cert,remote.key,remote.ca),server_hostname=bad_name),2)
                raise AssertionError('invalid identity accepted')
            except ssl.SSLCertVerificationError: pass
        for ca in [directory/'ca.crt',None]:
            # First: trusted server but no client certificate. Second: no trust in server CA.
            client=ssl.create_default_context(cafile=str(ca) if ca else None)
            writer=None
            try:
                reader,writer=await asyncio.wait_for(asyncio.open_connection('127.0.0.1',remote.remote_port,ssl=client,server_hostname='localhost'),2)
                assert await asyncio.wait_for(reader.read(1),2)==b'', 'unauthenticated client admitted'
            except (ssl.SSLError,ConnectionError): pass
            finally:
                if writer:
                    writer.close()
                    try: await asyncio.wait_for(writer.wait_closed(),1)
                    except (ssl.SSLError,ConnectionError): pass
        results['cases'].append('mutual_tls_identity_and_untrusted_client_rejected')
        port=lab.free_port()
        async with lab.daemon([build/'lab_server','--port',port,'--request-ms','10000','--timeout-ms','15000','-v']):
            for op,cap in lab.CAPS.items():
                direct=await lab.run_job(build/'lab_app',('127.0.0.1',port),cap,37)
                tls=await lab.run_job(build/'lab_app',('127.0.0.1',port),cap,37,remote)
                assert len(tls['observations'])==2 and all(o['origin_os']=='linux' for o in tls['observations'])
                assert tls['observations'][0]['subject_id']!=tls['observations'][1]['subject_id']
                assert tls['observations'][0]['origin_instance']!=tls['observations'][1]['origin_instance']
                results['measurements'].append(dict(op=op,direct=direct,local_tls=tls))
            results['cases'].append('three_real_capabilities_tls_preservation_and_separate_native_evidence')
            # The Linux executable must reject a request to report Windows origin.
            remote.remote_origin='windows'
            try:
                await lab.run_job(build/'lab_app',('127.0.0.1',port),1,37,remote)
                raise AssertionError('Linux impersonated Windows')
            except asyncio.IncompleteReadError: pass
            results['cases'].append('compiled_origin_cannot_be_overridden')
        async with worker(build/'lab_app') as (process,hello):
            command=lab.packet(0x40,struct.pack('<16sI16sBBBBI',b's'*16,1,hello[60:76],1,1,1,0,37),1)
            try: await execute(process,command+b'x');raise AssertionError('job trailing bytes')
            except ValueError: pass
        results['cases'].append('worker_invalid_job_length')
    finally:
        server.close();await server.wait_closed();await service.close()
    assert not service.tasks
    results['cases'].append('worker_cleanup')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build',type=Path,default=lab.ROOT/'build')
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    results=dict(environment=platform.platform(),tls=ssl.OPENSSL_VERSION,runtime='Linux -> TLS -> Linux (no Windows runtime)',cases=[],measurements=[],passed=False)
    try:
        with tempfile.TemporaryDirectory(prefix='lab-tls-') as directory:
            certificates(Path(directory))
            asyncio.run(checks(args.build.resolve(),Path(directory),results))
        results['passed']=True
    except (OSError,ValueError,AssertionError,asyncio.TimeoutError,asyncio.IncompleteReadError,subprocess.SubprocessError) as error:
        results['error']=str(error)
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(results,indent=2)+'\n')
    print(f"OK: {len(results['cases'])} grupos del puente TLS Linux" if results['passed'] else json.dumps(results,indent=2))
    return 0 if results['passed'] else 1


if __name__=='__main__': raise SystemExit(main())
