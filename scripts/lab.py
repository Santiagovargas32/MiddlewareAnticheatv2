"""Local CLI and authenticated worker endpoint for owned resources."""
import argparse
import asyncio
from contextlib import asynccontextmanager
import hashlib
import json
import os
from pathlib import Path
import signal
import socket
import struct
import time
from bridge_transport import WorkerService, encode_frame, execute, read_frame, tls_context, worker

ROOT=Path(__file__).resolve().parents[1]
CAPS={'file':1,'proc':2,'sync':3}


def packet(kind,payload,sequence=0):
    return struct.pack('<BBBBII4s',0x4c,2,kind,0,sequence,len(payload),b'\xaa'*4)+payload


def parse(data,kind,length):
    if len(data)!=16+length or data[:4]!=bytes((0x4c,2,kind,0)) or data[12:16]!=b'\xaa'*4 or struct.unpack_from('<I',data,8)[0]!=length:
        raise ValueError('invalid_response')
    return data[16:]


class Session:
    def __init__(self,peer,hello):
        self.peer=peer;self.hello=hello;self.session=None
        self.socket=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);self.socket.setblocking(False)
        self.socket.connect(peer)

    async def exchange(self,data):
        loop=asyncio.get_running_loop()
        sent=await asyncio.wait_for(loop.sock_sendto(self.socket,data,self.peer),2)
        if sent!=len(data): raise ValueError("partial_datagram")
        return await asyncio.wait_for(loop.sock_recv(self.socket,4096),2)

    async def open(self):
        payload=parse(await self.exchange(self.hello),2,56)
        result,reason=struct.unpack_from('<II',payload)
        if result!=1 or reason or payload[40:]!=self.hello[60:76]: raise ValueError('hello_rejected')
        self.session=payload[8:24]

    async def request(self,capability,origin,seed):
        request=packet(0x40,struct.pack('<16sI16sBBBBI',self.session,1,self.hello[60:76],origin,capability,1,0,seed),1)
        self.check_decision(await self.exchange(request),1,1)
        return request

    def check_decision(self,response,status,sequence):
        result=parse(response,0x42,28)
        session,request_id,actual,reason=struct.unpack('<16sIII',result)
        if session!=self.session or request_id!=1 or actual!=status or reason or struct.unpack_from('<I',response,4)[0]!=sequence:
            raise ValueError(f'policy_rejected:{reason}')

    async def submit(self,data):
        self.check_decision(await self.exchange(data),2,2)

    async def close(self):
        try:
            if self.session:
                result=parse(await self.exchange(packet(0x30,struct.pack('<16sII',self.session,0,0),3)),0x20,60)
                if result[:16]!=self.session or struct.unpack_from('<II',result,16)!=(0,3) or result[24:27]!=b'bye':
                    raise ValueError('close_rejected')
        finally: self.socket.close()


def decode_observation(data):
    p=parse(data,0x41,104)
    sid,request_id,instance,subject,origin,cap,evidence,ok,seed,elapsed,error,payload=struct.unpack('<16sI16s16sBBBBIII36s',p)
    if origin not in (1,2) or cap not in (1,2,3) or evidence!=1: raise ValueError('invalid_observation')
    output=dict(protocol='lab-udp/2',session_id=sid.hex(),request_id=request_id,
                sequence=struct.unpack_from('<I',data,4)[0],message_type='OBSERVATION',
                origin_os={1:'linux',2:'windows'}[origin],origin_instance=instance.hex(),subject_id=subject.hex(),
                evidence_class='self_reported_lab',capability={1:'file',2:'proc',3:'sync'}[cap],
                payload=dict(ok=bool(ok),seed=seed,elapsed_ms=elapsed,error=error))
    if cap==1:
        output['payload'].update(size=struct.unpack_from('<I',payload)[0],sha256=payload[4:].hex())
        if payload[4:]!=hashlib.sha256(bytes((i*7+seed)&255 for i in range(4096))).digest(): raise ValueError('digest_mismatch')
    if cap==2:
        pid,generation=struct.unpack_from('<QQ',payload)
        output['payload'].update(process_id=pid,generation=generation)
    return output


