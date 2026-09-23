"""Negative MA-012 boundaries with software certificates and bounded real sockets."""
import asyncio
import fcntl
import hashlib
import json
import os
from pathlib import Path
import socket
import ssl
import struct
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import arena_gateway as gateway
import gateway_protocol as protocol
from game_credentials import certificates


def pin(path):
    return hashlib.sha256(ssl.PEM_cert_to_DER_cert(path.read_text())).hexdigest()


class CodecTests(unittest.IsolatedAsyncioTestCase):
    def test_strict_json_and_fields(self):
        for data in [b'',b' '*4097,b'\xff',b'{"a":1,"a":2}',b'{"a":1,"\\u0061":2}',
                     b'{"a":NaN}',b'{"a":Infinity}',b'{"a":1e999}',b'[[[[[[0]]]]]]',b'[[[[[]]]]]']:
            with self.subTest(data=data[:50]),self.assertRaises(ValueError):
                protocol.strict_json(data)
        self.assertEqual(protocol.strict_json(b'{"operation":"HEARTBEAT"}'),{'operation':'HEARTBEAT'})
        for value in (True,False,0,-1,1.0,protocol.MAX_ID+1,'1'):
            with self.subTest(value=value),self.assertRaises(ValueError): protocol.integer(value)
        with self.assertRaises(ValueError): protocol.fields({'operation':'HEARTBEAT','allow':True},('operation',))

    def test_context_replay_and_overflow(self):
        rx = protocol.Sequence()
        good = protocol.envelope('a'*32,1,1,'HEARTBEAT',{})
        protocol.validate_envelope(good,'a'*32,1,rx)
        for bad in [good,dict(good,request_id=3),dict(good,request_id=2,server_run_id='b'*32),
                    dict(good,request_id=2,gateway_generation=2),dict(good,request_id=2,allow=True)]:
            with self.subTest(bad=bad),self.assertRaises(ValueError):
                protocol.validate_envelope(bad,'a'*32,1,rx)
        self.assertEqual(rx.value,1)
        rx.value = protocol.MAX_ID
        with self.assertRaises(ValueError): rx.next()

    async def test_frames_fragmentation_eof_and_absolute_timeout(self):
        for wire in (struct.pack('!I',0),struct.pack('!I',4098),struct.pack('!I',2)+b'\x03x'):
            reader = asyncio.StreamReader()
            reader.feed_data(wire)
            with self.assertRaises(ValueError): await protocol.read_frame(reader,tunnel=True)
        for wire in (b'',b'\x00',struct.pack('!I',4)+b'\x01x'):
            reader = asyncio.StreamReader()
            reader.feed_data(wire)
            reader.feed_eof()
            with self.assertRaises(asyncio.IncompleteReadError): await protocol.read_frame(reader,tunnel=True)
        reader = asyncio.StreamReader()
        reader.feed_data(b'\x00')
        with self.assertRaises(TimeoutError): await protocol.read_frame(reader,tunnel=True)
        reader = asyncio.StreamReader()
        async def fragments():
            for byte in protocol.frame(b'hello',1):
                reader.feed_data(bytes([byte]))
                await asyncio.sleep(.001)
        task=asyncio.create_task(fragments())
        self.assertEqual(await protocol.read_frame(reader,tunnel=True),(1,b'hello'))
        await task

    async def test_queue_age_size_count_and_rate(self):
        clock=[0.0]
        queue=protocol.BoundedQueue(count=2,size=4,clock=lambda:clock[0])
        queue.put(b'ab')
        queue.put(b'cd')
        with self.assertRaises(ValueError): queue.put(b'x')
        self.assertEqual(await queue.get(),b'ab')
        with self.assertRaises(ValueError): queue.put(b'xyz')
        clock[0]=.101
        with self.assertRaises(ValueError): await queue.get()
        rate=protocol.Rate(clock=lambda:clock[0])
        for _ in range(64): rate.take(1)
        with self.assertRaises(ValueError): rate.take(1)
        clock[0]+=.1
        rate.take(1)
        with self.assertRaises(ValueError): rate.take(65537)


class TLSAndProcessTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(prefix='gateway-tests-')
        cls.addClassCleanup(cls.temp.cleanup)
        cls.folder=Path(cls.temp.name)
        cls.keys=cls.folder/'keys'
        cls.keys.mkdir(mode=0o700)
        certificates(cls.keys)
        cls.foreign=cls.folder/'foreign'
        cls.foreign.mkdir(mode=0o700)
        certificates(cls.foreign)
        # A correctly signed but already expired client certificate.
        (cls.keys/'index').write_text('')
        (cls.keys/'serial').write_text('1000\n')
        (cls.keys/'sign.cnf').write_text('[ca]\ndefault_ca=local\n[local]\n'
            f'database={cls.keys}/index\nserial={cls.keys}/serial\nnew_certs_dir={cls.keys}\n'
            f'certificate={cls.keys}/ca.crt\nprivate_key={cls.keys}/ca.key\n'
            'default_md=sha256\npolicy=subject\n[subject]\ncommonName=supplied\n'
            '[extensions]\nbasicConstraints=critical,CA:FALSE\nextendedKeyUsage=clientAuth\n')
        subprocess.run(['openssl','ca','-batch','-notext','-config',str(cls.keys/'sign.cnf'),
            '-in',str(cls.keys/'client.csr'),'-out',str(cls.keys/'expired.crt'),
            '-startdate','20000101000000Z','-enddate','20010101000000Z','-extensions','extensions'],
            check=True,capture_output=True,timeout=10)

    def config(self,role='server',port=0,cert='server'):
        result=dict(role=role,cert=str(self.keys/(cert+'.crt')),key=str(self.keys/(cert+'.key')),
                    ca=str(self.keys/'ca.crt'),host='127.0.0.1',port=port)
        if role=='server': result.update(attestors=[pin(self.keys/'client.crt'),pin(self.keys/'client2.crt')],game_port=9,game_session_id='a'*32)
        else: result.update(gateway_pin=pin(self.keys/'server.crt'),server_name='localhost')
        return result

    async def start_gateway(self,ack=True,game_port=9):
        messages=[]
        ready=asyncio.Future()
        serial=protocol.Sequence()
        def emit(operation,body):
            seq=serial.next()
            messages.append((operation,body))
            if operation=='READY' and not ready.done(): ready.set_result(body['port'])
            if operation=='ROUTE_OPEN' and ack:
                asyncio.get_running_loop().call_soon(server.command,'ROUTE_ACK',
                    dict(channel_id=body['channel_id'],route_request_id=seq))
            return seq
        config=self.config()
        config['game_port']=game_port
        server=gateway.Gateway(config,'b'*32,1,emit)
        task=asyncio.create_task(server.listen())
        async def cleanup():
            task.cancel()
            await asyncio.gather(task,return_exceptions=True)
            await server.close()
            self.assertEqual(server.channels,{})
            self.assertEqual(server.retired,[])
        self.addAsyncCleanup(cleanup)
        return server,await asyncio.wait_for(ready,2),messages

    async def connection(self,port,cert='client',name='localhost',ca=None,alpn=protocol.TUNNEL):
        config=self.config('client',port,cert)
        if ca: config['ca']=str(ca)
        if cert=='expired': config['key']=str(self.keys/'client.key')
        ctx=gateway.context(config)
        ctx.set_alpn_protocols([alpn])
        reader,writer=await asyncio.wait_for(asyncio.open_connection('127.0.0.1',port,
            ssl=ctx,server_hostname=name,ssl_handshake_timeout=1,ssl_shutdown_timeout=.2),2)
        self.addAsyncCleanup(gateway.close_writer,writer)
        return reader,writer

    async def open_channel(self,port,cert='client'):
        reader,writer=await self.connection(port,cert)
        kind,data=await protocol.read_frame(reader,tunnel=True)
        self.assertEqual(kind,2)
        opening=protocol.strict_json(data)
        await gateway.send_control(writer,dict(opening,operation='OPEN_ACK'))
        await asyncio.sleep(.02)
        return reader,writer,opening

    async def test_roles_missing_certificate_ca_expiry_san_alpn(self):
        server,port,messages=await self.start_gateway()
        for cert,alpn in [('unknown',protocol.TUNNEL),('client','wrong'),('expired',protocol.TUNNEL)]:
            with self.subTest(cert=cert,alpn=alpn):
                try:
                    reader,_writer=await self.connection(port,cert,alpn=alpn)
                    with self.assertRaises((OSError,asyncio.IncompleteReadError)):
                        await protocol.read_frame(reader,tunnel=True)
                except (OSError,asyncio.IncompleteReadError): pass
        for name,ca in [('wrong.invalid',None),('localhost',self.foreign/'ca.crt')]:
            with self.subTest(name=name,ca=ca),self.assertRaises(ssl.SSLCertVerificationError):
                await self.connection(port,name=name,ca=ca)
        ctx=ssl.create_default_context(cafile=str(self.keys/'ca.crt'))
        ctx.minimum_version=ssl.TLSVersion.TLSv1_3
        ctx.set_alpn_protocols([protocol.TUNNEL])
        try:
            reader,writer=await asyncio.open_connection('127.0.0.1',port,ssl=ctx,server_hostname='localhost')
            self.addAsyncCleanup(gateway.close_writer,writer)
            with self.assertRaises((OSError,asyncio.IncompleteReadError)):
                await protocol.read_frame(reader,tunnel=True)
        except OSError: pass
        self.assertFalse(any(op=='ROUTE_OPEN' for op,_ in messages))
        self.assertEqual(server.channels,{})

    async def test_gateway_pin_and_open_context(self):
        _server,port,_messages=await self.start_gateway()
        config=self.config('client',port,'client')
        config['gateway_pin']='0'*64
        client=gateway.Gateway(config,'c'*32,1,lambda *_:1)
        with self.assertRaisesRegex(ValueError,'tls_role'): await client.connect()
        await client.close()
        config['gateway_pin']=pin(self.keys/'server.crt')
        # The server assigns the lobby session through authenticated OPEN;
        # the client must not need that random value before establishing TLS.
        observed=asyncio.Future()
        def emit(operation,body):
            if operation=='ROUTE_OPEN': observed.set_result(body)
            return 1
        client=gateway.Gateway(config,'c'*32,1,emit)
        task=asyncio.create_task(client.connect())
        try:
            route=await asyncio.wait_for(observed,1)
            self.assertEqual(route['game_session_id'],'a'*32)
            self.assertEqual(route['remote_run_id'],'b'*32)
        finally:
            task.cancel()
            await asyncio.gather(task,return_exceptions=True)
            await client.close()

    async def test_ack_gate_retirement_identity_and_reconnect(self):
        server,port,messages=await self.start_gateway(ack=False)
        reader,writer,opening=await self.open_channel(port)
        route=next(body for op,body in messages if op=='ROUTE_OPEN')
        self.assertEqual(route['attestor'],pin(self.keys/'client.crt'))
        channel=server.channels[opening['channel_id']]
        with self.assertRaises(ValueError):
            channel.acknowledge(dict(channel_id=channel.id,route_request_id=channel.route_request+1))
        self.assertFalse(channel.ack.is_set())
        # Nothing is forwarded until the inherited-pipe parent acknowledges.
        udp=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
        udp.bind(('127.0.0.1',0))
        udp.setblocking(False)
        self.addCleanup(udp.close)
        channel.udp.connect(udp.getsockname())
        writer.write(protocol.frame(b'probe',1))
        await writer.drain()
        with self.assertRaises(TimeoutError):
            await asyncio.wait_for(asyncio.get_running_loop().sock_recv(udp,100),.05)
        channel.acknowledge(dict(channel_id=channel.id,route_request_id=channel.route_request))
        self.assertEqual(await asyncio.wait_for(asyncio.get_running_loop().sock_recv(udp,100),.3),b'probe')
        with self.assertRaises(ValueError):
            channel.acknowledge(dict(channel_id=channel.id,route_request_id=channel.route_request))
        writer.close()
        await writer.wait_closed()
        await asyncio.sleep(.05)
        self.assertNotIn(channel.id,server.channels)
        probe=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
        self.addCleanup(probe.close)
        with self.assertRaises(OSError): probe.bind(('127.0.0.1',route['port']))
        _r,_w,next_open=await self.open_channel(port,'client2')
        self.assertNotEqual(next_open['channel_id'],opening['channel_id'])
        next_route=[body for op,body in messages if op=='ROUTE_OPEN'][-1]
        self.assertNotEqual(next_route['port'],route['port'])
        self.assertEqual(next_route['attestor'],pin(self.keys/'client2.crt'))
        with self.assertRaises(ValueError): server.command('ROUTE_ACK',dict(channel_id=channel.id,route_request_id=channel.route_request))
        server.command('ROUTE_CLOSE',dict(channel_id=channel.id))  # Idempotent terminal close.

    async def test_replay_extra_fields_and_malformed_frame_close(self):
        server,port,_messages=await self.start_gateway()
        for payload in [protocol.frame(b'{"operation":"HEARTBEAT","allow":true}',2),
                        protocol.frame(b'{"operation":"HEARTBEAT","operation":"HEARTBEAT"}',2),
                        struct.pack('!I',4098),struct.pack('!I',2)+b'\x03x']:
            reader,writer,opening=await self.open_channel(port)
            writer.write(payload)
            await writer.drain()
            await asyncio.sleep(.05)
            self.assertNotIn(opening['channel_id'],server.channels)
        reader,writer,opening=await self.open_channel(port)
        await gateway.send_control(writer,dict(opening,operation='OPEN_ACK'))
        await asyncio.sleep(.05)
        self.assertNotIn(opening['channel_id'],server.channels)
        # A valid OPEN_ACK from a previous TLS connection is not a bearer token.
        reader,writer=await self.connection(port)
        _kind,data=await protocol.read_frame(reader,tunnel=True)
        fresh=protocol.strict_json(data)
        await gateway.send_control(writer,dict(opening,operation='OPEN_ACK'))
        await asyncio.sleep(.05)
        self.assertNotIn(fresh['channel_id'],server.channels)

    async def test_pre_tls_quota_and_reserved_route_capacity(self):
        server,port,_messages=await self.start_gateway()
        raw=[]
        for _ in range(5):
            reader,writer=await asyncio.open_connection('127.0.0.1',port)
            raw.append((reader,writer))
            self.addAsyncCleanup(gateway.close_writer,writer)
            await asyncio.sleep(.01)
        self.assertEqual(server.pending,4)
        self.assertEqual(await asyncio.wait_for(raw[-1][0].read(1),.3),b'')
        for _reader,writer in raw: writer.close()
        await asyncio.sleep(.05)
        self.assertEqual(server.pending,0)
        # Same capacity guard used with actual retired sockets; table stress is
        # covered in Godot too. Do not require hundreds of TLS handshakes here.
        server.retired=[socket.socket(socket.AF_INET,socket.SOCK_DGRAM) for _ in range(256)]
        reader,writer=await asyncio.open_connection('127.0.0.1',port)
        self.addAsyncCleanup(gateway.close_writer,writer)
        self.assertEqual(await asyncio.wait_for(reader.read(1),.3),b'')

    async def test_eight_active_channels_and_idle_deadline(self):
        server,port,_messages=await self.start_gateway()
        channels=[await self.open_channel(port) for _ in range(8)]
        self.assertEqual(len(server.channels),8)
        with self.assertRaises((OSError,asyncio.IncompleteReadError)):
            await self.open_channel(port)
        # No heartbeat from these clients: all routes must retire after 1 s.
        await asyncio.sleep(1.1)
        self.assertEqual(server.channels,{})
        self.assertEqual(len(server.retired),8)
        self.assertEqual(len({sock.getsockname() for sock in server.retired}),8)

    async def test_foreign_udp_queued_before_client_port_ack_is_not_forwarded(self):
        target=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
        target.bind(('127.0.0.1',0))
        target.setblocking(False)
        legitimate=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
        legitimate.bind(('127.0.0.1',0))
        rogue=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
        for sock in (target,legitimate,rogue): self.addCleanup(sock.close)
        _server,port,_messages=await self.start_gateway(game_port=target.getsockname()[1])
        injection=[]
        def emit(operation,body):
            if operation=='ROUTE_OPEN':
                async def inject():
                    address=('127.0.0.1',body['port'])
                    rogue.sendto(b'foreign-before-ack',address)
                    await asyncio.sleep(.02)
                    client.command('ROUTE_ACK',dict(channel_id=body['channel_id'],route_request_id=1,
                                                   client_port=legitimate.getsockname()[1]))
                    legitimate.sendto(b'legitimate',address)
                injection.append(asyncio.create_task(inject()))
            return 1
        client=gateway.Gateway(self.config('client',port,'client'),'c'*32,1,emit)
        task=asyncio.create_task(client.connect())
        try:
            result=await asyncio.wait_for(asyncio.get_running_loop().sock_recv(target,100),1)
            self.assertEqual(result,b'legitimate')
            with self.assertRaises(TimeoutError):
                await asyncio.wait_for(asyncio.get_running_loop().sock_recv(target,100),.05)
        finally:
            task.cancel()
            await asyncio.gather(task,*injection,return_exceptions=True)
            await client.close()

    async def test_partial_tls_frame_retention_and_deadline(self):
        target=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
        target.bind(('127.0.0.1',0))
        target.setblocking(False)
        self.addCleanup(target.close)
        server,port,_messages=await self.start_gateway(game_port=target.getsockname()[1])
        _reader,writer,_opening=await self.open_channel(port)
        wire=protocol.frame(b'retained',1)
        began=asyncio.get_running_loop().time()
        writer.write(wire[:2])
        await writer.drain()
        await asyncio.sleep(.06)
        writer.write(wire[2:])
        await writer.drain()
        self.assertEqual(await asyncio.wait_for(asyncio.get_running_loop().sock_recv(target,100),.3),b'retained')
        elapsed=asyncio.get_running_loop().time()-began
        self.assertGreaterEqual(elapsed,.06)
        self.assertLess(elapsed,.3)
        _reader,writer,opening=await self.open_channel(port)
        writer.write(b'\x00')
        await writer.drain()
        await asyncio.sleep(.25)
        self.assertNotIn(opening['channel_id'],server.channels)
        print(json.dumps({'case':'partial_tls_retention','observed_ms':round(elapsed*1000,2),
                          'partial_frame_250ms_closed':True}))

    async def process(self):
        process=await asyncio.create_subprocess_exec(sys.executable,str(ROOT/'scripts/arena_gateway.py'),
            stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
        async def cleanup():
            if process.returncode is None:
                process.terminate()
                try: await asyncio.wait_for(process.wait(),2)
                except TimeoutError:
                    process.kill()
                    await asyncio.wait_for(process.wait(),1)
        self.addAsyncCleanup(cleanup)
        tx=protocol.Sequence()
        async def send(operation,body):
            process.stdin.write(protocol.frame(protocol.json_bytes(protocol.envelope('a'*32,1,tx.next(),operation,body))))
            await process.stdin.drain()
        await send('CONFIG',self.config())
        while True:
            message=protocol.strict_json(await protocol.read_frame(process.stdout,idle=3))
            if message['operation']=='READY': break
        return process,send,message['body']['port']

    async def test_parent_eof_and_idle_close_own_listener(self):
        for eof in (True,False):
            process,_send,port=await self.process()
            if eof: process.stdin.close()
            await asyncio.wait_for(process.wait(),2)
            probe=socket.socket()
            self.addCleanup(probe.close)
            probe.bind(('127.0.0.1',port))

    async def test_broken_output_and_ipc_replay_close(self):
        process,_send,_port=await self.process()
        process.stdout._transport.close()  # Own pipe; exercise EPIPE in the child.
        await asyncio.wait_for(process.wait(),2)
        process,_send,_port=await self.process()
        replay=protocol.envelope('a'*32,1,1,'HEARTBEAT',{})
        process.stdin.write(protocol.frame(protocol.json_bytes(replay)))
        await process.stdin.drain()
        self.assertEqual(await asyncio.wait_for(process.wait(),2),1)

    async def test_stdout_backpressure_has_deadline_while_parent_is_alive(self):
        process,send,_port=await self.process()
        # Keep stdin alive, stop consuming stdout and reduce only our own pipe.
        fd=process.stdout._transport.get_extra_info('pipe').fileno()
        fcntl.fcntl(fd,fcntl.F_SETPIPE_SZ,4096)
        process.stdout._transport.pause_reading()
        async def heartbeat():
            while process.returncode is None:
                try: await send('HEARTBEAT',{})
                except (OSError,ConnectionError): return
                await asyncio.sleep(.05)
        task=asyncio.create_task(heartbeat())
        try:
            # A subprocess wait can await its paused pipe even after exit.
            deadline=asyncio.get_running_loop().time()+8
            while process.returncode is None and asyncio.get_running_loop().time()<deadline:
                await asyncio.sleep(.05)
            self.assertIsNotNone(process.returncode,'stdout backpressure did not terminate auxiliary')
        finally:
            process.stdout._transport.resume_reading()
            task.cancel()
            await asyncio.gather(task,return_exceptions=True)
        await asyncio.wait_for(process.communicate(),2)
        self.assertEqual(process.returncode,1)


if __name__=='__main__':
    unittest.main()
