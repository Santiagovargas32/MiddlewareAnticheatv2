"""Isolated routes, bounded faults, restart and queued stale traffic."""
from contextlib import ExitStack
import json
import socket
import struct
import time


def cases(h, build, directory, evidence):
    # The common functional suite already ran through the relay. Here control each hop.
    evidence['via_adapter'] = False
    try:
        with h.server(build/'lab_server', directory, evidence, timeout_ms=2000) as upstream:
            for options, case in [(['--drop-every','2'], 'loss_hello_retry'),
                                  (['--delay-ms','100'], 'bounded_delay'),
                                  (['--replay-last'], 'duplicate_ping')]:
                with h.adapter(build/'lab_adapter', directory, evidence, upstream, options) as peer:
                    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as c:
                        c.settimeout(0.15 if case == 'loss_hello_retry' else 1)
                        request = h.hello(case.encode().ljust(16,b'x')[:16])
                        if case == 'loss_hello_retry':
                            c.sendto(request, peer)
                            try: c.recvfrom(4096); raise RuntimeError('drop mode did not drop')
                            except socket.timeout: pass
                        start = time.monotonic()
                        ack = h.exchange(c, peer, request)
                        h.require(len(ack) == 72 and ack[2] == 2, case)
                        if case == 'bounded_delay': h.require(time.monotonic() - start >= 0.09, 'missing delay')
                        if case == 'duplicate_ping':
                            h.ping_session(c, peer, ack[24:40], 1)
                            response, sender = c.recvfrom(4096)
                            h.require(sender == peer, 'unexpected response peer')
                            h.expect_rst(response, 10, b'REPLAY', session=ack[24:40])
                            h.ping_session(c, peer, ack[24:40], 2)
                evidence['cases'].append(case)
            with h.adapter(build/'lab_adapter',directory,evidence,upstream,['--max-clients','1']) as peer:
                for iteration in range(40):
                    with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as c:
                        c.settimeout(1)
                        session=h.open_session(c,peer,bytes([iteration+1])*16)
                        h.ping_session(c,peer,session,1)
                        kind=0x30 if iteration%2==0 else 0x20
                        h.expect_rst(h.exchange(c,peer,h.close_packet(kind,session)),0,b'bye' if kind==0x30 else b'rst',session=session)
                evidence['cases'].append('40_immediate_route_reuses_after_confirmed_close')
            with h.adapter(build/'lab_adapter', directory, evidence, upstream, ['--max-clients','1','--idle-ms','150']) as peer:
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as a, socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as b:
                    a.settimeout(1); b.settimeout(1)
                    h.open_session(a, peer, b'A'*16)
                    h.expect_rst(h.exchange(b,peer,h.hello(b'B'*16)),14,b'adapter full')
                    time.sleep(0.3)
                    h.open_session(b,peer,b'B'*16)
                evidence['cases'].append('route_saturation_and_idle_reuse')
            with h.adapter(build/'lab_adapter', directory, evidence, upstream, ['--delay-ms','500']) as peer:
                with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as c:
                    c.settimeout(1)
                    for _ in range(40): c.sendto(h.hello(b'Q'*16),peer)
                    response,sender=c.recvfrom(4096)
                    h.require(sender==peer,'queue response peer')
                    h.expect_rst(response,14,b'adapter queue full')
                evidence['cases'].append('bounded_queue_saturation')
            # Stop a relay with a queued PING, then reuse its listen endpoint.
            with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as c:
                c.settimeout(1)
                with h.adapter(build/'lab_adapter',directory,evidence,upstream,['--delay-ms','150']) as old_peer:
                    old_session=h.open_session(c,old_peer,b'L'*16)
                    c.sendto(h.packet(0x10,struct.pack('<16s16sQ',old_session,b'n'*16,1),1),old_peer)
                with h.adapter(build/'lab_adapter',directory,evidence,upstream,port=old_peer[1]) as peer:
                    fresh=h.open_session(c,peer,b'M'*16)
                    h.ping_session(c,peer,fresh,1)
                    c.settimeout(0.3)
                    try: c.recvfrom(4096);raise RuntimeError('queued response crossed relay restart')
                    except socket.timeout: pass
                evidence['cases'].append('queued_old_request_discarded_on_restart')
            with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as c:
                c.settimeout(1)
                with h.adapter(build/'lab_adapter',directory,evidence,upstream) as old_peer:
                    session=h.open_session(c,old_peer,b'R'*16)
                    h.ping_session(c,old_peer,session,1)
                with h.adapter(build/'lab_adapter',directory,evidence,upstream,port=old_peer[1]) as peer:
                    old_ping=h.packet(0x10,struct.pack('<16s16sQ',session,b'n'*16,1),2)
                    h.expect_rst(h.exchange(c,peer,old_ping),3,b'HELLO primero',session=bytes(16))
                    fresh=h.open_session(c,peer,b'S'*16)
                    h.require(fresh!=session,'session survived restart')
                    h.ping_session(c,peer,fresh,1)
                evidence['cases'].append('restart_invalidates_session')
            # Native client must terminate after missing HELLO within its deadline.
            with h.adapter(build/'lab_adapter',directory,evidence,upstream,['--drop-every','1']) as peer:
                result=h.build_checks.run([str(build/'lab_client'),'--port',str(peer[1]),'--timeout-ms','100'],2)
                h.require(result['exit_code']==1 and json.loads(result['stdout'])['ok'] is False,'client loss timeout')
                evidence['checks'].append(result)
                evidence['cases'].append('native_client_bounded_loss')
        # The upstream has stopped; a connected UDP socket must report an error.
        with h.adapter(build/'lab_adapter',directory,evidence,upstream) as peer:
            with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as c:
                c.settimeout(1)
                h.expect_rst(h.exchange(c,peer,h.hello(b'U'*16)),16,b'upstream unavailable')
            evidence['cases'].append('upstream_unavailable')
    finally:
        evidence['via_adapter'] = True