@asynccontextmanager
async def daemon(command):
    process=await asyncio.create_subprocess_exec(*map(str,command),stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
    draining=None
    try:
        line=await asyncio.wait_for(process.stdout.readline(),3)
        if json.loads(line).get('ev')!='boot': raise ValueError('readiness')
        async def drain_logs():
            while await process.stdout.readline(): pass
        draining=asyncio.create_task(drain_logs())
        yield process
    finally:
        if process.returncode is None:
            try: process.terminate()
            except ProcessLookupError: pass
        try: await asyncio.wait_for(process.wait(),2)
        except asyncio.TimeoutError:
            process.kill();await asyncio.wait_for(process.wait(),2)
        if draining: await asyncio.wait_for(draining,2)
        if process.returncode!=0: raise ValueError('daemon_failed')


def free_port():
    with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as s:
        s.bind(('127.0.0.1',0));return s.getsockname()[1]


def resources(pid):
    status=Path(f'/proc/{pid}/status')
    if not status.exists(): return None
    rss=next((line.split()[1] for line in status.read_text().splitlines() if line.startswith('VmRSS:')),None)
    fields=Path(f'/proc/{pid}/stat').read_text().rsplit(')',1)[1].split()
    cpu=(int(fields[11])+int(fields[12]))/os.sysconf('SC_CLK_TCK')
    return dict(rss_kib=int(rss) if rss else None,open_fds=len(list(Path(f'/proc/{pid}/fd').iterdir())),cpu_seconds=cpu)


async def run_job(binary,peer,capability,seed,remote=None):
    import resource
    cpu_before=resource.getrusage(resource.RUSAGE_CHILDREN)
    start=time.perf_counter(); sessions=[]; writer=None
    try:
        async with worker(binary) as (process,hello):
            local=Session(peer,hello);sessions.append(local);await local.open()
            request=await local.request(capability,1,seed)
            source=(await execute(process,request))[0]
        records=[source]
        if remote:
            reader,writer=await asyncio.wait_for(asyncio.open_connection(remote.remote_host,remote.remote_port,
                ssl=tls_context(remote.cert,remote.key,remote.ca),server_hostname=remote.server_name,ssl_handshake_timeout=3),4)
            remote_hello=await read_frame(reader)
            native=Session(peer,remote_hello);sessions.append(native);await native.open()
            command=await native.request(capability,{'linux':1,'windows':2}[remote.remote_origin],seed)
            writer.write(encode_frame(command+source));await writer.drain()
            preserved=await read_frame(reader);observed=await read_frame(reader)
            if preserved!=source: raise ValueError('origin_evidence_changed')
            records=[preserved,observed]
        observations=[decode_observation(record) for record in records]
        for session,record in zip(sessions,records): await session.submit(record)
        cpu_after=resource.getrusage(resource.RUSAGE_CHILDREN)
        cpu_ms=(cpu_after.ru_utime+cpu_after.ru_stime-cpu_before.ru_utime-cpu_before.ru_stime)*1000
        return dict(accepted=True,elapsed_ms=round((time.perf_counter()-start)*1000,3),local_child_cpu_ms=round(cpu_ms,3),observations=observations)
    finally:
        if writer:
            writer.close()
            try: await asyncio.wait_for(writer.wait_closed(),1)
            except (OSError,asyncio.TimeoutError): pass
        errors=[]
        for session in sessions:
            try: await session.close()
            except (OSError,ValueError,asyncio.TimeoutError) as error: errors.append(error)
        if errors: raise errors[0]


async def demo(args):
    server_port,adapter_port=free_port(),free_port()
    server_command=[args.build/'lab_server','--port',str(server_port),'--timeout-ms','15000','--request-ms','10000','-v']
    runs=[]
    async with daemon(server_command) as server:
        async with daemon([args.build/'lab_adapter','--listen',f'127.0.0.1:{adapter_port}','--upstream',f'127.0.0.1:{server_port}']) as adapter:
            for route,port in [('direct',server_port),('via-adapter',adapter_port)]:
                for op in CAPS:
                    for _ in range(args.iterations):
                        result=await run_job(args.build/'lab_app',('127.0.0.1',port),CAPS[op],37,args if args.remote_host else None)
                        result.update(route=route,op=op,resources=dict(server=resources(server.pid),adapter=resources(adapter.pid)))
                        runs.append(result)
    output=dict(environment=dict(platform=os.uname().sysname,release=os.uname().release),
                method='wall-clock per job including process startup, UDP session, capability and decision; local reaped-child CPU delta; daemon RSS/FD and cumulative CPU snapshot',
                remote_origin=args.remote_origin if args.remote_host else None,runs=runs)
    print(json.dumps(output,indent=2))


async def serve(args):
    service=WorkerService(args.binary)
    context=tls_context(args.cert,args.key,args.ca,server=True)
    stop=asyncio.Event();loop=asyncio.get_running_loop()
    for signo in (signal.SIGINT,signal.SIGTERM):
        try: loop.add_signal_handler(signo,stop.set)
        except NotImplementedError: pass
    server=await asyncio.start_server(service.handle,args.listen,args.port,ssl=context,ssl_handshake_timeout=3,ssl_shutdown_timeout=1)
    print(json.dumps(dict(ev='boot',port=server.sockets[0].getsockname()[1],transport='TLSv1.3',evidence_class='self_reported_lab')),flush=True)
    try:
        async with server: await stop.wait()
    finally: await service.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    subs=parser.add_subparsers(dest='command',required=True)
    demo_parser=subs.add_parser('demo')
    demo_parser.add_argument('--build',type=Path,default=ROOT/'build')
    demo_parser.add_argument('--iterations',type=int,choices=range(1,11),default=1)
    demo_parser.add_argument('--remote-host')
    demo_parser.add_argument('--remote-port',type=int,default=9443)
    demo_parser.add_argument('--remote-origin',choices=['windows','linux'],default='windows')
    demo_parser.add_argument('--server-name',default='localhost')
    service=subs.add_parser('serve')
    service.add_argument('--binary',type=Path,required=True)
    service.add_argument('--listen',default='127.0.0.1')
    service.add_argument('--port',type=int,default=9443)
    for sub in (service,demo_parser):
        for option in ['cert','key','ca']: sub.add_argument('--'+option,type=Path,required=sub is service)
    for command in ['start','status','stop']:
        sub=subs.add_parser(command)
        default_runtime=Path(f'/run/user/{os.getuid()}') / ('middleware-anticheat-'+hashlib.sha256(str(ROOT).encode()).hexdigest()[:10]) if hasattr(os,'getuid') else ROOT/'results/runtime'
        sub.add_argument('--runtime',type=Path,default=default_runtime)
        if command=='start':
            sub.add_argument('--build',type=Path,default=ROOT/'build')
            sub.add_argument('--port',type=int,default=7777)
            sub.add_argument('--adapter-port',type=int,default=7778)
    args=parser.parse_args()
    if args.command=='demo' and args.remote_host and not all((args.cert,args.key,args.ca)): parser.error('remote requires --cert --key --ca')
    try:
        if args.command in ('start','status','stop'):
            from lab_processes import manage
            manage(args)
        else:
            asyncio.run(serve(args) if args.command=='serve' else demo(args))
    except (OSError,ValueError,asyncio.TimeoutError,asyncio.IncompleteReadError) as error:
        print(json.dumps(dict(ok=False,error=str(error))))
        return 1
    return 0


if __name__=='__main__':
    raise SystemExit(main())
