"""Real loopback TLS clients, C game worker and bounded failure/CLI tests."""
import argparse
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import socket
import ssl
import struct
import subprocess
import sys
import tempfile
import traceback

from bridge_transport import encode_frame, read_frame, tls_context
from game_service import GameService, state, command, close_writer

ROOT = Path(__file__).resolve().parents[1]


from game_credentials import certificates


@asynccontextmanager
async def running(binary, folder):
    service = GameService(binary, [folder / 'client.crt', folder / 'client2.crt'])
    await service.start()
    server = None
    try:
        server = await asyncio.start_server(service.handle, '127.0.0.1', 0,
                    ssl=tls_context(folder / 'server.crt', folder / 'server.key', folder / 'ca.crt', True),
                    ssl_handshake_timeout=1, ssl_shutdown_timeout=1)
        yield service, server.sockets[0].getsockname()[1]
    finally:
        if server:
            server.close()
            await server.wait_closed()
        await service.close()
        assert service.process.returncode is not None and not service.tasks


async def connect(folder, port, name='client', server_name='localhost'):
    r, w = await asyncio.wait_for(asyncio.open_connection('127.0.0.1', port,
        ssl=tls_context(folder / (name + '.crt'), folder / (name + '.key'), folder / 'ca.crt'),
        server_hostname=server_name, ssl_shutdown_timeout=1), 2)
    try:
        hello = await read_frame(r, 2)
        return r, w, hello
    except BaseException:
        await close_writer(w)
        raise


async def exchange(pair, data):
    reader, writer, _ = pair
    writer.write(encode_frame(data))
    await asyncio.wait_for(writer.drain(), 2)
    return await read_frame(reader, 3)


async def next_tick(service, after):
    # Wait for a condition, with a deadline; no action retries to hide a race.
    async with asyncio.timeout(2):
        while int((asyncio.get_running_loop().time() - service.started) / 0.05) <= after:
            await asyncio.sleep(0.005)


async def disconnected(service, slot):
    async with asyncio.timeout(3):
        while service.connected[slot]:
            await asyncio.sleep(0.005)


