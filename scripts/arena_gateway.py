"""Internal MA-012 ENet/mTLS auxiliary. No admission service calls or gameplay permission.

Started by Godot through inherited stdin/stdout pipes. Configuration and paths
arrive over IPC; stdout contains framed messages only. No public game launcher
uses this module until the later enforcement/lifecycle gates are implemented.
"""
import asyncio
import hashlib
import os
from pathlib import Path
import secrets
import socket
import ssl
import sys
import time

from bridge_transport import tls_context
from gateway_protocol import (BoundedQueue, PROFILE, Rate, Sequence,
                              TUNNEL, envelope, fields, frame, hex_id, integer,
                              json_bytes, read_frame, strict_json, validate_envelope)


def configuration(body):
    common = {'role', 'cert', 'key', 'ca', 'host', 'port'}
    role = body.get('role')
    fields(body, common | ({'attestors', 'game_port', 'game_session_id'} if role == 'server'
                          else {'gateway_pin', 'server_name'}))
    if role not in ('server', 'client'):
        raise ValueError('role')
    for key in ('cert', 'key', 'ca'):
        if type(body[key]) is not str or not os.path.isabs(body[key]) or len(body[key]) > 1024:
            raise ValueError('credential_path')
    socket.inet_pton(socket.AF_INET, body['host'])
    integer(body['port'], 0 if role == 'server' else 1, 65535)
    if role == 'server':
        hex_id(body['game_session_id'])
        integer(body['game_port'], 1, 65535)
        if type(body['attestors']) is not list or not 1 <= len(body['attestors']) <= 8:
            raise ValueError('attestors')
        for fingerprint in body['attestors']:
            hex_id(fingerprint, 64)
        if len(set(body['attestors'])) != len(body['attestors']):
            raise ValueError('duplicate_role')
        own = hashlib.sha256(ssl.PEM_cert_to_DER_cert(Path(body['cert']).read_text(encoding='ascii'))).hexdigest()
        if own in body['attestors']:
            raise ValueError('overlapping_role')
    else:
        hex_id(body['gateway_pin'], 64)
        if type(body['server_name']) is not str or not 1 <= len(body['server_name']) <= 253:
            raise ValueError('server_name')
    return body


def context(config):
    server = config['role'] == 'server'
    ctx = tls_context(config['cert'], config['key'], config['ca'], server=server)
    ctx.maximum_version = ssl.TLSVersion.TLSv1_3
    ctx.set_alpn_protocols([TUNNEL])
    if server:
        ctx.num_tickets = 0
    return ctx


def identity(writer, allowed):
    tls = writer.get_extra_info('ssl_object')
    if tls is None or tls.version() != 'TLSv1.3' or tls.selected_alpn_protocol() != TUNNEL or tls.session_reused:
        raise ValueError('tls_protocol')
    fingerprint = hashlib.sha256(tls.getpeercert(binary_form=True)).hexdigest()
    if fingerprint not in allowed:
        raise ValueError('tls_role')
    return fingerprint


async def close_writer(writer):
    writer.close()
    try:
        await asyncio.wait_for(writer.wait_closed(), .3)
    except (OSError, TimeoutError):
        writer.transport.abort()


async def send_control(writer, message):
    writer.write(frame(json_bytes(message), 2))
    await asyncio.wait_for(writer.drain(), .2)


