"""Two pinned TLS players and one authoritative C worker; loopback lab only.

Profile server_rules_v1 has no TPM requirement. Slots are single-use per match;
a disconnect ends that slot. No automatic restart or old-session resurrection.
"""
import asyncio
import hashlib
from pathlib import Path
import ssl
import struct
from bridge_transport import encode_frame, read_frame, tls_context

RESULTS = ('ACCEPTED', 'BAD_INPUT', 'WRONG_MATCH', 'WRONG_SESSION', 'SESSION_CLOSED',
           'PLAYER_DEAD', 'SEQUENCE_REPLAY', 'SEQUENCE_EXHAUSTED', 'TICK_ALREADY_USED',
           'FIRE_COOLDOWN', 'NO_AMMO', 'OUTSIDE_ARENA', 'POSITION_OCCUPIED', 'SERVER_TICK_EXHAUSTED')
ERRORS = {1: 'IDENTITY_NOT_ENROLLED', 2: 'PLAYER_CONNECTED', 3: 'SESSION_CLOSED',
          4: 'WORKER_UNAVAILABLE', 5: 'BAD_FRAME', 6: 'SESSION_LIMIT', 7: 'MATCH_INACTIVE'}


def fingerprint(path):
    data = Path(path).read_text()
    if len(data) > 8192:
        raise ValueError('CERTIFICATE_SIZE')
    return hashlib.sha256(ssl.PEM_cert_to_DER_cert(data)).digest()


def state(data):
    if len(data) == 5 and data[:4] == b'LGRE' and data[4] in ERRORS:
        raise ValueError(ERRORS[data[4]])
    if (len(data) != 80 or data[:5] != b'LGST\x01' or data[5] >= len(RESULTS)
            or data[6] > 1 or data[7] != 1 or data[76] > 3 or any(data[77:])):
        raise ValueError('STATE_SCHEMA')
    players = []
    for slot in range(2):
        x, y, hp, ammo, hits, kills = struct.unpack_from('<iiBBBB', data, 52 + slot * 12)
        if not (-10000 <= x <= 10000 and -10000 <= y <= 10000 and hp <= 100
                and ammo <= 4 and hits <= 4 and kills <= 1):
            raise ValueError('STATE_RANGE')
        players.append(dict(x_mm=x, y_mm=y, health=hp, ammo=ammo, hits=hits,
                            kills=kills, open=bool(data[76] & (1 << slot))))
    if not any(data[20:36]) or not any(data[36:52]):
        raise ValueError('STATE_IDENTITY')
    return dict(tick=struct.unpack_from('<Q', data, 8)[0], sequence=struct.unpack_from('<I', data, 16)[0],
                player=data[6], reason=RESULTS[data[5]], profile='server_rules_v1', players=players)


def command(hello, sequence, action):
    state(hello)
    directions = {'east': (1, 2, 0), 'west': (1, 1, 0), 'north': (1, 0, 2),
                  'south': (1, 0, 1), 'fire': (2, 0, 0), 'wait': (3, 0, 0)}
    if action not in directions or not 0 < sequence < 0xffffffff:
        raise ValueError('INPUT_ARGUMENT')
    kind, x, y = directions[action]
    return b'LGIN' + bytes((1, kind, x, y)) + hello[20:52] + struct.pack('<I', sequence) + bytes(4)


async def close_writer(writer):
    writer.close()
    try:
        await asyncio.wait_for(writer.wait_closed(), 1)
    except (OSError, asyncio.TimeoutError):
        pass


