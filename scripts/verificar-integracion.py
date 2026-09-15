"""Verify Linux UDP handshakes and session lifecycle in a disposable build."""
import argparse
from contextlib import contextmanager, ExitStack
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import platform
import signal
import socket
import struct
import tempfile
import time
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('build_checks', ROOT / 'scripts/verificar-build.py')
build_checks = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build_checks)


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def packet(kind, payload, seq=0):
    return struct.pack('<BBBBII4s', 0x4c, 2, kind, 0, seq, len(payload), b'\xaa' * 4) + payload


def hello(nonce):
    return packet(1, struct.pack('<I16s24s16s', 0x4c414201, b'LabClient', b'hello-test', nonce))


def exchange(client, peer, data):
    require(client.sendto(data, peer) == len(data), 'datagrama enviado parcialmente')
    response, sender = client.recvfrom(65535)
    require(sender == peer, f'respuesta de otro peer: {sender}')
    return response


def expect_rst(data, reason, message, seq=0, session=None):
    expected = packet(0x20, (data[16:32] if session is None else session) + struct.pack('<II36s', reason, len(message), message), seq)
    require(data == expected, f'RST inesperado: {data.hex()}')


def available_port():
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as reservation:
        reservation.bind(('127.0.0.1', 0))
        return reservation.getsockname()[1]


@contextmanager
def program(command, directory, evidence, port):
    record = {'command': command, 'startup_timeout_seconds': 3,
              'cleanup_timeout_seconds': 2, 'forced_kill': False}
    evidence['servers'].append(record)
    start = time.monotonic()
    with tempfile.TemporaryFile(mode='w+t', dir=directory) as log:
        process = subprocess.Popen(command, cwd=ROOT, stdout=log, stderr=log)
        try:
            deadline = start + 3
            while True:
                log.seek(0)
                first = log.readline()
                if first.endswith('\n') and first.startswith('{'):
                    boot = json.loads(first)
                    require(boot.get('ev') == 'boot' and boot.get('port') == port,
                            'evento de arranque inesperado')
                    break
                require(process.poll() is None, f'proceso terminó durante arranque: {first}')
                require(time.monotonic() < deadline, 'timeout esperando arranque')
                time.sleep(0.01)
            yield ('127.0.0.1', port)
            require(process.poll() is None, 'proceso terminó durante las pruebas')
        finally:
            record['exit_before_cleanup'] = process.poll()
            if process.poll() is None:
                process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                record['forced_kill'] = True
                process.kill()
                process.wait(timeout=2)
            log.seek(0)
            record.update(exit_code=process.returncode, stdout=log.read(),
                          elapsed_seconds=round(time.monotonic() - start, 3))


@contextmanager
def adapter(binary, directory, evidence, upstream, options=(), port=None):
    port = port or available_port()
    command = [str(binary), '--listen', f'127.0.0.1:{port}',
               '--upstream', f'{upstream[0]}:{upstream[1]}', '-v', *options]
    with program(command, directory, evidence, port) as peer:
        yield peer


@contextmanager
def server(binary, directory, evidence, *, max_clients=32, timeout_ms=5000):
    port = available_port()
    command = [str(binary), '--host', '127.0.0.1', '--port', str(port),
               '--timeout-ms', str(timeout_ms), '--max', str(max_clients), '-v']
    with program(command, directory, evidence, port) as peer:
        if evidence.get('via_adapter'):
            with adapter(evidence['adapter_binary'], directory, evidence, peer) as relay:
                yield relay
        else:
            yield peer


def check_hello(peer, evidence, deterministic=False):
    nonce = bytes(range(1, 17))
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
        client.settimeout(1)
        client.bind(('127.0.0.1', 0))
        ack = exchange(client, peer, hello(nonce))
        require(len(ack) == 72, f'ACK de {len(ack)} bytes, esperado 72')
        result, reason, session, snonce, echo = struct.unpack('<II16s16s16s', ack[16:])
        require(ack[:16] == packet(2, bytes(56))[:16], 'cabecera ACK incorrecta')
        require((result, reason, echo) == (1, 0, nonce), 'resultado/razón/nonce de ACK incorrectos')
        require(session != bytes(16) and snonce != bytes(16), 'sesión o nonce completo nulo')
        if deterministic:
            require(session == b'\x42' * 16 and snonce == b'\x42' * 16,
                    'no se completó la lectura parcial de entropía')
        # Prove the ACK session is the one stored by the real server.
        ping_nonce = bytes(range(16))
        stamp = 0x1020304050607080
        ping = packet(0x10, struct.pack('<16s16sQ', session, ping_nonce, stamp), 1)
        pong = exchange(client, peer, ping)
        require(pong == packet(0x11, struct.pack('<Q16sI', stamp, ping_nonce, 0)),
                f'PONG incorrecto para la sesión del ACK: {pong.hex()}')
    evidence['cases'].append('hello_ack_session_ping_partial_entropy' if deterministic
                             else 'hello_ack_exact_and_session_ping')


