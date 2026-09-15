"""Launch two raylib clients and our dedicated TLS/C server; temporary local match."""
import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import signal
import socket
import subprocess
import sys
import tempfile

from game_credentials import certificates

ROOT = Path(__file__).resolve().parents[1]


async def match(args, directory):
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        port = probe.getsockname()[1]
    def tls(name):
        return ['--cert', str(directory / (name + '.crt')), '--key', str(directory / (name + '.key')),
                '--ca', str(directory / 'ca.crt')]
    base = [sys.executable, str(ROOT / 'scripts/game.py')]
    server = await asyncio.create_subprocess_exec(*base, 'serve', '--binary', str(args.build_dir / 'lab_game_host'),
                '--port', str(port), '--player0-cert', str(directory / 'client.crt'),
                '--player1-cert', str(directory / 'client2.crt'), *tls('server'),
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    clients = []
    results = []
    try:
        line = await asyncio.wait_for(server.stdout.readline(), 3)
        if not line or json.loads(line).get('event') != 'ready':
            raise RuntimeError('SERVER_NOT_READY')
        for i, name in enumerate(('client', 'client2')):
            options = ['--seconds', str(args.seconds)]
            if args.hidden:
                options.append('--hidden')
            if args.scripted:
                options.append('--scripted')
            if args.screenshot_dir:
                options.extend(['--screenshot', str(args.screenshot_dir / f'player-{i}.png')])
            child = await asyncio.create_subprocess_exec(*base, 'graphics', '--renderer',
                        str(args.build_dir / 'lab_game_viewer'), '--port', str(port), *options, *tls(name),
                        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            clients.append(child)
        for child in clients:
            output, error = await asyncio.wait_for(child.communicate(), args.seconds + 10)
            if child.returncode:
                raise RuntimeError('GRAPHICAL_CLIENT_FAILED: ' + output.decode(errors='replace')[-1200:] +
                                   error.decode(errors='replace')[-800:])
            events = [json.loads(line) for line in output.splitlines()]
            if len(events) != 1 or events[0].get('event') != 'graphics_result':
                raise RuntimeError('GRAPHICAL_RESULT_INVALID')
            event = events[0]
            view = event['renderer']
            authoritative = event['state']['players'][event['state']['player']]
            if view['frames'] < 1 or view['updates'] < 1 or view['player'] != event['state']['player']:
                raise RuntimeError('NO_RENDERED_AUTHORITY')
            for key in ('x_mm', 'y_mm', 'health', 'ammo'):
                if view[key] != authoritative[key]:
                    raise RuntimeError('VIEW_SERVER_DIVERGENCE')
            results.append(event)
        if args.scripted:
            if (results[0]['renderer']['x_mm'] != 100 or results[1]['renderer']['x_mm'] != 400 or
                    results[0]['renderer']['ammo'] != 3 or results[1]['renderer']['health'] != 75):
                raise RuntimeError('SCRIPTED_FINAL_STATE')
            if not any(x['action'] == 'fire' and x['reason'] == 'ACCEPTED' for x in results[0]['actions']):
                raise RuntimeError('SCRIPTED_SHOT_NOT_ACCEPTED')
        return results
    finally:
        for child in [*clients, server]:
            if child.returncode is None:
                child.terminate()
            try:
                await asyncio.wait_for(child.wait(), 3)
            except asyncio.TimeoutError:
                child.kill()
                await asyncio.wait_for(child.wait(), 2)


async def supervised_match(args, directory):
    loop = asyncio.get_running_loop()
    task = asyncio.current_task()
    loop.add_signal_handler(signal.SIGTERM, task.cancel)
    try:
        return await match(args, directory)
    finally:
        loop.remove_signal_handler(signal.SIGTERM)


def interrupt_setup(_signal, _frame):
    raise KeyboardInterrupt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build-dir', type=Path, default=ROOT / 'build-graphics')
    parser.add_argument('--seconds', type=int, choices=range(1, 21), default=20)
    parser.add_argument('--scripted', action='store_true')
    parser.add_argument('--hidden', action='store_true')
    parser.add_argument('--screenshot-dir', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    args.build_dir = args.build_dir.resolve()
    if args.scripted and args.seconds < 2:
        parser.error('scripted mode requires at least two seconds')
    if args.screenshot_dir:
        args.screenshot_dir = args.screenshot_dir.resolve()
        args.screenshot_dir.mkdir(parents=True, exist_ok=True)
        if any((args.screenshot_dir / f'player-{i}.png').exists() for i in range(2)):
            parser.error('screenshot destination already contains player images')
    report = dict(passed=False, date=datetime.now(timezone.utc).isoformat(),
                  scope='two real raylib windows and TLS/C authority; cardinal prototype, no TPM admission',
                  system=platform.platform(), display=dict(x11=bool(os.getenv('DISPLAY')),
                  wayland=bool(os.getenv('WAYLAND_DISPLAY'))), scripted=args.scripted)
    sources = ['CMakeLists.txt', 'lab/app/game_viewer.c', 'lab/game/view.c', 'lab/game/view.h',
               'scripts/game_graphics.py', 'scripts/game.py', 'scripts/game_credentials.py', 'scripts/jugar.py',
               'lab/game/game.c', 'lab/game/game.h', 'lab/app/game_host.c',
               'scripts/game_service.py', 'scripts/bridge_transport.py', 'scripts/preparar-raylib.py']
    report['raylib'] = dict(version='5.5', distribution='official linux_amd64 binary',
        archive_sha256='3d95ef03d5b38dfa55c0a16ca122d382134b078f0e5b270b52fe7eae0549c000')
    report['source_sha256'] = {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in sources}
    signal.signal(signal.SIGTERM, interrupt_setup)
    try:
        with tempfile.TemporaryDirectory(prefix='lab-graphics-') as temp:
            folder = Path(temp)
            certificates(folder)
            report['players'] = asyncio.run(supervised_match(args, folder))
        report['credentials_removed'] = not folder.exists()
        report['passed'] = True
    except (KeyboardInterrupt, asyncio.CancelledError):
        report['error'] = 'CANCELLED_BY_OPERATOR'
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError, asyncio.TimeoutError) as error:
        report['error'] = str(error) or type(error).__name__
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
