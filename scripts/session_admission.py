"""arena-admission/1: operator-pinned AK permissions bound to game connections.

This service does not yet gate Godot ENet traffic. ALLOW is a scoped verifier
decision, not evidence of genuine TPM hardware or of a cheat-free host.
"""
import argparse
import asyncio
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import secrets
import signal
import ssl
import threading
import time

import tpm_attestation as attest

PROTOCOL = 'arena-admission/1'


def hex_value(value, length):
    if not isinstance(value, str) or len(value) != length or any(
            c not in '0123456789abcdef' for c in value):
        raise ValueError('INVALID_IDENTIFIER')
    return value


def fingerprint(path):
    return hashlib.sha256(ssl.PEM_cert_to_DER_cert(Path(path).read_text())).hexdigest()


def bound_nonce(binding, salt):
    """Canonical binding and independent random salt, carried inside lab-attest/1."""
    payload = json.dumps(binding, sort_keys=True, separators=(',', ':')).encode('ascii')
    return hashlib.sha256(PROTOCOL.encode('ascii') + b'\0' + payload + b'\0' +
                          bytes.fromhex(hex_value(salt, 64))).hexdigest()


class BoundChallenge(attest.AttestationServer):
    def __init__(self, verifier, binding, ttl_ms, clock):
        super().__init__(verifier, ttl_ms=ttl_ms, maximum=1, clock=clock)
        self.binding = dict(binding)
        self.salt = secrets.token_hex(32)

    def _issue(self, owner):
        challenge = super()._issue(owner)
        challenge['nonce'] = bound_nonce(self.binding, self.salt)
        self.sessions[challenge['session_id']]['challenge'] = dict(challenge)
        return challenge


@dataclass
class Entry:
    binding: dict
    deadline: float
    state: str = 'REGISTERED'
    lease_deadline: float = 0
    challenge_deadline: float = 0
    verifier: object = None


