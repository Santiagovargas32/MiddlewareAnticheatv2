"""Authenticated transport for bounded binary lab-udp/2 worker jobs.

No platform translation: the C backend determines its own origin. A job is one
REQUEST datagram, optionally followed by a Linux OBSERVATION datagram in the
same frame. Outputs preserve the Linux datagram and add the native observation.
"""
import asyncio
from contextlib import asynccontextmanager
import ssl
import struct

MAX_FRAME = 256
FRAME_TIMEOUT = 4


def encode_frame(data):
    if not 0 < len(data) <= MAX_FRAME:
        raise ValueError('frame_size')
    return struct.pack('!I',len(data))+data


async def read_frame(reader, timeout=FRAME_TIMEOUT):
    async def read():
        size=struct.unpack('!I',await reader.readexactly(4))[0]
        if not 0 < size <= MAX_FRAME:
            raise ValueError('frame_size')
        return await reader.readexactly(size)
    return await asyncio.wait_for(read(),timeout)


def tls_context(cert,key,ca,server=False):
    context=ssl.create_default_context(ssl.Purpose.CLIENT_AUTH if server else ssl.Purpose.SERVER_AUTH,cafile=str(ca))
    context.minimum_version=ssl.TLSVersion.TLSv1_3
    context.verify_mode=ssl.CERT_REQUIRED
    context.load_cert_chain(str(cert),str(key))
    return context


@asynccontextmanager
async def worker(binary):
    process=await asyncio.create_subprocess_exec(str(binary),'--worker',stdin=asyncio.subprocess.PIPE,
                                               stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
    try:
        hello=await read_frame(process.stdout)
        if len(hello)!=76:
            raise ValueError('worker_hello')
        yield process,hello
    finally:
        if process.returncode is None:
            try: process.terminate()
            except ProcessLookupError: pass
            try: await asyncio.wait_for(process.wait(),2)
            except asyncio.TimeoutError:
                process.kill();await asyncio.wait_for(process.wait(),2)


async def execute(process,command):
    if len(command) not in (60,180):
        raise ValueError('job_size')
    process.stdin.write(encode_frame(command))
    await asyncio.wait_for(process.stdin.drain(),FRAME_TIMEOUT)
    process.stdin.close()
    observations=[await read_frame(process.stdout) for _ in range(2 if len(command)==180 else 1)]
    extra=await asyncio.wait_for(process.stdout.read(1),FRAME_TIMEOUT)
    code=await asyncio.wait_for(process.wait(),FRAME_TIMEOUT)
    if extra or code!=0 or any(len(data)!=120 for data in observations):
        raise ValueError('worker_result')
    return observations


class WorkerService:
    def __init__(self,binary,limit=4):
        self.binary=binary
        self.limit=limit
        self.tasks=set()

    async def handle(self,reader,writer):
        task=asyncio.current_task()
        if len(self.tasks)>=self.limit:
            writer.close()
            return
        self.tasks.add(task)
        try:
            async with worker(self.binary) as (process,hello):
                writer.write(encode_frame(hello));await writer.drain()
                command=await read_frame(reader)
                for data in await execute(process,command):
                    writer.write(encode_frame(data))
                await asyncio.wait_for(writer.drain(),FRAME_TIMEOUT)
        except (OSError,ValueError,asyncio.TimeoutError,asyncio.IncompleteReadError):
            # A closed connection is a failed job, never a successful observation.
            pass
        finally:
            writer.close()
            try: await asyncio.wait_for(writer.wait_closed(),1)
            except (OSError,asyncio.TimeoutError): pass
            self.tasks.discard(task)

    async def close(self):
        pending=list(self.tasks)
        for task in pending: task.cancel()
        await asyncio.gather(*pending,return_exceptions=True)