async def checks(binary, folder, report):
    async with running(binary, folder) as (service, port):
        unknown = await connect(folder, port, 'unknown')
        assert unknown[2] == b'LGRE\x01'
        await close_writer(unknown[1])
        try:
            await connect(folder, port, server_name='wrong.invalid')
            raise AssertionError('wrong server accepted')
        except ssl.SSLCertVerificationError:
            pass
        context = ssl.create_default_context(cafile=str(folder / 'ca.crt'))
        writer = None
        try:
            reader, writer = await asyncio.wait_for(asyncio.open_connection('127.0.0.1', port,
                ssl=context, server_hostname='localhost'), 2)
            assert await asyncio.wait_for(reader.read(1), 2) == b''
        except (ssl.SSLError, ConnectionError):
            pass
        finally:
            if writer:
                await close_writer(writer)
        report['cases'].append('tls_identity_missing_certificate_and_unenrolled_certificate')
        a = await connect(folder, port)
        assert state(a[2])['player'] == 0
        assert await exchange(a, command(a[2], 1, 'fire')) == b'LGRE\x07'
        duplicate = await connect(folder, port)
        assert duplicate[2] == b'LGRE\x02'
        await close_writer(duplicate[1])
        b = await connect(folder, port, 'client2')
        try:
            assert state(b[2])['player'] == 1
            wrong = await exchange(a, command(b[2], 1, 'fire'))
            assert state(wrong)['reason'] == 'WRONG_SESSION'
            assert all(p['health'] == 100 and p['ammo'] == 4 for p in state(wrong)['players'])
            saved = command(a[2], 1, 'east')
            result = state(await exchange(a, saved))
            assert result['reason'] == 'ACCEPTED' and result['players'][0]['x_mm'] == 100
            repeat = state(await exchange(a, saved))
            assert repeat['reason'] == 'SEQUENCE_REPLAY' and repeat['players'] == result['players']
            await next_tick(service, result['tick'])
            result = state(await exchange(a, command(a[2], 2, 'fire')))
            assert result['reason'] == 'ACCEPTED' and result['players'][1]['health'] == 75
            assert result['players'][0]['ammo'] == 3
            # Deliberately unaligned byte-by-byte TLS frame writes and concatenation.
            for byte in encode_frame(command(b[2], 1, 'north')):
                b[1].write(bytes((byte,)))
            await b[1].drain()
            moved = state(await read_frame(b[0]))
            assert moved['reason'] == 'ACCEPTED' and moved['players'][1]['y_mm'] == 100
            duplicate_frame = encode_frame(command(b[2], 1, 'north'))
            b[1].write(duplicate_frame * 2)
            await b[1].drain()
            for _ in range(2):
                repeated = state(await read_frame(b[0]))
                assert repeated['reason'] == 'SEQUENCE_REPLAY' and repeated['players'] == moved['players']
            report['cases'].append('two_tls_players_real_c_state_isolation_hits_replay_partial_and_concatenated_frames')
            old_match = a[2][20:36]
        finally:
            await close_writer(a[1])
            await disconnected(service, 0)
            assert not state(await service.snapshot(0))['players'][0]['open']
            assert await exchange(b, command(b[2], 2, 'fire')) == b'LGRE\x07'
            again = await connect(folder, port)
            assert again[2] == b'LGRE\x03'
            await close_writer(again[1])
            await close_writer(b[1])
        report['cases'].append('no_phantom_opponent_duplicate_login_or_reopened_closed_session')

    async with running(binary, folder) as (service, port):
        a = await connect(folder, port)
        b = await connect(folder, port, 'client2')
        try:
            assert a[2][20:36] != old_match
            assert state(await exchange(a, saved))['reason'] == 'WRONG_MATCH'
            # A remote 50-byte supervisor envelope must never reach private controls.
            assert await exchange(a, bytes(50)) == b'LGRE\x05'
            await disconnected(service, 0)
            assert not state(await service.snapshot(0))['players'][0]['open']
        finally:
            await close_writer(a[1]); await close_writer(b[1])
        report['cases'].append('restart_new_instance_and_private_control_envelope_rejected')

    async with running(binary, folder) as (service, port):
        a = await connect(folder, port)
        b = await connect(folder, port, 'client2')
        try:
            for seq in range(1, 257):
                value = state(await exchange(a, command(a[2], seq, 'wait')))
                assert value['reason'] in ('ACCEPTED', 'TICK_ALREADY_USED')
            assert await read_frame(a[0], 2) == b'LGRE\x06'
            await disconnected(service, 0)
        finally:
            await close_writer(a[1]); await close_writer(b[1])
        report['cases'].append('bounded_256_inputs_per_session')

    async with running(binary, folder) as (service, port):
        a = await connect(folder, port)
        try:
            a[1].write(b'\x00')  # Partial header cannot keep a slot alive indefinitely.
            await a[1].drain()
            assert await asyncio.wait_for(a[0].read(1), 3) == b''
            await disconnected(service, 0)
        finally:
            await close_writer(a[1])
        report['cases'].append('partial_frame_absolute_timeout_closes_slot')

    async with running(binary, folder) as (service, port):
        a = await connect(folder, port)
        b = await connect(folder, port, 'client2')
        try:
            service.process.terminate()
            await asyncio.wait_for(service.process.wait(), 2)
            try:
                await exchange(a, command(a[2], 1, 'fire'))
                raise AssertionError('dead worker returned game decision')
            except (asyncio.IncompleteReadError, ConnectionError):
                pass
        finally:
            await close_writer(a[1]); await close_writer(b[1])
        report['cases'].append('worker_death_invalidates_connection_without_respawn')


