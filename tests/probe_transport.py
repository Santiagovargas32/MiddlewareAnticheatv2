"""Independent regression probes for the live UDP server."""
import importlib.util
from pathlib import Path
import socket
import struct

spec = importlib.util.spec_from_file_location('integration', Path(__file__).resolve().parents[1] / 'scripts/verificar-integracion.py')
h = importlib.util.module_from_spec(spec)
spec.loader.exec_module(h)


def probe(binary, directory):
    results = {}
    evidence = {'servers': []}
    with h.server(binary, directory, evidence) as peer:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
            client.settimeout(1)
            nonce = b'\0' + b'a' * 15
            response = h.exchange(client, peer, h.hello(nonce))
            results['nonce_with_zero'] = response[2] == 2
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
            client.settimeout(1)
            session = h.open_session(client, peer, b'b' * 16)
            ping = h.packet(0x10, struct.pack('<16s16sQ', session, b'c' * 16, 42), 1)
            h.exchange(client, peer, ping)
            response = h.exchange(client, peer, ping)
            results['immediate_replay'] = response[2] == 0x20 and struct.unpack_from('<I', response, 32)[0] == 10
            wrong = ping[:8] + struct.pack('<I', 39) + ping[12:]
            response = h.exchange(client, peer, wrong)
            results['declared_length'] = response[2] == 0x20 and struct.unpack_from('<I', response, 32)[0] == 4
    return results
