"""Protocol histories, malformed packets and real client CLI checks."""
from contextlib import ExitStack
import json
import random
import socket
import struct
import threading
import time


def cases(h, build, directory, evidence):
    with ExitStack() as stack:
        clients = [stack.enter_context(socket.socket(socket.AF_INET, socket.SOCK_DGRAM)) for _ in range(3)]
        for c in clients:
            c.bind(('127.0.0.1', 0)); c.settimeout(1)
        with h.server(build / 'lab_server', directory, evidence) as peer:
            c, other, bad = clients
            nonce = b'\x00' + b'a' * 15
            first = h.exchange(c, peer, h.hello(nonce))
            h.require(len(first) == 72, 'nonce con un byte cero rechazado')
            h.require(h.exchange(c, peer, h.hello(nonce)) == first, 'HELLO retransmitido cambia sesión/ACK')
            session = first[24:40]
            h.expect_rst(h.exchange(other, peer, h.hello(nonce)), 15, b'duplicate nonce')
            h.expect_rst(h.exchange(other, peer, h.hello(bytes(16))), 5, b'nonce cero')
            h.expect_rst(h.exchange(c, peer, h.hello(b'b' * 16)), 6, b'otro HELLO', session=session)
            evidence['cases'].append('binary_nonce_duplicate_and_hello_retransmission')
            rst_sequence = 1
            history = [(1, 0), (3, 0), (2, 0), (3, 10), (2, 10)]
            history += [(i, 0) for i in range(4, 50)]
            history += [(40, 10), (1, 9), (58, 0), (55, 0), (55, 10), (68, 9)]
            for seq, reason in history:
                ping = h.packet(0x10, struct.pack('<16s16sQ', session, b'x' * 16, seq), seq)
                response = h.exchange(c, peer, ping)
                if reason:
                    h.expect_rst(response, reason, b'BAD_SEQ' if reason == 9 else b'REPLAY', rst_sequence, session)
                    rst_sequence += 1
                else:
                    h.require(response == h.packet(0x11, struct.pack('<Q16sI', seq, b'x' * 16, 0)), 'PONG incorrecto')
            evidence['cases'].append('live_sequence_history')
            old = session
            h.expect_rst(h.exchange(c, peer, h.close_packet(0x30, old)), 0, b'bye', rst_sequence, old)
            session = h.open_session(c, peer, b'c' * 16)
            for index, kind in enumerate([0x30, 0x20]):
                h.expect_rst(h.exchange(c, peer, h.close_packet(kind, old)), 8, b'session !=', index, session)
            h.ping_session(c, peer, session, 1)
            exhausted = h.packet(0x10, struct.pack('<16s16sQ', session, b'x' * 16, 0), 0xffffffff)
            h.expect_rst(h.exchange(c, peer, exhausted), 16, b'CLOSING', 2, session)
            h.open_session(c, peer, b'd' * 16)
            evidence['cases'].append('stale_close_and_sequence_exhaustion')
            old_version = bytearray(h.hello(b'v' * 16)); old_version[1] = 1
            h.expect_rst(h.exchange(bad, peer, old_version), 2, b'version')
            oversized = h.hello(b'q' * 16) + bytes(500)
            h.expect_rst(h.exchange(bad, peer, oversized), 11, b'>128 B')
            rng = random.Random(1821)
            for length in range(0, 129):
                data = bytes(rng.randrange(256) for _ in range(length))
                response = h.exchange(bad, peer, data)
                h.require(len(response) == 76 and response[2] == 0x20, 'fuzz acotado: respuesta incorrecta')
            h.open_session(bad, peer, b'z' * 16)
            evidence['cases'].append('v1_rejection_oversize_and_129_malformed_datagrams')
    # Continuous traffic must not postpone expiration of another peer.
    for invalid in [False, True]:
        with h.server(build / 'lab_server', directory, evidence, timeout_ms=200) as peer:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as c, socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as noise:
                c.settimeout(1); noise.settimeout(0.05)
                session = h.open_session(c, peer, b'e' * 16)
                until = time.monotonic() + 0.65
                sequence = 1
                if not invalid:
                    while time.monotonic() < until:
                        h.ping_session(c, peer, session, sequence); sequence += 1; time.sleep(0.025)
                    evidence['cases'].append('accepted_ping_refreshes_deadline')
                stopped = threading.Event()
                def flood():
                    while not stopped.is_set():
                        (c if invalid else noise).sendto(b'bad', peer)
                        if not invalid:
                            try: noise.recvfrom(4096)
                            except socket.timeout: pass
                        stopped.wait(0.001)
                worker = threading.Thread(target=flood)
                worker.start()
                try:
                    deadline = time.monotonic() + 2
                    while True:
                        h.require(time.monotonic() < deadline, 'tráfico inválido mantiene la sesión')
                        response, sender = c.recvfrom(65535)
                        h.require(sender == peer, 'timeout de otro origen')
                        if len(response) == 76 and struct.unpack_from('<I', response, 32)[0] == 17:
                            h.expect_rst(response, 17, b'timeout', struct.unpack_from('<I', response, 4)[0], session)
                            break
                        h.require(invalid and response[2] == 0x20, 'respuesta inesperada durante expiración')
                finally:
                    stopped.set(); worker.join(1)
                    h.require(not worker.is_alive(), 'hilo de prueba sin finalizar')
                evidence['cases'].append('invalid_activity_does_not_refresh' if invalid else 'expiry_with_continuous_other_peer_traffic')
    with h.server(build / 'lab_server', directory, evidence) as peer:
        result = h.build_checks.run([str(build/'lab_client'), '--host', peer[0], '--port', str(peer[1]), '--count','3','--name','demo'], 5)
        evidence['checks'].append(result)
        h.require(result['exit_code'] == 0 and json.loads(result['stdout'])['ok'], 'cliente C falló')
        evidence['cases'].append('native_client_roundtrip_and_close')
    for binary, option, values in [
        ('lab_client','--port',['','-1','+1','0','65536','12x','4294967296']),
        ('lab_server','--timeout-ms',['','-1','+1','0','60001','12x']),
        ('lab_server','--max',['','-1','+1','0','33','12x']),
        ('lab_adapter','--max-clients',['','-1','+1','0','33','12x']),
    ]:
        for value in values:
            result = h.build_checks.run([str(build/binary), option, value], 2)
            h.require(result['exit_code'] == 2, f'CLI {binary}: {value!r} no rechazada')
    evidence['cases'].append('25_invalid_cli_inputs')

    with h.server(build / 'lab_server', directory, evidence, timeout_ms=250) as peer:
        for case in ['bad-magic','bad-version','bad-kind','bad-payload','bad-len','bad-session','dup','replay','trunc','bad-seq','stale','too-big','timeout']:
            result=h.build_checks.run([str(build/'lab_fault'),'--port',str(peer[1]),'--case',case],2)
            h.require(result['exit_code']==0 and json.loads(result['stdout'])['ok'],f'fault {case}: {result}')
        evidence['cases'].append('13_native_fault_cases')

    # Independent peer supplies a wrong nonce, a delayed old PONG, or an oversized reply.
    for fault in ['ack_nonce','old_pong','oversize']:
        with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as responder:
            responder.bind(('127.0.0.1',0));responder.settimeout(2)
            failures=[]
            def reply():
                try:
                    data,client=responder.recvfrom(4096)
                    nonce=data[60:76] if fault!='ack_nonce' else b'z'*16
                    responder.sendto(h.packet(2,struct.pack('<II16s16s16s',1,0,b's'*16,b't'*16,nonce)),client)
                    if fault=='ack_nonce': return
                    ping,client=responder.recvfrom(4096)
                    pong=h.packet(0x11,struct.pack('<Q16sI',struct.unpack_from('<Q',ping,48)[0],ping[32:48],0))
                    if fault=='oversize': responder.sendto(pong+bytes(500),client);return
                    responder.sendto(pong,client)
                    responder.recvfrom(4096) # second PING: answer with the first packet
                    responder.sendto(pong,client)
                except Exception as error: failures.append(str(error))
            thread=threading.Thread(target=reply);thread.start()
            result=h.build_checks.run([str(build/'lab_client'),'--port',str(responder.getsockname()[1]),'--count','2','--timeout-ms','200'],3)
            thread.join(3)
            h.require(not thread.is_alive() and not failures and result['exit_code']==1 and json.loads(result['stdout'])['ok'] is False,f'client {fault} accepted unrelated reply: {result} {failures}')
    evidence['cases'].append('native_client_rejects_wrong_ack_late_pong_and_oversize')