def check_rejections(peer, evidence):
    valid = hello(bytes(range(17, 33)))
    cases = [
        ('short_header', b'L', 1, b'hdr'),
        ('bad_padding', valid[:12] + bytes(4) + valid[16:], 1, b'hdr'),
        ('wrong_length', valid[:8] + struct.pack('<I', 59) + valid[12:], 4, b'len != real'),
        ('wrong_app', valid[:16] + bytes(4) + valid[20:], 5, b'app_id != LAB1'),
    ]
    for index, (name, data, reason, message) in enumerate(cases):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
            client.settimeout(1)
            expect_rst(exchange(client, peer, data), reason, message)
            # Rejection must leave a usable slot and the process alive.
            ack = exchange(client, peer, hello(bytes([80 + index]) * 16))
            require(len(ack) == 72 and ack[:24] == packet(2, bytes(56))[:16]
                    + struct.pack('<II', 1, 0), f'{name}: no acepta HELLO tras rechazo')
        evidence['cases'].append(name)


def open_session(client, peer, nonce):
    ack = exchange(client, peer, hello(nonce))
    require(len(ack) == 72 and ack[:24] == packet(2, bytes(56))[:16]
            + struct.pack('<II', 1, 0) and ack[56:] == nonce, f'ACK de sesión incorrecto: {ack.hex()}')
    return ack[24:40]


def ping_session(client, peer, session, seq):
    nonce, stamp = bytes(range(16)), 0x1020304050607080
    data = packet(0x10, struct.pack('<16s16sQ', session, nonce, stamp), seq)
    expected = packet(0x11, struct.pack('<Q16sI', stamp, nonce, 0))
    require(exchange(client, peer, data) == expected, 'sesión afectada por el cierre de otro cliente')


def close_packet(kind, session):
    return packet(kind, session + ( struct.pack('<II', 0, 0) if kind == 0x30
                  else struct.pack('<II36s', 0, 0, b'')))