class Channel:
    def __init__(self, gateway, channel_id, reader, writer, fingerprint, session):
        self.gateway = gateway
        self.id = hex_id(channel_id)
        self.reader, self.writer = reader, writer
        self.fingerprint = fingerprint
        self.session = hex_id(session)
        self.udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.udp.setblocking(False)
        self.udp.bind(('127.0.0.1', 0))
        self.origin = None
        if gateway.config['role'] == 'server':
            self.origin = ('127.0.0.1', gateway.config['game_port'])
            self.udp.connect(self.origin)
        self.ack = asyncio.Event()
        self.closed = asyncio.Event()
        self.route_request = 0
        self.outgoing = BoundedQueue()
        self.incoming = BoundedQueue()
        self.tx_rate, self.rx_rate = Rate(), Rate()

    def acknowledge(self, body):
        server = self.gateway.config['role'] == 'server'
        fields(body, {'channel_id', 'route_request_id'} | (set() if server else {'client_port'}))
        if body['channel_id'] != self.id or integer(body['route_request_id']) != self.route_request or self.ack.is_set() or self.closed.is_set():
            raise ValueError('route_ack')
        if not server:
            self.origin = ('127.0.0.1', integer(body['client_port'], 1, 65535))
            self.udp.connect(self.origin)
        self.ack.set()

    async def forward(self):
        loop = asyncio.get_running_loop()

        async def udp_reader():
            while True:
                data, origin = await loop.sock_recvfrom(self.udp, 4097)
                self.tx_rate.take(len(data))
                # UDP queued before the client-port ACK retains its original
                # sender even after connect(); never forward such foreign data.
                if origin != self.origin:
                    await asyncio.sleep(0)
                    continue
                self.outgoing.put(frame(data, 1))
                await asyncio.sleep(0)

        async def tls_writer():
            while True:
                data = await self.outgoing.get()
                self.writer.write(data)
                await asyncio.wait_for(self.writer.drain(), .2)

        async def tls_reader():
            while True:
                kind, data = await read_frame(self.reader, tunnel=True)
                self.rx_rate.take(len(data))
                if kind == 1:
                    self.incoming.put(data)
                else:
                    message = strict_json(data)
                    fields(message, ('operation',))
                    if message['operation'] == 'CLOSE':
                        return
                    if message['operation'] != 'HEARTBEAT':
                        raise ValueError('unexpected_control')

        async def udp_writer():
            while True:
                data = await self.incoming.get()
                await asyncio.wait_for(loop.sock_sendall(self.udp, data), .2)

        async def heartbeat():
            while True:
                await asyncio.sleep(.25)
                self.outgoing.put(frame(json_bytes({'operation': 'HEARTBEAT'}), 2))

        tasks = [asyncio.create_task(coro()) for coro in
                 (udp_reader, tls_writer, tls_reader, udp_writer, heartbeat, self.closed.wait)]
        try:
            done, _pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)