class AdmissionRegistry:
    def __init__(self, controllers, attestors, *, maximum=256, binding_ms=300000,
                 challenge_ms=10000, lease_ms=30000, clock=time.monotonic):
        for identity in (*controllers, *attestors):
            hex_value(identity, 64)
        if not controllers or not attestors or set(controllers) & set(attestors):
            raise ValueError('INVALID_ROLES')
        for value, upper in ((maximum, 4096), (binding_ms, 3600000),
                             (challenge_ms, 60000), (lease_ms, 60000)):
            if type(value) is not int or not 1 <= value <= upper:
                raise ValueError('INVALID_LIMIT')
        self.controllers = frozenset(controllers)
        self.attestors = dict(attestors)
        self.maximum = maximum
        self.binding_ms = binding_ms
        self.challenge_ms = challenge_ms
        self.lease_ms = lease_ms
        self.clock = clock
        self.instance_id = secrets.token_hex(16)
        self.entries = {}
        self.lock = threading.RLock()

    def _status(self, entry):
        now = self.clock()
        if entry.state != 'REVOKED' and now >= entry.deadline:
            entry.state = 'EXPIRED'
        if entry.state == 'ALLOWED' and now >= entry.lease_deadline:
            entry.state = 'EXPIRED'
        remaining = min(entry.deadline, entry.lease_deadline) - now
        return dict(protocol_version=PROTOCOL, binding=dict(entry.binding), state=entry.state,
                    allow=entry.state == 'ALLOWED',
                    remaining_ms=max(0, int(remaining * 1000)) if entry.state == 'ALLOWED' else 0,
                    provenance='operator_pinned_ak_lab')

    def dispatch(self, identity, message):
        if not isinstance(message, dict) or message.get('protocol_version') != PROTOCOL:
            raise ValueError('INVALID_SCHEMA')
        operation = message.get('operation')
        fields = {'register': {'game_session_id', 'peer_id', 'attestor'},
                  'status': {'admission_id'}, 'revoke': {'admission_id'},
                  'challenge': {'admission_id'}, 'submit': {'admission_id', 'evidence'}}
        if not isinstance(operation, str) or operation not in fields or set(message) != (
                {'protocol_version', 'operation'} | fields[operation]):
            raise ValueError('INVALID_SCHEMA')
        controller = operation in ('register', 'status', 'revoke')
        if identity not in (self.controllers if controller else self.attestors):
            raise ValueError('UNAUTHORIZED_ROLE')
        with self.lock:
            if operation == 'register':
                return self._register(identity, message)
            admission_id = hex_value(message['admission_id'], 32)
            entry = self.entries.get(admission_id)
            if entry is None or identity != entry.binding['controller' if controller else 'attestor']:
                raise ValueError('UNKNOWN_ADMISSION')
            if operation == 'status':
                return self._status(entry)
            if operation == 'revoke':
                entry.state = 'REVOKED'
                return self._status(entry)
            if entry.state == 'REVOKED' or self.clock() >= entry.deadline:
                raise ValueError('ADMISSION_CLOSED')
            if operation == 'challenge':
                if entry.state == 'VERIFYING' or (entry.state == 'CHALLENGED' and
                                                 self.clock() < entry.challenge_deadline):
                    raise ValueError('CHALLENGE_PENDING')
                verifier = BoundChallenge(self.attestors[identity], entry.binding,
                                          self.challenge_ms, self.clock)
                challenge = verifier.issue(identity)
                entry.verifier = verifier
                entry.state = 'CHALLENGED'  # Renewal suspends the old lease.
                entry.challenge_deadline = self.clock() + self.challenge_ms / 1000
                return dict(protocol_version=PROTOCOL, binding=dict(entry.binding),
                            salt=verifier.salt, challenge=challenge)
            if entry.state != 'CHALLENGED':
                raise ValueError('NO_PENDING_CHALLENGE')
            evidence = message['evidence']
            if not isinstance(evidence, dict):
                raise ValueError('INVALID_SCHEMA')
            entry.state = 'VERIFYING'
            verifier = entry.verifier
        # Never hold the registry lock while running external cryptographic tools.
        # Revoke/status remain available; a completion cannot restore a revoked entry.
        try:
            result = verifier.submit(identity, evidence)
        except Exception:
            with self.lock:
                if entry.state == 'VERIFYING':
                    entry.state = 'DENIED'
            raise
        with self.lock:
            if self.entries.get(admission_id) is not entry or entry.state != 'VERIFYING':
                raise ValueError('ADMISSION_CLOSED')
            entry.state = 'ALLOWED' if result['decision'] == 'ALLOW' else 'DENIED'
            # A lease starts at challenge issue, never at a delayed verification finish.
            issued = entry.challenge_deadline - self.challenge_ms / 1000
            entry.lease_deadline = min(entry.deadline, issued + self.lease_ms / 1000)
            return dict(self._status(entry), attestation=result)

    def _register(self, identity, message):
        session = hex_value(message['game_session_id'], 32)
        attestor = hex_value(message['attestor'], 64)
        peer = message['peer_id']
        if type(peer) is not int or not 2 <= peer <= 2147483647:
            raise ValueError('INVALID_PEER')
        if attestor not in self.attestors:
            raise ValueError('UNKNOWN_ATTESTOR')
        now = self.clock()
        self.entries = {key: entry for key, entry in self.entries.items()
                        if now < entry.deadline and entry.state != 'REVOKED'}
        if any(entry.binding['controller'] == identity and
               entry.binding['game_session_id'] == session and entry.binding['peer_id'] == peer
               for entry in self.entries.values()):
            raise ValueError('PEER_ALREADY_REGISTERED')
        if len(self.entries) >= self.maximum:
            raise ValueError('ADMISSION_LIMIT')
        admission_id = secrets.token_hex(16)
        if admission_id in self.entries:
            raise ValueError('ENTROPY_COLLISION')
        binding = dict(instance_id=self.instance_id, admission_id=admission_id,
                       game_session_id=session, peer_id=peer, connection_id=secrets.token_hex(32),
                       controller=identity, attestor=attestor)
        entry = Entry(binding, now + self.binding_ms / 1000)
        self.entries[admission_id] = entry
        return self._status(entry)