def check_sessions(binary, directory, evidence):
    # Persistent sockets prevent the OS from reassigning an earlier test's peer.
    with ExitStack() as stack:
        clients = [stack.enter_context(socket.socket(socket.AF_INET, socket.SOCK_DGRAM))
                   for _ in range(4)]
        for client in clients:
            client.bind(('127.0.0.1', 0))
            client.settimeout(1)
        with server(binary, directory, evidence, max_clients=3) as peer:
            sessions = [open_session(c, peer, bytes([i + 1]) * 16)
                        for i, c in enumerate(clients[:3])]
            expect_rst(exchange(clients[3], peer, hello(b'\x04' * 16)), 14, b'max alcanzado')
            evidence['cases'].append('capacity_enforced')
            # Release last, first and middle entries; other clients keep working.
            sequences = [1, 1, 1]
            for index in [2, 0, 1]:
                expect_rst(exchange(clients[index], peer, close_packet(0x30, sessions[index])), 0, b'bye')
                expect_rst(exchange(clients[index], peer, close_packet(0x30, sessions[index])), 3, b'HELLO primero')
                for other in range(3):
                    if other != index:
                        ping_session(clients[other], peer, sessions[other], sequences[other])
                        sequences[other] += 1
                replacement = open_session(clients[3], peer, b'\x05' * 16)
                ping_session(clients[3], peer, replacement, 1)
                expect_rst(exchange(clients[3], peer, close_packet(0x20, replacement)), 0, b'rst')
                expect_rst(exchange(clients[3], peer, close_packet(0x20, replacement)), 3, b'HELLO primero')
                old_session = sessions[index]
                sessions[index] = open_session(clients[index], peer, bytes([index + 1]) * 16)
                require(sessions[index] != old_session, 'la sesión cerrada fue reutilizada')
                stale_ping = packet(0x10, struct.pack('<16s16sQ', old_session, bytes(16), 1), 1)
                expect_rst(exchange(clients[index], peer, stale_ping), 8, b'session !=')
                ping_session(clients[index], peer, sessions[index], 1)
                sequences[index] = 2
                # BAD_SESSION consumed one RST sequence; use a clean session next.
                expect_rst(exchange(clients[index], peer, close_packet(0x20, sessions[index])), 0, b'rst', 1)
                sessions[index] = open_session(clients[index], peer, bytes([index + 1]) * 16)
                sequences[index] = 1
                evidence['cases'].append(f'release_slot_{index}_isolation_and_reopen')
        for index, client in enumerate(clients):
            client.close()
            clients[index] = stack.enter_context(socket.socket(socket.AF_INET, socket.SOCK_DGRAM))
            clients[index].bind(('127.0.0.1', 0)); clients[index].settimeout(1)
        with server(binary, directory, evidence, max_clients=1) as peer:
            # More openings than both the session table and old nonce ring capacity.
            for count in range(70):
                client = clients[count % 2]
                session = open_session(client, peer, bytes([count + 1]) * 16)
                ping_session(client, peer, session, 1)
                kind = 0x30 if count % 2 == 0 else 0x20
                expect_rst(exchange(client, peer, close_packet(kind, session)), 0,
                           b'bye' if kind == 0x30 else b'rst')
            evidence['cases'].append('70_bye_rst_cycles_capacity_one')
        for index, client in enumerate(clients):
            client.close()
            clients[index] = stack.enter_context(socket.socket(socket.AF_INET, socket.SOCK_DGRAM))
            clients[index].bind(('127.0.0.1', 0)); clients[index].settimeout(1)
        with server(binary, directory, evidence, max_clients=1) as peer:
            client = clients[0]
            session = open_session(client, peer, b'\x10' * 16)
            invalid = []
            for kind in [0x30, 0x20]:
                good = close_packet(kind, session)
                invalid += [(good[:-1], b'bye len' if kind == 0x30 else b'rst len'),
                            (good + b'X', b'bye len' if kind == 0x30 else b'rst len'),
                            (good[:8] + bytes(4) + good[12:], b'bye len' if kind == 0x30 else b'rst len')]
            for index, (data, message) in enumerate(invalid):
                expect_rst(exchange(client, peer, data), 4, message, index)
                ping_session(client, peer, session, index + 1)
                expect_rst(exchange(clients[1], peer, hello(b'\x11' * 16)), 14, b'max alcanzado')
            invalid_msg = packet(0x20, session + struct.pack('<II36s', 0, 37, b''))
            expect_rst(exchange(client, peer, invalid_msg), 5, b'rst msg len', len(invalid))
            ping_session(client, peer, session, len(invalid) + 1)
            expect_rst(exchange(client, peer, close_packet(0x20, session)), 0, b'rst', len(invalid) + 1)
            open_session(clients[1], peer, b'\x11' * 16)
            evidence['cases'].append('malformed_close_preserves_session')
        for index, client in enumerate(clients):
            client.close()
            clients[index] = stack.enter_context(socket.socket(socket.AF_INET, socket.SOCK_DGRAM))
            clients[index].bind(('127.0.0.1', 0)); clients[index].settimeout(1)
        with server(binary, directory, evidence, max_clients=1, timeout_ms=50) as peer:
            session = open_session(clients[0], peer, b'\x12' * 16)
            data, sender = clients[0].recvfrom(65535)
            require(sender == peer, 'timeout enviado por otro peer')
            expect_rst(data, 17, b'timeout')
            reopened = open_session(clients[1], peer, b'\x13' * 16)
            require(session != reopened, 'timeout conservó la sesión anterior')
            ping_session(clients[1], peer, reopened, 1)
            evidence['cases'].append('idle_timeout_releases_capacity')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--hello', action='store_true')
    modes.add_argument('--sessions', action='store_true')
    modes.add_argument('--direct', action='store_true')
    modes.add_argument('--via-adapter', action='store_true')
    parser.add_argument('--sanitize', action='store_true', help='Run with AddressSanitizer and UBSan')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()

    sources = [ROOT / 'CMakeLists.txt', Path(__file__).resolve(),
               ROOT / 'scripts/verificar-build.py', ROOT / 'tests/server_random_fault.c']
    sources += sorted((ROOT / 'tests').glob('*.py'))
    sources += sorted((ROOT / 'lab').rglob('*.c')) + sorted((ROOT / 'lab').rglob('*.h'))
    evidence = {'date': datetime.now(timezone.utc).isoformat(),
                'scope': 'via-adapter' if args.via_adapter else 'direct' if args.direct else 'sessions' if args.sessions else 'hello',
                'via_adapter': args.via_adapter,
                'environment': {'system': platform.platform(), 'machine': platform.machine()},
                'source_sha256': {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                                  for p in sources},
                'checks': [], 'servers': [], 'cases': [], 'network_timeout_seconds': 1,
                'sanitizers': args.sanitize,
                'passed': False}
    start = time.monotonic()
    try:
        with tempfile.TemporaryDirectory(prefix='middleware-hello-') as directory:
            build = Path(directory) / 'build'
            evidence['adapter_binary'] = str(build / 'lab_adapter')
            flags = ['-Werror']
            if args.sanitize:
                flags += ['-fsanitize=address,undefined', '-fno-sanitize-recover=all',
                          '-fno-omit-frame-pointer']
            commands = [
                ['cc', '--version'],
                ['cmake', '-S', str(ROOT), '-B', str(build), '-G', 'Ninja',
                 '-DCMAKE_BUILD_TYPE=Release', '-DCMAKE_C_FLAGS=' + ' '.join(flags)],
                ['cmake', '--build', str(build), '--parallel', '2'],
                ['ctest', '--test-dir', str(build), '--output-on-failure', '--timeout', '10'],
            ]
            for command in commands:
                result = build_checks.run(command, 60)
                evidence['checks'].append(result)
                require(result['exit_code'] == 0, 'falló build/CTest: ' + result['stdout'] + result['stderr'])
            with server(build / 'lab_server', directory, evidence) as peer:
                check_hello(peer, evidence)
                check_rejections(peer, evidence)
            if args.sessions or args.direct or args.via_adapter:
                check_sessions(build / 'lab_server', directory, evidence)
            if args.direct or args.via_adapter:
                test_spec = importlib.util.spec_from_file_location('transport_cases', ROOT / 'tests/transport_cases.py')
                test_module = importlib.util.module_from_spec(test_spec)
                test_spec.loader.exec_module(test_module)
                test_module.cases(sys.modules[__name__], build, directory, evidence)
                policy_spec = importlib.util.spec_from_file_location('policy_cases', ROOT / 'tests/policy_cases.py')
                policy_tests = importlib.util.module_from_spec(policy_spec)
                policy_spec.loader.exec_module(policy_tests)
                policy_tests.cases(sys.modules[__name__], build, directory, evidence)
                if args.via_adapter:
                    adapter_spec = importlib.util.spec_from_file_location('adapter_cases', ROOT / 'tests/adapter_cases.py')
                    adapter_tests = importlib.util.module_from_spec(adapter_spec)
                    adapter_spec.loader.exec_module(adapter_tests)
                    adapter_tests.cases(sys.modules[__name__], build, directory, evidence)
            # A separate test executable wraps entropy; production uses the OS.
            fault_binary = Path(directory) / 'server_random_fault'
            command = ['cc', '-std=c11', '-Wall', '-Wextra', '-O2', *flags,
                       'lab/server/server.c', 'lab/contracts/lab_util.c', 'lab/contracts/evidence.c',
                       'tests/server_random_fault.c', '-Wl,--wrap=getrandom', '-o', str(fault_binary)]
            result = build_checks.run(command, 60)
            evidence['checks'].append(result)
            require(result['exit_code'] == 0, result['stdout'] + result['stderr'])
            with server(fault_binary, directory, evidence) as peer:
                # The wrapper returns EINTR, partial data, EIO, then zero bytes.
                check_hello(peer, evidence, deterministic=True)
                for failure in ['entropy_error', 'entropy_eof']:
                    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
                        client.settimeout(1)
                        expect_rst(exchange(client, peer, hello(bytes(range(33, 49)))),
                                   14, b'entropy unavailable')
                    evidence['cases'].append(failure)
            for record in evidence['servers']:
                require(record['exit_before_cleanup'] is None and not record['forced_kill']
                        and record['exit_code'] == 0, 'salida del servidor inesperada')
                for line in record['stdout'].splitlines():
                    json.loads(line)
            evidence['passed'] = True
    except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as error:
        evidence['error'] = str(error)
    evidence['elapsed_seconds'] = round(time.monotonic() - start, 3)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(evidence, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    if evidence['passed']:
        print(f"OK: {evidence['scope']}, {len(evidence['cases'])} casos UDP; integración completa pendiente.")
        return 0
    print('FAIL: ' + evidence.get('error', 'consultar evidencia'))
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
