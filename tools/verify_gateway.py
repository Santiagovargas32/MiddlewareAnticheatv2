#!/usr/bin/env python3
"""MA-012: real Godot/auxiliary loopback, temporary TLS keys, no gameplay permission."""
import hashlib
import json
import os
from pathlib import Path
import signal
import secrets
import ssl
import subprocess
import sys
import tempfile
import time

from run_game import ROOT, engine
sys.path.insert(0, str(ROOT/'scripts'))
from game_credentials import certificates


def fingerprint(path):
    return hashlib.sha256(ssl.PEM_cert_to_DER_cert(path.read_text())).hexdigest()


def events(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.startswith('{')]


def assert_loopback_bound(port):
    # Linux socket tables: inspect only the port reported by our own child.
    matches=[]
    for name in ('udp','udp6'):
        path=Path('/proc/net')/name
        if not path.exists(): continue
        for line in path.read_text().splitlines()[1:]:
            address,number=line.split()[1].split(':')
            if int(number,16)==port: matches.append(address)
    assert matches and all(address in ('0100007F','0000000000000000FFFF00000100007F') for address in matches), 'ENet must bind only loopback'


def main():
    children = []
    report = {'passed': False, 'scope': 'transport-only Godot/mTLS loopback; no permission, LAN or hardware TPM'}
    (ROOT/'results').mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='ma012-e2e-') as tmp:
        folder = Path(tmp)
        keys = folder/'keys'
        keys.mkdir(mode=0o700)
        certificates(keys)
        pins = [fingerprint(keys/(name+'.crt')) for name in ('client','client2')]
        session = secrets.token_hex(16)

        def start(name, role, port, seconds, cert, extra=None):
            config = dict(role=role, cert=str(keys/(cert+'.crt')), key=str(keys/(cert+'.key')),
                          ca=str(keys/'ca.crt'), host='127.0.0.1', port=port)
            if role == 'server':
                config.update(attestors=pins, game_port=1, game_session_id=session)
            else:
                config.update(gateway_pin=fingerprint(keys/'server.crt'), server_name='localhost')
            options = dict(configuration=config, python=sys.executable,
                           helper=str(ROOT/'scripts/arena_gateway.py'), run_id=secrets.token_hex(16),
                           seconds=seconds, probe_direct=role=='server')
            if extra:
                options.update(extra)
            config_path = folder/(name+'.json')
            config_path.write_text(json.dumps(options))
            log = folder/(name+'.log')
            stream = log.open('w')
            env = dict(os.environ,XDG_DATA_HOME=str(folder/name),XDG_CONFIG_HOME=str(folder/name),XDG_CACHE_HOME=str(folder/name))
            process = subprocess.Popen([engine(),'--headless','--path',str(ROOT/'game'),
                '--script','tests/gateway_peer.gd','--',str(config_path)], stdout=stream,
                stderr=subprocess.STDOUT,env=env,start_new_session=True)
            children.append((process,stream,log))
            return process,log

        try:
            server, server_log = start('server','server',0,9,'server')
            deadline = time.monotonic()+7
            ready = []
            while not ready:
                assert server.poll() is None and time.monotonic()<deadline, server_log.read_text()
                ready = [item for item in events(server_log) if item['event']=='ready']
                time.sleep(.02)
            port = int(ready[0]['port'])
            first, first_log = start('first','client',port,2.5,'client')
            second, second_log = start('second','client',port,5,'client2')
            for log in (first_log,second_log):
                deadline=time.monotonic()+2
                while not any(item['event']=='client_endpoint' for item in events(log)):
                    assert time.monotonic()<deadline,log.read_text()
                    time.sleep(.02)
                endpoint=next(item for item in events(log) if item['event']=='client_endpoint')
                assert_loopback_bound(int(endpoint['port']))
            assert first.wait(timeout=8)==0, first_log.read_text()
            # A fresh channel after close must bind to a new route/generation.
            third, third_log = start('reconnect','client',port,2.5,'client')
            assert second.wait(timeout=8)==0, second_log.read_text()
            assert third.wait(timeout=8)==0, third_log.read_text()
            assert server.wait(timeout=10)==0, server_log.read_text()
            observed = events(server_log)
            bound = [item for item in observed if item['event']=='bound_peer']
            assert len(bound)==3 and {item['attestor'] for item in bound}==set(pins), observed
            assert len({item['channel'] for item in bound})==3, bound
            assert len({item['generation'] for item in bound})==3, bound
            assert all(item['permission'] is False for item in bound), bound
            assert any(item['event']=='unbound_peer' for item in observed), observed
            metrics = []
            for path in (first_log,second_log,third_log):
                result = next(item for item in events(path) if item['event']=='exit')
                assert not result['failed'] and result['echoes']>=8 and len(result['channels'])==4 and len(result['modes'])==3, result
                samples = sorted(result['rtt_ms'])
                metrics.append(dict(echoes=result['echoes'],frames=result['frames'],
                    rtt_p50_ms=samples[len(samples)//2],rtt_p95_ms=samples[int((len(samples)-1)*.95)],rtt_max_ms=max(samples)))
            fault_cases=[]
            killed_server,killed_log=start('killed-server','server',0,6,'server')
            deadline=time.monotonic()+5
            while not any(item['event']=='ready' for item in events(killed_log)):
                assert killed_server.poll() is None and time.monotonic()<deadline,killed_log.read_text()
                time.sleep(.02)
            killed_port=int(next(item['port'] for item in events(killed_log) if item['event']=='ready'))
            victim,victim_log=start('lost-channel','client',killed_port,4,'client')
            while not any(item['event']=='bound_peer' for item in events(killed_log)):
                assert killed_server.poll() is None and time.monotonic()<deadline,killed_log.read_text()
                time.sleep(.02)
            owned_pid=next(item['pid'] for item in events(killed_log) if item['event']=='child')
            os.kill(owned_pid,signal.SIGKILL)
            assert killed_server.wait(timeout=4)==1,killed_log.read_text()
            assert victim.wait(timeout=4)==1,victim_log.read_text()
            outcome=next(item for item in events(killed_log) if item['event']=='exit')
            assert outcome['failed'] and outcome['routes_remaining']==0,outcome
            fault_cases.append('helper_kill_retires_live_route_and_client')
            fixtures={
                'stderr_pressure':("import sys; sys.stderr.buffer.write(b'x'*196608); sys.stderr.flush()",'child_exit'),
                'partial_ipc':("import sys,time; sys.stdout.buffer.write(b'\\x00'); sys.stdout.flush(); time.sleep(1)",'partial_timeout'),
                'blocked_parent_write':("import time; time.sleep(5)",'ipc_write'),
            }
            for name,(source,reason) in fixtures.items():
                fixture=folder/(name+'.py')
                fixture.write_text(source+'\n')
                process,path=start(name,'server',0,5,'server',dict(helper=str(fixture),probe_direct=False,ipc_burst=name=='blocked_parent_write'))
                assert process.wait(timeout=5)==1,path.read_text()
                result=next(item for item in events(path) if item['event']=='exit')
                assert result['failed'] and result['reason']==reason,result
                assert result['stderr_bytes']<=65536 and result['burst_us']<250000,result
                if name=='stderr_pressure': assert result['stderr_bytes']==65536,result
                fault_cases.append(name)
            for _process,_stream,path in children:
                output = path.read_text()
                assert 'ERROR:' not in output and 'were leaked' not in output, output
                for item in events(path):
                    if item['event']=='child' and item['pid']>0:
                        try:
                            os.kill(item['pid'],0)
                        except ProcessLookupError:
                            continue
                        raise AssertionError('auxiliary still alive after Godot exit')
            report.update(passed=True, cases=['two_tls_identities_real_enet','four_channels_three_delivery_modes',
                'direct_udp_route_rejected','reconnect_new_channel_generation','transport_never_grants_permission',
                'survivor_continues_after_disconnect','owned_children_closed',
                'client_enet_bound_only_loopback',*fault_cases],clients=metrics)
        finally:
            for process,stream,path in children:
                # Each group was created by this harness. Also stop descendants
                # when a failed Godot parent has already exited.
                try:
                    os.killpg(process.pid,signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try: process.wait(timeout=3)
                except subprocess.TimeoutExpired: pass
                try:
                    os.killpg(process.pid,signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait(timeout=3)
                stream.close()
                (ROOT/'results'/('gateway-'+path.name)).write_bytes(path.read_bytes())
            (ROOT/'results/gateway-network.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


if __name__=='__main__':
    main()
