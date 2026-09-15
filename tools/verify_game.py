#!/usr/bin/env python3
"""Real Godot processes on loopback; never physical LAN/TPM or human gameplay evidence."""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import time
from run_game import ROOT, engine


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--graphical', action='store_true')
    args = parser.parse_args()
    (ROOT/'results').mkdir(exist_ok=True)
    report = {'scope': 'Godot loopback processes; optional real rendering; no physical LAN, TPM or human gameplay', 'passed': False, 'cases': []}
    children = []
    with tempfile.TemporaryDirectory(prefix='arena-network-') as tmp:
        env = dict(os.environ, XDG_DATA_HOME=tmp, XDG_CONFIG_HOME=tmp, XDG_CACHE_HOME=tmp)
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.bind(('127.0.0.1', 0))
            port = probe.getsockname()[1]
        graphical = args.graphical
        def start(label, args):
            path = Path(tmp) / (label+'.log')
            stream = path.open('w+')
            render = ['--max-fps', '60', '--resolution', '1920x1080', '--fullscreen'] if label in ('alice', 'bob') and graphical else ['--headless']
            process = subprocess.Popen([engine(), "--verbose", *render, '--path', str(ROOT/'game'), '--', *args],
                                       stdout=stream, stderr=subprocess.STDOUT, env=env)
            children.append((process, stream, path))
            return process, path
        try:
            closed, path = start('protected', ['--server', '--port', str(port)])
            assert closed.wait(timeout=5) == 2, path.read_text()
            report['cases'].append('protected_server_fails_closed_without_verifier')
            server, path = start('server', ['--server', '--development', '--port', str(port)])
            deadline = time.monotonic()+8
            while 'server_ready' not in path.read_text():
                assert server.poll() is None and time.monotonic() < deadline, path.read_text()
                time.sleep(.05)
            report['cases'].append('dedicated_server_started')
            a, ap = start('alice', ['--join', '127.0.0.1', '--port', str(port), '--name', 'Alice', '--automated', '--seconds', '18', '--lab', '--snap-cycle', *(['--screenshot', str(ROOT/'results/fps-match.png'), '--alert-screenshot', str(ROOT/'results/fps-alert.png')] if graphical else [])])
            b, bp = start('bob', ['--join', '127.0.0.1', '--port', str(port), '--name', 'Bob', '--automated', '--seconds', '22', '--lab', '--snap-cycle'])
            assert a.wait(timeout=28) == 0, ap.read_text()
            first = next(json.loads(x) for x in ap.read_text().splitlines() if x.startswith('{"event":"automated_exit"'))
            assert first['players'] == 2 and first['snapshots'] == 2, first
            report['cases'].append('two_clients_lobby_ready_match_and_snapshots')
            assert server.poll() is None
            assert b.wait(timeout=12) == 0, bp.read_text()
            second = next(json.loads(x) for x in bp.read_text().splitlines() if x.startswith('{"event":"automated_exit"'))
            assert second['players'] == 1 and second['snapshots'] == 1, second
            report['cases'].append('client_disconnect_other_player_and_server_continue')
            report['client_states'] = [first.get('own_state'), second.get('own_state')]
            assert first['own_state']['kills']+first['own_state']['deaths'] > 0, first
            report['cases'].append('server_shooting_damage_death_and_score')
            assert 'ANTICHEAT · Suspicious aim behaviour:' in ap.read_text(), ap.read_text()
            assert 'ANTICHEAT · Suspicious aim behaviour:' in bp.read_text(), bp.read_text()
            report['cases'].append('behavioral_alert_received_by_both_clients')
            assert server.poll() is None
            for _, _, path in children:
                assert 'ERROR:' not in path.read_text() and 'were leaked' not in path.read_text(), path.read_text()
            report['graphical'] = graphical
            report['passed'] = True
        finally:
            for process, stream, path in children:
                if process.poll() is None:
                    process.terminate()
                    try: process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=3)
                stream.close()
                target = ROOT/'results'/('fps-'+path.name)
                target.parent.mkdir(exist_ok=True)
                target.write_text(path.read_text())
            for record in Path(tmp).rglob('*.jsonl'):
                (ROOT/'results'/record.name).write_bytes(record.read_bytes())
            (ROOT/'results/fps-network.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
