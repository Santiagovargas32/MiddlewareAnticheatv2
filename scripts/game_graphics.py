"""Pipe adapter for the C renderer. Forward authenticated states without rewriting."""
import asyncio
import json
from bridge_transport import encode_frame, read_frame, tls_context
from game_service import state, command, close_writer

ACTIONS = {b'n': 'north', b's': 'south', b'e': 'east', b'w': 'west', b'f': 'fire', b'.': 'wait'}


async def graphics(args):
    reader, writer = await asyncio.wait_for(asyncio.open_connection(
        '127.0.0.1', args.port, ssl=tls_context(args.cert, args.key, args.ca),
        server_hostname='localhost', ssl_shutdown_timeout=1), 3)
    process = None
    pump = None
    try:
        hello = await read_frame(reader)
        state(hello)
        arguments = [str(args.renderer), '--seconds', str(args.seconds)]
        if args.hidden:
            arguments.append('--hidden')
        if args.scripted:
            arguments.append('--scripted')
        if args.screenshot:
            arguments.extend(['--screenshot', str(args.screenshot)])
        process = await asyncio.create_subprocess_exec(*arguments, stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, limit=4096)
        latest = asyncio.Queue(maxsize=1)

        async def inputs():
            while True:
                action = await process.stdout.read(1)
                if not action:
                    return
                if action not in ACTIONS:
                    raise ValueError('RENDERER_ACTION_INVALID')
                if latest.full():
                    latest.get_nowait()
                latest.put_nowait(action)

        pump = asyncio.create_task(inputs())
        process.stdin.write(encode_frame(hello))
        await asyncio.wait_for(process.stdin.drain(), 1)
        sequence = 0
        last = state(hello)
        history = {0: last}
        decisions = []
        while True:
            await asyncio.sleep(0.1)
            if pump.done():
                pump.result()
                break
            action = ACTIONS[latest.get_nowait()] if not latest.empty() else 'wait'
            sequence += 1
            if sequence > 256:
                raise RuntimeError('GRAPHICS_SESSION_LIMIT')
            writer.write(encode_frame(command(hello, sequence, action)))
            await asyncio.wait_for(writer.drain(), 2)
            packet = await read_frame(reader, 2)
            if packet != b'LGRE\x07':
                value = state(packet)
                if packet[20:52] != hello[20:52] or value['player'] != hello[6] or value['sequence'] != sequence:
                    raise ValueError('RESPONSE_ASSOCIATION')
                last = value
                history[sequence] = value
                if action != 'wait':
                    decisions.append(dict(action=action, reason=value['reason'], tick=value['tick']))
            if process.returncode is not None or pump.done():
                break
            try:
                process.stdin.write(encode_frame(packet))
                await asyncio.wait_for(process.stdin.drain(), 1)
            except (BrokenPipeError, ConnectionResetError):
                if await asyncio.wait_for(process.wait(), 2) != 0:
                    raise
                break
        code = await asyncio.wait_for(process.wait(), 2)
        errors = (await asyncio.wait_for(process.stderr.read(4096), 1)).decode(errors='replace')
        if code:
            raise RuntimeError('RENDERER_EXIT_' + str(code) + ': ' + errors[-1000:])
        records = [json.loads(line) for line in errors.splitlines() if line.startswith('{')]
        if len(records) != 1 or records[0].get('event') != 'renderer_exit':
            raise RuntimeError('RENDERER_RESULT_MISSING')
        rendered = records[0]
        numeric = {'frames', 'updates', 'player', 'x_mm', 'y_mm', 'health', 'ammo', 'tick', 'sequence'}
        if set(rendered) != numeric | {'event'} or any(type(rendered[k]) is not int for k in numeric):
            raise RuntimeError('RENDERER_RESULT_SCHEMA')
        displayed = history.get(rendered['sequence'])
        if displayed is None or displayed['tick'] != rendered['tick'] or displayed['player'] != rendered['player']:
            raise RuntimeError('RENDERER_STATE_NOT_RECEIVED')
        # A newer response may arrive after the last rendered frame. Compare to the
        # exact authoritative sequence that was displayed, not an unrelated later one.
        result = dict(event='graphics_result', state=displayed, renderer=rendered, actions=decisions)
        print(json.dumps(result), flush=True)
        return result
    finally:
        if pump:
            pump.cancel()
            await asyncio.gather(pump, return_exceptions=True)
        if process and process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), 2)
            except asyncio.TimeoutError:
                process.kill()
                await asyncio.wait_for(process.wait(), 2)
        await close_writer(writer)