class Gateway:
    def __init__(self, config, run, generation, emit):
        self.config = configuration(config)
        self.run, self.generation = hex_id(run), integer(generation)
        self.emit = emit
        self.context = context(config)
        self.channels = {}
        self.retired = []
        self.retired_ids = set()
        self.tasks = set()
        self.pending = 0
        self.listener = None
        self.stopping = False

    def command(self, operation, body):
        if operation == 'HEARTBEAT':
            fields(body, ())
        elif operation == 'SHUTDOWN':
            fields(body, ())
            raise EOFError('shutdown')
        elif operation in ('ROUTE_ACK', 'ROUTE_CLOSE'):
            if operation == 'ROUTE_CLOSE':
                fields(body, ('channel_id',))
            channel = self.channels.get(body.get('channel_id'))
            if channel is None:
                if operation == 'ROUTE_CLOSE' and body['channel_id'] in self.retired_ids:
                    return  # Concurrent terminal close is idempotent, never reopens.
                raise ValueError('unknown_route')
            if operation == 'ROUTE_ACK':
                channel.acknowledge(body)
            else:
                channel.closed.set()
        else:
            raise ValueError('ipc_operation')

    async def advertise(self, channel, remote_run):
        channel.route_request = self.emit('ROUTE_OPEN', dict(
            channel_id=channel.id, attestor=channel.fingerprint,
            address='127.0.0.1', port=channel.udp.getsockname()[1],
            remote_run_id=remote_run, game_session_id=channel.session))
        await asyncio.wait_for(channel.ack.wait(), 1)
        if channel.closed.is_set():
            raise ValueError('closed_route')

    async def retire(self, channel):
        channel.closed.set()
        self.channels.pop(channel.id, None)
        # Keep the endpoint reserved until process exit. Drain without forwarding.
        self.retired.append(channel.udp)
        self.retired_ids.add(channel.id)
        try:
            if not self.stopping:
                self.emit('ROUTE_CLOSE', {'channel_id': channel.id})
        finally:
            await close_writer(channel.writer)

        async def drain():
            while True:
                try:
                    await asyncio.get_running_loop().sock_recv(channel.udp, 4097)
                    await asyncio.sleep(0)
                except ConnectionRefusedError:
                    await asyncio.sleep(.01)
        self.spawn(drain())

    def spawn(self, coroutine):
        task = asyncio.create_task(coroutine)
        self.tasks.add(task)

        def finished(item):
            self.tasks.discard(item)
            if not item.cancelled():
                item.exception()  # Channel failures are terminal, never unhandled tasks.
        task.add_done_callback(finished)
        return task

    async def serve_socket(self, raw):
        writer = None
        channel = None
        try:
            reader = asyncio.StreamReader(limit=8192)
            protocol = asyncio.StreamReaderProtocol(reader)
            transport, _ = await asyncio.get_running_loop().connect_accepted_socket(
                lambda: protocol, raw, ssl=self.context,
                ssl_handshake_timeout=3, ssl_shutdown_timeout=.2)
            writer = asyncio.StreamWriter(transport, protocol, reader, asyncio.get_running_loop())
            fingerprint = identity(writer, self.config['attestors'])
            if len(self.channels) >= 8 or len(self.channels) + len(self.retired) >= 256:
                raise ValueError('route_capacity')
            channel_id = secrets.token_hex(16)
            if channel_id in self.channels or channel_id in self.retired_ids:
                raise ValueError('channel_collision')
            channel = Channel(self, channel_id, reader, writer, fingerprint, self.config['game_session_id'])
            self.channels[channel.id] = channel
            opening = dict(operation='OPEN', protocol_version=TUNNEL, profile=PROFILE,
                           server_run_id=self.run, channel_id=channel.id,
                           game_session_id=self.config['game_session_id'])
            await send_control(writer, opening)
            kind, data = await read_frame(reader, tunnel=True)
            expected = dict(opening, operation='OPEN_ACK')
            if kind != 2 or strict_json(data) != expected:
                raise ValueError('open_ack')
            await self.advertise(channel, self.run)
            self.pending -= 1
            try:
                await channel.forward()
            finally:
                self.pending += 1
        except (OSError, ValueError, TimeoutError, asyncio.IncompleteReadError):
            # Network rejection is represented by terminal close. Do not let
            # attacker-controlled handshake rates fill a synchronous stderr pipe.
            pass
        finally:
            self.pending -= 1
            if channel is not None:
                await self.retire(channel)
            elif writer is not None:
                await close_writer(writer)
            else:
                raw.close()

    async def listen(self):
        self.listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.listener.setblocking(False)
        self.listener.bind((self.config['host'], self.config['port']))
        self.listener.listen(8)
        self.emit('READY', {'port': self.listener.getsockname()[1]})
        while True:
            raw, _ = await asyncio.get_running_loop().sock_accept(self.listener)
            if self.pending >= 4 or len(self.channels) >= 8 or len(self.channels) + len(self.retired) >= 256:
                raw.close()
                continue
            self.pending += 1  # Quota before TLS allocation/handshake.
            self.spawn(self.serve_socket(raw))

    async def connect(self):
        reader, writer = await asyncio.wait_for(asyncio.open_connection(
            self.config['host'], self.config['port'], ssl=self.context,
            server_hostname=self.config['server_name'], ssl_handshake_timeout=3,
            ssl_shutdown_timeout=.2, limit=8192), 3)
        channel = None
        try:
            identity(writer, [self.config['gateway_pin']])
            kind, data = await read_frame(reader, tunnel=True)
            opening = strict_json(data)
            fields(opening, ('operation', 'protocol_version', 'profile', 'server_run_id',
                             'channel_id', 'game_session_id'))
            if kind != 2 or opening['operation'] != 'OPEN' or opening['protocol_version'] != TUNNEL or opening['profile'] != PROFILE:
                raise ValueError('open_context')
            hex_id(opening['server_run_id'])
            cert = ssl.PEM_cert_to_DER_cert(Path(self.config['cert']).read_text(encoding='ascii'))
            channel = Channel(self, opening['channel_id'], reader, writer,
                              hashlib.sha256(cert).hexdigest(), opening['game_session_id'])
            self.channels[channel.id] = channel
            await send_control(writer, dict(opening, operation='OPEN_ACK'))
            self.emit('READY', {'port': 0})
            await self.advertise(channel, opening['server_run_id'])
            await channel.forward()
        finally:
            if channel is not None:
                await self.retire(channel)
            else:
                await close_writer(writer)

    async def close(self):
        self.stopping = True
        if self.listener is not None:
            self.listener.close()
        for channel in self.channels.values():
            channel.closed.set()
        tasks = list(self.tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        # Retire may create drain tasks during cancellation; stop these too.
        remaining = list(self.tasks)
        for task in remaining:
            task.cancel()
        await asyncio.gather(*remaining, return_exceptions=True)
        for channel in self.channels.values():
            channel.udp.close()
        self.channels.clear()
        for udp in self.retired:
            udp.close()
        self.retired.clear()


async def stdio_main():
    loop = asyncio.get_running_loop()
    reader = asyncio.StreamReader(limit=8192)
    incoming_transport, _ = await loop.connect_read_pipe(
        lambda: asyncio.StreamReaderProtocol(reader), sys.stdin.buffer)
    outgoing = BoundedQueue(count=128, size=262144, age=.2)
    tx, rx = Sequence(), Sequence()
    gateway = None
    tasks = []
    try:
        first = strict_json(await read_frame(reader, idle=5))
        fields(first, ('protocol_version', 'server_run_id', 'gateway_generation',
                       'request_id', 'operation', 'body'))
        run = hex_id(first.get('server_run_id'))
        generation = integer(first.get('gateway_generation'))
        operation, config = validate_envelope(first, run, generation, rx)
        if operation != 'CONFIG':
            raise ValueError('config_required')

        def emit(operation, body):
            request = tx.next()
            outgoing.put(frame(json_bytes(envelope(run, generation, request, operation, body))))
            return request

        gateway = Gateway(config, run, generation, emit)
        os.set_blocking(sys.stdout.fileno(), False)

        async def output():
            while True:
                data = await outgoing.get()
                sent = 0
                deadline = time.monotonic() + .2
                while sent < len(data):
                    if time.monotonic() >= deadline:
                        raise TimeoutError('ipc_write')
                    try:
                        count = os.write(sys.stdout.fileno(), data[sent:])
                        if count == 0:
                            raise BrokenPipeError('ipc_write')
                        sent += count
                    except BlockingIOError:
                        await asyncio.sleep(.001)

        async def commands():
            while True:
                message = strict_json(await read_frame(reader))
                operation, body = validate_envelope(message, run, generation, rx)
                gateway.command(operation, body)

        async def heartbeat():
            while True:
                emit('HEARTBEAT', {})
                await asyncio.sleep(.25)

        tasks = [asyncio.create_task(coro()) for coro in (output, commands, heartbeat)]
        tasks.append(asyncio.create_task(gateway.listen() if config['role'] == 'server' else gateway.connect()))
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            task.result()
    except EOFError:
        pass
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if gateway is not None:
            await gateway.close()
        incoming_transport.close()


def main():
    try:
        asyncio.run(stdio_main())
    except (OSError, ValueError, TimeoutError, asyncio.IncompleteReadError, KeyError, TypeError) as error:
        # Never include certificate paths, keys or untrusted payload in diagnostics.
        reason = str(error) if type(error) is ValueError and str(error).replace('_','').isalpha() else type(error).__name__
        print('GATEWAY_CLOSED: '+reason, file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