async def cli(binary, folder, report):
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0)); port = probe.getsockname()[1]
    base = [sys.executable, str(ROOT / 'scripts/game.py')]
    server_args = ['serve', '--binary', str(binary), '--port', str(port),
                   '--player0-cert', str(folder / 'client.crt'), '--player1-cert', str(folder / 'client2.crt')]
    tls = lambda name: ['--cert', str(folder / (name + '.crt')), '--key', str(folder / (name + '.key')),
                        '--ca', str(folder / 'ca.crt')]
    server = await asyncio.create_subprocess_exec(*base, *server_args, *tls('server'),
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    children = []
    try:
        ready = json.loads(await asyncio.wait_for(server.stdout.readline(), 3))
        assert ready['event'] == 'ready' and ready['port'] == port
        for name, move in [('client', 'east'), ('client2', 'north')]:
            child = await asyncio.create_subprocess_exec(*base, 'client', '--port', str(port),
                        '--actions', 'wait,' + move + ',wait,wait', *tls(name),
                        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            children.append(child)
        for child in children:
            output, error = await asyncio.wait_for(child.communicate(), 5)
            assert child.returncode == 0, error.decode()
            events = [json.loads(line) for line in output.splitlines()]
            assert events[0]['event'] == 'joined'
            accepted = [e for e in events[1:] if e['reason'] == 'ACCEPTED']
            assert len(accepted) >= 2 and accepted[-1]['players'][0]['x_mm'] == 100
            assert accepted[-1]['players'][1]['y_mm'] == 100
        server.terminate()
        await asyncio.wait_for(server.wait(), 3)
        assert server.returncode == 0
        report['cases'].append('cli_server_and_two_separate_client_processes_shutdown')
    finally:
        for child in [*children, server]:
            if child.returncode is None:
                child.kill()
            await asyncio.wait_for(child.wait(), 3)


def private_worker(binary, report):
    for data, status, length in [(b'', 0, 160), (b'\x01', 1, 160),
            (b'\x04\x02' + bytes(48), 1, 160), (b'\x04\x00' + bytes(48), 0, 240),
            (b'\x02\x00' + struct.pack('<Q', 10) + bytes(40) + b'\x02\x00' + bytes(48), 1, 240)]:
        result = subprocess.run([str(binary)], input=data, capture_output=True, timeout=3)
        assert result.returncode == status and len(result.stdout) == length, (result.returncode, result.stderr)
        assert b'AddressSanitizer' not in result.stderr and b'runtime error:' not in result.stderr
    report['cases'].append('private_worker_eof_truncation_slot_and_clock_rollback')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', type=Path, default=ROOT / 'build/lab_game_host')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    report = dict(passed=False, scope='real local TLS and C game worker; no engine or TPM admission',
                  date=datetime.now(timezone.utc).isoformat(), system=platform.platform(), cases=[])
    paths = ['CMakeLists.txt', 'lab/game/game.h', 'lab/game/game.c', 'lab/app/game_host.c',
             'scripts/game_service.py', 'scripts/game.py', 'scripts/verificar-juego-red.py',
             'scripts/bridge_transport.py', 'scripts/game_credentials.py']
    report['source_sha256'] = {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in paths}
    try:
        private_worker(args.binary.resolve(), report)
        with tempfile.TemporaryDirectory(prefix='lab-game-tls-') as directory:
            folder = Path(directory)
            certificates(folder)
            asyncio.run(checks(args.binary.resolve(), folder, report))
            asyncio.run(cli(args.binary.resolve(), folder, report))
        report['passed'] = True
        report['temporary_credentials_removed'] = not folder.exists()
    except (OSError, ValueError, RuntimeError, AssertionError, subprocess.SubprocessError,
            asyncio.TimeoutError, asyncio.IncompleteReadError) as error:
        report['error'] = str(error) or type(error).__name__
        report['traceback'] = traceback.format_exc(limit=6)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