class AdmissionService:
    """One request per mTLS connection; bounded handlers and verification workers."""
    def __init__(self, registry):
        self.registry = registry
        self.tasks = set()
        self.closing = False
        self.verifications = 0

    async def handle(self, reader, writer):
        task = asyncio.current_task()
        accepted = not self.closing and len(self.tasks) < 8
        if accepted:
            self.tasks.add(task)
        try:
            if not accepted:
                return
            certificate = writer.get_extra_info('ssl_object').getpeercert(binary_form=True)
            identity = hashlib.sha256(certificate).hexdigest()
            message = await attest.receive(reader)
            try:
                if message.get('operation') == 'submit':
                    # At most four costly requests; reserve capacity for revoke/status.
                    if self.verifications >= 4:
                        raise ValueError('VERIFIER_BUSY')
                    self.verifications += 1
                    try:
                        result = await asyncio.to_thread(self.registry.dispatch, identity, message)
                    finally:
                        self.verifications -= 1
                else:
                    result = self.registry.dispatch(identity, message)
            except ValueError as error:
                result = dict(protocol_version=PROTOCOL, allow=False, error=str(error))
            writer.write(attest.encode(result))
            await asyncio.wait_for(writer.drain(), 4)
        except (OSError, ValueError, asyncio.TimeoutError, asyncio.IncompleteReadError):
            pass
        finally:
            writer.close()
            try:
                await asyncio.wait_for(writer.wait_closed(), 1)
            except (OSError, asyncio.TimeoutError):
                pass
            self.tasks.discard(task)

    async def close(self):
        self.closing = True
        # Do not cancel to_thread: await owned work so it cannot restore state later.
        await asyncio.gather(*list(self.tasks), return_exceptions=True)


def load_registry(path, inspector):
    path = Path(path).resolve()
    with path.open('rb') as source:
        value = attest.decode(source.read(attest.MAX_FRAME + 1))
    if set(value) != {'controllers', 'attestors'} or not isinstance(value['controllers'], list) or not isinstance(value['attestors'], dict):
        raise ValueError('INVALID_CONFIG')
    verifiers = {}
    for identity, config in value['attestors'].items():
        if not isinstance(config, dict) or set(config) not in ({'ak_public'}, {'ak_public', 'pcr_policy'}):
            raise ValueError('INVALID_CONFIG')
        if any(not isinstance(filename, str) or not filename for filename in config.values()):
            raise ValueError('INVALID_CONFIG')
        verifiers[identity] = attest.QuoteVerifier(path.parent / config['ak_public'], inspector,
            path.parent / config['pcr_policy'] if 'pcr_policy' in config else None)
    return AdmissionRegistry(value['controllers'], verifiers)


async def exchange(host, port, context, server_name, message):
    reader, writer = await asyncio.wait_for(asyncio.open_connection(
        host, port, ssl=context, server_hostname=server_name,
        ssl_handshake_timeout=3, ssl_shutdown_timeout=1), 4)
    try:
        writer.write(attest.encode(message))
        await asyncio.wait_for(writer.drain(), 4)
        return await attest.receive(reader, timeout=12)
    finally:
        writer.close()
        try:
            await asyncio.wait_for(writer.wait_closed(), 1)
        except (OSError, asyncio.TimeoutError):
            pass


async def run(args):
    context = attest.tls_context(args.cert, args.key, args.ca, server=args.config is not None)
    if args.request:
        with args.request.open('rb') as source:
            message = attest.decode(source.read(attest.MAX_FRAME + 1))
        result = await exchange(args.host, args.port, context, args.server_name, message)
        print(json.dumps(result))
        return 1 if 'error' in result else 0
    service = AdmissionService(load_registry(args.config, args.inspector))
    server = await asyncio.start_server(service.handle, args.host, args.port, ssl=context,
                                       ssl_handshake_timeout=3, ssl_shutdown_timeout=1)
    print(json.dumps(dict(event='boot', protocol_version=PROTOCOL,
                          instance_id=service.registry.instance_id,
                          port=server.sockets[0].getsockname()[1])), flush=True)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    try:
        async with server:
            await stop.wait()
    finally:
        await service.close()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.remove_signal_handler(sig)
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--config', type=Path, help='Operator roles and pinned public AKs')
    mode.add_argument('--request', type=Path, help='Send one JSON request over mTLS')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=9445)
    parser.add_argument('--server-name', default='localhost', help='TLS SAN to verify')
    parser.add_argument('--inspector', type=Path, default=Path('build-tpm/lab_quote_inspect'))
    for name in ('cert', 'key', 'ca'):
        parser.add_argument('--' + name, required=True, type=Path)
    args = parser.parse_args()
    if not (0 if args.config else 1) <= args.port <= 65535:
        parser.error('port must be between 1 and 65535 (0 also allowed for a server)')
    try:
        return asyncio.run(run(args))
    except (OSError, ValueError, asyncio.TimeoutError) as error:
        parser.exit(1, f'admission: {error}\n')


if __name__ == '__main__':
    raise SystemExit(main())
