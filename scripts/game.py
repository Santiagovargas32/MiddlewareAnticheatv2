"""Run the loopback game lab with two enrolled TLS clients and C authority."""
import argparse
import asyncio
import json
from pathlib import Path
import signal

from bridge_transport import encode_frame, read_frame, tls_context
from game_service import GameService, state, command, close_writer

ROOT = Path(__file__).resolve().parents[1]


def port(value):
    if not value.isascii() or not value.isdecimal() or not 1 <= int(value) <= 65535:
        raise argparse.ArgumentTypeError('port must be 1..65535')
    return int(value)


async def serve(args):
    context = tls_context(args.cert, args.key, args.ca, True)
    service = GameService(args.binary, [args.player0_cert, args.player1_cert])
    await service.start()
    server = None
    stopped = asyncio.Event()
    loop = asyncio.get_running_loop()
    signals = []
    watchers = []
    try:
        server = await asyncio.start_server(service.handle, '127.0.0.1', args.port,
                                            ssl=context, ssl_handshake_timeout=2, ssl_shutdown_timeout=1)
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, stopped.set)
            signals.append(sig)
        print(json.dumps(dict(event='ready', port=args.port, profile='server_rules_v1',
                              protocol='lab-game-session/1', scope='loopback_lab')), flush=True)
        watchers = [asyncio.create_task(stopped.wait()), asyncio.create_task(service.process.wait())]
        done, _ = await asyncio.wait(watchers, return_when=asyncio.FIRST_COMPLETED)
        if watchers[1] in done:
            raise RuntimeError('GAME_WORKER_EXITED')
    finally:
        for watcher in watchers:
            watcher.cancel()
        await asyncio.gather(*watchers, return_exceptions=True)
        for sig in signals:
            loop.remove_signal_handler(sig)
        if server:
            server.close()
            await server.wait_closed()
        await service.close()


async def client(args):
    actions = args.actions.split(',')
    if not 1 <= len(actions) <= 64 or any(x not in ('east', 'west', 'north', 'south', 'fire', 'wait') for x in actions):
        raise ValueError('ACTIONS_INVALID')
    reader, writer = await asyncio.wait_for(asyncio.open_connection(
        '127.0.0.1', args.port, ssl=tls_context(args.cert, args.key, args.ca),
        server_hostname='localhost', ssl_shutdown_timeout=1), 3)
    try:
        hello = await read_frame(reader)
        print(json.dumps(dict(event='joined', **state(hello))), flush=True)
        for sequence, action in enumerate(actions, 1):
            # A bounded demo pace, not a client-selected simulation timestep.
            await asyncio.sleep(0.25)
            writer.write(encode_frame(command(hello, sequence, action)))
            await asyncio.wait_for(writer.drain(), 2)
            result = await read_frame(reader)
            if result == b'LGRE\x07':
                print(json.dumps(dict(event='decision', reason='MATCH_INACTIVE')), flush=True)
                continue
            value = state(result)
            if (result[20:52] != hello[20:52] or value['player'] != hello[6]
                    or value['sequence'] != sequence):
                raise ValueError('RESPONSE_ASSOCIATION')
            print(json.dumps(dict(event='decision', **value)), flush=True)
    finally:
        await close_writer(writer)


async def graphical_run(args):
    from game_graphics import graphics
    loop = asyncio.get_running_loop()
    task = asyncio.current_task()
    loop.add_signal_handler(signal.SIGTERM, task.cancel)
    try:
        return await graphics(args)
    finally:
        loop.remove_signal_handler(signal.SIGTERM)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_subparsers(dest='mode', required=True)
    serve_parser = modes.add_parser('serve')
    serve_parser.add_argument('--binary', type=Path, default=ROOT / 'build/lab_game_host')
    serve_parser.add_argument('--player0-cert', type=Path, required=True)
    serve_parser.add_argument('--player1-cert', type=Path, required=True)
    client_parser = modes.add_parser('client')
    client_parser.add_argument('--actions', default='wait,wait,east,fire,wait')
    graphics_parser = modes.add_parser('graphics')
    graphics_parser.add_argument('--renderer', type=Path, default=ROOT / 'build-graphics/lab_game_viewer')
    graphics_parser.add_argument('--hidden', action='store_true')
    graphics_parser.add_argument('--scripted', action='store_true')
    graphics_parser.add_argument('--seconds', type=int, choices=range(1, 21), default=20)
    graphics_parser.add_argument('--screenshot', type=Path)
    for sub in (serve_parser, client_parser, graphics_parser):
        sub.add_argument('--port', type=port, default=7780)
        for name in ('cert', 'key', 'ca'):
            sub.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.mode == 'graphics':
            asyncio.run(graphical_run(args))
        else:
            asyncio.run(serve(args) if args.mode == 'serve' else client(args))
    except asyncio.CancelledError:
        return 143
    except (OSError, ValueError, RuntimeError, asyncio.TimeoutError, asyncio.IncompleteReadError) as error:
        print(json.dumps(dict(event='error', reason=str(error))))
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