class GameService:
    def __init__(self, binary, player_certificates):
        identities = [fingerprint(path) for path in player_certificates]
        if len(identities) != 2 or len(set(identities)) != 2:
            raise ValueError('TWO_DISTINCT_PLAYER_CERTIFICATES_REQUIRED')
        self.identities = dict(zip(identities, range(2)))
        self.binary = str(Path(binary).resolve())
        self.process = None
        self.lock = asyncio.Lock()
        self.tasks = set()
        self.claimed = [False, False]
        self.connected = [False, False]
        self.broken = False
        self.started = 0

    async def start(self):
        if self.process is not None:
            raise RuntimeError('SERVICE_ALREADY_STARTED')
        self.process = await asyncio.create_subprocess_exec(
            self.binary, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE, limit=4096)
        try:
            data = await asyncio.wait_for(self.process.stdout.readexactly(160), 2)
            a, b = state(data[:80]), state(data[80:])
            if (a['player'] != 0 or b['player'] != 1 or a['reason'] != 'ACCEPTED'
                    or b['reason'] != 'ACCEPTED' or data[20:36] != data[100:116]
                    or data[36:52] == data[116:132]):
                raise ValueError('WORKER_HELLO')
            self.started = asyncio.get_running_loop().time()
        except BaseException:
            await self.close()
            raise

    async def exchange(self, op, slot, payload=bytes(48)):
        # Serialize command/reply association. A timeout poisons the entire worker.
        if self.broken or self.process is None or self.process.returncode is not None:
            raise RuntimeError('WORKER_UNAVAILABLE')
        if op not in (1, 2, 3, 4) or slot not in (0, 1) or len(payload) != 48:
            raise ValueError('PRIVATE_COMMAND')
        self.process.stdin.write(bytes((op, slot)) + payload)
        try:
            await asyncio.wait_for(self.process.stdin.drain(), 2)
            result = await asyncio.wait_for(self.process.stdout.readexactly(80), 2)
            value = state(result)
            if value['player'] != slot:
                raise ValueError('WORKER_REPLY_ASSOCIATION')
            return result
        except BaseException:
            self.broken = True
            raise

    async def snapshot(self, slot):
        async with self.lock:
            return await self.exchange(4, slot)

    async def apply(self, slot, payload):
        async with self.lock:
            tick = int((asyncio.get_running_loop().time() - self.started) / 0.05)
            if not 0 <= tick <= 0xffffffffffffffff:
                raise RuntimeError('SERVER_CLOCK_EXHAUSTED')
            await self.exchange(2, slot, struct.pack('<Q', tick) + bytes(40))
            return await self.exchange(1, slot, payload)

    async def send(self, writer, data):
        writer.write(encode_frame(data))
        await asyncio.wait_for(writer.drain(), 2)

    async def handle(self, reader, writer):
        task = asyncio.current_task()
        if len(self.tasks) >= 4:
            await close_writer(writer)
            return
        self.tasks.add(task)
        slot = None
        owned = False
        try:
            peer = writer.get_extra_info('ssl_object')
            cert = peer.getpeercert(binary_form=True) if peer else None
            slot = self.identities.get(hashlib.sha256(cert).digest()) if cert else None
            if slot is None:
                await self.send(writer, b'LGRE\x01')
                return
            if self.broken:
                await self.send(writer, b'LGRE\x04')
                return
            if self.claimed[slot]:
                snapshot = state(await self.snapshot(slot))
                await self.send(writer, b'LGRE' + bytes((2 if snapshot['players'][slot]['open'] else 3,)))
                return
            # No await between checking and claiming the certificate's slot.
            self.claimed[slot] = True
            owned = True
            self.connected[slot] = True
            hello = await self.snapshot(slot)
            await self.send(writer, hello)
            deadline = asyncio.get_running_loop().time() + 30
            for _ in range(256):
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    break
                data = await read_frame(reader, min(2, remaining))
                if len(data) != 48:
                    await self.send(writer, b'LGRE\x05')
                    return
                if not all(self.connected):
                    await self.send(writer, b'LGRE\x07')
                    continue
                result = await self.apply(slot, data)
                await self.send(writer, result)
            else:
                await self.send(writer, b'LGRE\x06')
        except (OSError, ValueError, RuntimeError, asyncio.TimeoutError, asyncio.IncompleteReadError):
            pass
        finally:
            try:
                if owned:
                    self.connected[slot] = False
                if owned and not self.broken:
                    try:
                        async with self.lock:
                            await self.exchange(3, slot)
                    except (OSError, ValueError, RuntimeError, asyncio.TimeoutError, asyncio.IncompleteReadError):
                        self.broken = True
                await close_writer(writer)
            finally:
                # Cancellation may arrive while the TLS shutdown is awaiting EOF.
                # Synchronous close and task removal must still run in that case.
                writer.close()
                self.tasks.discard(task)

    async def close(self):
        self.broken = True
        tasks = list(self.tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if self.process is not None and self.process.returncode is None:
            try:
                self.process.terminate()
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(self.process.wait(), 2)
            except asyncio.TimeoutError:
                self.process.kill()
                await asyncio.wait_for(self.process.wait(), 2)
        if self.process is not None:
            await asyncio.wait_for(self.process.stderr.read(4096), 1)
