"""MA-012 transport-only codecs and bounded queues; unrelated to the C codecs."""
import asyncio
import json
import re
import struct
import time

TUNNEL = 'arena-enet-tunnel/1'
IPC = 'arena-gateway-ipc/1'
PROFILE = 'verified_pinned_ak/1'  # Intended profile, never an admission decision.
MAX_ID = 2147483647


def fields(value, names):
    if type(value) is not dict or set(value) != set(names):
        raise ValueError('fields')


def integer(value, low=1, high=MAX_ID):
    if type(value) is not int or not low <= value <= high:
        raise ValueError('integer')
    return value


def hex_id(value, size=32):
    if type(value) is not str or re.fullmatch('[0-9a-f]{%d}' % size, value) is None:
        raise ValueError('identifier')
    return value


def strict_json(data):
    if not 1 <= len(data) <= 4096:
        raise ValueError('json_size')

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('duplicate_key')
            result[key] = value
        return result

    def invalid(_value):
        raise ValueError('non_finite')

    try:
        result = json.loads(data.decode('utf-8'), object_pairs_hook=pairs,
                            parse_constant=invalid)
    except (UnicodeError, RecursionError) as error:
        raise ValueError('json_encoding_depth') from error

    def depth(value, level=0):
        if level > 4 or (level >= 4 and isinstance(value, (dict, list))):
            raise ValueError('json_depth')
        if isinstance(value, (dict, list)):
            for item in value.values() if isinstance(value, dict) else value:
                depth(item, level + 1)
        elif isinstance(value, float):
            raise ValueError('integer_fields_only')
    depth(result)
    return result


def json_bytes(value):
    result = json.dumps(value, separators=(',', ':'), sort_keys=True, allow_nan=False).encode()
    strict_json(result)
    return result


def frame(payload, kind=None):
    if not 1 <= len(payload) <= 4096 or kind not in (None, 1, 2):
        raise ValueError('frame')
    body = (bytes([kind]) if kind is not None else b'') + payload
    return struct.pack('!I', len(body)) + body


async def read_frame(reader, tunnel=False, idle=1.0):
    # Idle timeout starts before the first byte; the entire partial frame then
    # has one absolute 200 ms deadline, not a fresh deadline for every fragment.
    first = await asyncio.wait_for(reader.readexactly(1), idle)
    async with asyncio.timeout(.2):
        header = first + await reader.readexactly(3)
        size = struct.unpack('!I', header)[0]
        if not (2 if tunnel else 1) <= size <= (4097 if tunnel else 4096):
            raise ValueError('frame_size')
        data = await reader.readexactly(size)
    if tunnel:
        if data[0] not in (1, 2):
            raise ValueError('frame_type')
        return data[0], data[1:]
    return data


class Sequence:
    def __init__(self):
        self.value = 0

    def next(self):
        self.value = integer(self.value + 1)
        return self.value

    def accept(self, value):
        integer(value)
        if value != self.value + 1:
            raise ValueError('sequence')
        self.value = value


def envelope(run, generation, request, operation, body):
    return dict(protocol_version=IPC, server_run_id=run, gateway_generation=generation,
                request_id=request, operation=operation, body=body)


def validate_envelope(value, run, generation, sequence):
    fields(value, ('protocol_version', 'server_run_id', 'gateway_generation',
                   'request_id', 'operation', 'body'))
    if value['protocol_version'] != IPC or value['server_run_id'] != run or value['gateway_generation'] != generation:
        raise ValueError('ipc_context')
    integer(value['gateway_generation'])
    if type(value['operation']) is not str or type(value['body']) is not dict:
        raise ValueError('ipc_operation')
    sequence.accept(value['request_id'])
    return value['operation'], value['body']


class BoundedQueue:
    def __init__(self, count=64, size=65536, age=.1, clock=time.monotonic):
        self.queue = asyncio.Queue(maxsize=count)
        self.limit = size
        self.bytes = 0
        self.age = age
        self.clock = clock

    def put(self, data):
        if self.bytes + len(data) > self.limit or self.queue.full():
            raise ValueError('queue_full')
        self.queue.put_nowait((self.clock(), data))
        self.bytes += len(data)

    async def get(self):
        at, data = await self.queue.get()
        self.bytes -= len(data)
        if self.clock() - at > self.age:
            raise ValueError('queue_expired')
        return data


class Rate:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.at = clock()
        self.frames = 64.0
        self.bytes = 65536.0

    def take(self, size):
        now = self.clock()
        delta = max(0, now - self.at)
        self.at = now
        self.frames = min(64, self.frames + delta * 512)
        self.bytes = min(65536, self.bytes + delta * 524288)
        if self.frames < 1 or self.bytes < size:
            raise ValueError('rate')
        self.frames -= 1
        self.bytes -= size
