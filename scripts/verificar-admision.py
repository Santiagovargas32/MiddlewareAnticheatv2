"""Admission checks with SOFTWARE signed quotes and real loopback mTLS; no TPM I/O."""
import argparse
import asyncio
from concurrent.futures import ThreadPoolExecutor
import importlib.util
import json
from pathlib import Path
import ssl
import tempfile
import threading
import unittest

import game_credentials
import session_admission as admission
import tpm_attestation as attest

spec = importlib.util.spec_from_file_location('attestation_checks',
    Path(__file__).with_name('verificar-atestacion.py'))
fixtures = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixtures)
INSPECTOR = None


def request(operation, **fields):
    return dict(protocol_version=admission.PROTOCOL, operation=operation, **fields)


class AdmissionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix='admission-checks-')
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.folder = Path(cls.temporary.name)
        game_credentials.certificates(cls.folder)
        fixtures.command(['openssl', 'genrsa', '-out', str(cls.folder / 'private.pem'), '2048'])
        fixtures.command(['openssl', 'pkey', '-in', str(cls.folder / 'private.pem'),
                          '-pubout', '-out', str(cls.folder / 'public.pem')])
        cls.verifier = attest.QuoteVerifier(cls.folder / 'public.pem', INSPECTOR)
        cls.controller = admission.fingerprint(cls.folder / 'client.crt')
        cls.attestor = admission.fingerprint(cls.folder / 'client2.crt')
        cls.unknown = admission.fingerprint(cls.folder / 'unknown.crt')
        cls.other_controller = 'c' * 64
        cls.other_attestor = 'd' * 64

    def setUp(self):
        self.now = [0.0]
        self.registry = admission.AdmissionRegistry(
            [self.controller, self.other_controller],
            {self.attestor: self.verifier, self.other_attestor: self.verifier},
            clock=lambda: self.now[0])

    def register(self, peer=2, registry=None):
        registry = registry or self.registry
        return registry.dispatch(self.controller, request('register',
            game_session_id='a' * 32, peer_id=peer, attestor=self.attestor))['binding']

    def call(self, operation, binding, identity=None, **fields):
        identity = identity or (self.controller if operation in ('status', 'revoke') else self.attestor)
        return self.registry.dispatch(identity, request(operation,
            admission_id=binding['admission_id'], **fields))

    def evidence(self, binding):
        challenge = self.call('challenge', binding)
        self.assertEqual(challenge['binding'], binding)
        self.assertEqual(challenge['challenge']['nonce'],
                         admission.bound_nonce(binding, challenge['salt']))
        return fixtures.fixture(challenge['challenge'], self.folder)

    def test_allow_expiry_and_renewal(self):
        binding = self.register()
        self.assertFalse(self.call('status', binding)['allow'])
        evidence = self.evidence(binding)
        result = self.call('submit', binding, evidence=evidence)
        self.assertTrue(result['allow'], result)
        self.assertEqual(result['remaining_ms'], 30000)
        self.assertEqual(result['attestation']['tpm_identity_validity'], 'not_proven')
        self.now[0] = 30.0
        self.assertEqual(self.call('status', binding)['state'], 'EXPIRED')
        evidence = self.evidence(binding)
        self.assertTrue(self.call('submit', binding, evidence=evidence)['allow'])
        self.evidence(binding)
        self.assertFalse(self.call('status', binding)['allow'])

    def test_roles_and_owner_isolation(self):
        binding = self.register()
        for operation, identity, reason in [('status', self.attestor, 'UNAUTHORIZED_ROLE'),
                ('challenge', self.controller, 'UNAUTHORIZED_ROLE'),
                ('status', self.other_controller, 'UNKNOWN_ADMISSION'),
                ('revoke', self.other_controller, 'UNKNOWN_ADMISSION'),
                ('challenge', self.other_attestor, 'UNKNOWN_ADMISSION'),
                ('challenge', self.unknown, 'UNAUTHORIZED_ROLE')]:
            with self.subTest(operation=operation, identity=identity):
                with self.assertRaisesRegex(ValueError, reason):
                    self.call(operation, binding, identity=identity)
        self.assertEqual(self.call('status', binding)['state'], 'REGISTERED')

    def test_one_use_and_connection_isolation(self):
        first, second = self.register(), self.register(3)
        evidence = self.evidence(first)
        self.evidence(second)
        self.assertFalse(self.call('submit', second, evidence=evidence)['allow'])
        self.assertTrue(self.call('submit', first, evidence=evidence)['allow'])
        with self.assertRaisesRegex(ValueError, 'NO_PENDING_CHALLENGE'):
            self.call('submit', first, evidence=evidence)
        self.assertTrue(self.call('status', first)['allow'])
        self.call('revoke', first)
        replacement = self.register()
        self.assertNotEqual(first['connection_id'], replacement['connection_id'])
        self.evidence(replacement)
        self.assertFalse(self.call('submit', replacement, evidence=evidence)['allow'])

    def test_relabelled_signed_evidence_cannot_move_connections(self):
        first, second = self.register(), self.register(3)
        evidence = self.evidence(first)
        target = self.call('challenge', second)
        evidence['session_id'] = target['challenge']['session_id']
        result = self.call('submit', second, evidence=evidence)
        self.assertFalse(result['allow'])
        self.assertEqual(result['attestation']['cryptographic_validity'], 'verified')
        self.assertEqual(result['attestation']['reasons'], ['NONCE_MISMATCH'])

    def test_binding_changes_nonce(self):
        binding = self.register()
        response = self.call('challenge', binding)
        for field in binding:
            changed = dict(binding)
            changed[field] = 7 if field == 'peer_id' else '0' * len(binding[field])
            self.assertNotEqual(admission.bound_nonce(changed, response['salt']),
                                response['challenge']['nonce'], field)

    def test_timeout_and_late_verification(self):
        binding = self.register()
        evidence = self.evidence(binding)
        self.now[0] = 10
        result = self.call('submit', binding, evidence=evidence)
        self.assertFalse(result['allow'])
        self.assertEqual(result['attestation']['reasons'], ['CHALLENGE_EXPIRED'])
        evidence = self.evidence(binding)
        original = self.registry.entries[binding['admission_id']].verifier.verifier
        class LateVerifier:
            def verify(inner, message, challenge):
                result = original.verify(message, challenge)
                self.now[0] += 11
                return result
        self.registry.entries[binding['admission_id']].verifier.verifier = LateVerifier()
        self.assertFalse(self.call('submit', binding, evidence=evidence)['allow'])
        self.now[0] = 300
        with self.assertRaisesRegex(ValueError, 'ADMISSION_CLOSED'):
            self.evidence(binding)

    def test_bad_signature_and_invalid_schema(self):
        binding = self.register()
        evidence = self.evidence(binding)
        damaged = dict(evidence, signature='AA==')
        self.assertFalse(self.call('submit', binding, evidence=damaged)['allow'])
        for payload in [None, [], {}, request('status', admission_id=[]),
                        request('status', admission_id=binding['admission_id'], allow=True),
                        request(['status']), dict(protocol_version='arena-admission/2')]:
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                self.registry.dispatch(self.controller, payload)
        for peer in (True, 1, -1, 2147483648, '2'):
            with self.assertRaisesRegex(ValueError, 'INVALID_PEER'):
                self.register(peer)

    def test_revocation_wins_over_inflight_verification(self):
        binding = self.register()
        evidence = self.evidence(binding)
        started, release = threading.Event(), threading.Event()
        original = self.registry.entries[binding['admission_id']].verifier.verifier
        class SlowVerifier:
            def verify(inner, message, challenge):
                started.set()
                if not release.wait(5):
                    raise ValueError('TEST_TIMEOUT')
                return original.verify(message, challenge)
        self.registry.entries[binding['admission_id']].verifier.verifier = SlowVerifier()
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(self.call, 'submit', binding, evidence=evidence)
            try:
                self.assertTrue(started.wait(3))
                self.assertFalse(self.call('status', binding)['allow'])
                with self.assertRaisesRegex(ValueError, 'CHALLENGE_PENDING'):
                    self.evidence(binding)
                with self.assertRaisesRegex(ValueError, 'NO_PENDING_CHALLENGE'):
                    self.call('submit', binding, evidence=evidence)
                self.assertEqual(self.call('revoke', binding)['state'], 'REVOKED')
                replacement = self.register()
            finally:
                release.set()
            with self.assertRaisesRegex(ValueError, 'ADMISSION_CLOSED'):
                future.result(timeout=5)
        self.assertFalse(self.call('status', replacement)['allow'])

    def test_limits_restart_and_response_mutation(self):
        self.registry.maximum = 1
        binding = self.register()
        with self.assertRaisesRegex(ValueError, 'PEER_ALREADY_REGISTERED'):
            self.register()
        with self.assertRaisesRegex(ValueError, 'ADMISSION_LIMIT'):
            self.register(3)
        response = self.call('status', binding)
        response['binding']['peer_id'] = 99
        self.assertEqual(self.call('status', binding)['binding']['peer_id'], 2)
        self.now[0] = 300
        replacement = self.register()
        with self.assertRaisesRegex(ValueError, 'UNKNOWN_ADMISSION'):
            self.call('status', binding)
        restart = admission.AdmissionRegistry([self.controller], {self.attestor: self.verifier})
        self.assertNotEqual(restart.instance_id, replacement['instance_id'])
        with self.assertRaisesRegex(ValueError, 'UNKNOWN_ADMISSION'):
            restart.dispatch(self.controller, request('status', admission_id=replacement['admission_id']))

    def test_config(self):
        path = self.folder / 'roles.json'
        config = dict(controllers=[self.controller], attestors={self.attestor: {'ak_public': 'public.pem'}})
        path.write_text(json.dumps(config))
        self.assertIn(self.attestor, admission.load_registry(path, INSPECTOR).attestors)
        for bad in [dict(config, extra=True), dict(config, controllers=[self.attestor]),
                    dict(config, controllers=[[]]), dict(config, attestors={self.attestor: {'ak_public': 123}})]:
            path.write_text(json.dumps(bad))
            with self.assertRaises(ValueError):
                admission.load_registry(path, INSPECTOR)

    def test_pinned_pcr_policy(self):
        policy = self.folder / 'pcr-policy.json'
        policy.write_text(json.dumps({'policy_version': 'pcr-reference/1',
            'sha256': {'0': '00' * 32, '7': '00' * 32}}))
        self.registry.attestors[self.attestor] = attest.QuoteVerifier(
            self.folder / 'public.pem', INSPECTOR, policy)
        binding = self.register()
        result = self.call('submit', binding, evidence=self.evidence(binding))
        self.assertFalse(result['allow'])
        self.assertEqual(result['attestation']['cryptographic_validity'], 'verified')
        self.assertEqual(result['attestation']['reasons'], ['PCR_REFERENCE_MISMATCH'])

    def test_service_process_start_stop(self):
        asyncio.run(self.process_case())

    async def process_case(self):
        folder = self.folder
        config = folder / 'process-config.json'
        config.write_text(json.dumps(dict(controllers=[self.controller],
            attestors={self.attestor: {'ak_public': 'public.pem'}})))
        process = await asyncio.create_subprocess_exec('python3', str(Path(admission.__file__)),
            '--config', str(config), '--inspector', str(INSPECTOR), '--port', '0',
            '--cert', str(folder / 'server.crt'), '--key', str(folder / 'server.key'),
            '--ca', str(folder / 'ca.crt'), stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE)
        try:
            boot = json.loads(await asyncio.wait_for(process.stdout.readline(), 5))
            self.assertEqual(boot['protocol_version'], admission.PROTOCOL)
            context = attest.tls_context(folder / 'client.crt', folder / 'client.key', folder / 'ca.crt')
            result = await admission.exchange('127.0.0.1', boot['port'], context, 'localhost',
                request('register', game_session_id='a' * 32, peer_id=2, attestor=self.attestor))
            self.assertEqual(result['binding']['instance_id'], boot['instance_id'])
            self.assertFalse(result['allow'])
            process.terminate()
            stdout, stderr = await asyncio.wait_for(process.communicate(), 10)
            self.assertEqual(process.returncode, 0, stderr)
            self.assertFalse(stderr, stderr)
        finally:
            if process.returncode is None:
                process.kill()
                await process.wait()

    def test_tls_and_cli(self):
        asyncio.run(self.tls_case())

    def test_worker_limit_and_shutdown_waits(self):
        asyncio.run(self.worker_case())

    async def worker_case(self):
        folder = self.folder
        service = admission.AdmissionService(self.registry)
        bindings = [self.register(peer) for peer in range(2, 7)]
        messages = [request('submit', admission_id=binding['admission_id'],
                            evidence=self.evidence(binding)) for binding in bindings]
        original = self.registry.dispatch
        started, release = threading.Event(), threading.Event()
        counter, counter_lock = [0], threading.Lock()
        def delayed(identity, message):
            if message['operation'] == 'submit':
                with counter_lock:
                    counter[0] += 1
                    if counter[0] == 4:
                        started.set()
                if not release.wait(5):
                    raise ValueError('TEST_TIMEOUT')
            return original(identity, message)
        self.registry.dispatch = delayed
        context = attest.tls_context(folder / 'server.crt', folder / 'server.key', folder / 'ca.crt', True)
        server = await asyncio.start_server(service.handle, '127.0.0.1', 0, ssl=context,
            ssl_handshake_timeout=3, ssl_shutdown_timeout=1)
        port = server.sockets[0].getsockname()[1]
        async def send(name, message):
            context = attest.tls_context(folder / (name + '.crt'), folder / (name + '.key'), folder / 'ca.crt')
            return await admission.exchange('127.0.0.1', port, context, 'localhost', message)
        tasks = [asyncio.create_task(send('client2', message)) for message in messages[:4]]
        closing = None
        try:
            self.assertTrue(await asyncio.to_thread(started.wait, 3))
            self.assertEqual((await send('client2', messages[4]))['error'], 'VERIFIER_BUSY')
            revoked = await send('client', request('revoke', admission_id=bindings[0]['admission_id']))
            self.assertEqual(revoked['state'], 'REVOKED')
            closing = asyncio.create_task(service.close())
            await asyncio.sleep(0)
            self.assertFalse(closing.done(), 'shutdown detached in-flight workers')
            release.set()
            results = await asyncio.wait_for(asyncio.gather(*tasks), 8)
            self.assertEqual(results[0]['error'], 'ADMISSION_CLOSED')
            self.assertTrue(all(result['allow'] for result in results[1:]), results)
            await asyncio.wait_for(closing, 3)
            self.assertEqual(counter[0], 4)
            self.assertEqual(service.verifications, 0)
            self.assertFalse(service.tasks)
        finally:
            release.set()
            server.close()
            await server.wait_closed()
            await asyncio.gather(*tasks, return_exceptions=True)
            if closing is not None:
                await closing
            await service.close()

    async def tls_case(self):
        folder = self.folder
        service = admission.AdmissionService(self.registry)
        context = attest.tls_context(folder / 'server.crt', folder / 'server.key', folder / 'ca.crt', True)
        server = await asyncio.start_server(service.handle, '127.0.0.1', 0, ssl=context,
            ssl_handshake_timeout=3, ssl_shutdown_timeout=1)
        port = server.sockets[0].getsockname()[1]
        async def send(name, message, server_name='localhost'):
            context = attest.tls_context(folder / (name + '.crt'), folder / (name + '.key'), folder / 'ca.crt')
            return await admission.exchange('127.0.0.1', port, context, server_name, message)
        message = request('register', game_session_id='a' * 32, peer_id=2, attestor=self.attestor)
        try:
            self.assertEqual((await send('unknown', message))['error'], 'UNAUTHORIZED_ROLE')
            self.assertEqual((await send('client2', message))['error'], 'UNAUTHORIZED_ROLE')
            with self.assertRaises(ssl.SSLCertVerificationError):
                await send('client', message, server_name='untrusted.invalid')
            with self.assertRaises((ssl.SSLError, ConnectionError, asyncio.IncompleteReadError)):
                await admission.exchange('127.0.0.1', port,
                    ssl.create_default_context(cafile=str(folder / 'ca.crt')), 'localhost', message)
            self.assertFalse(self.registry.entries)
            binding = (await send('client', message))['binding']
            challenge = await send('client2', request('challenge', admission_id=binding['admission_id']))
            evidence = fixtures.fixture(challenge['challenge'], folder)
            result = await send('client2', request('submit', admission_id=binding['admission_id'], evidence=evidence))
            self.assertTrue(result['allow'], result)
            result = await send('client', request('status', admission_id=binding['admission_id']))
            self.assertTrue(result['allow'])
            # Exercise the actual client entry point while this event loop serves requests.
            path = folder / 'request.json'
            path.write_text(json.dumps(request('revoke', admission_id=binding['admission_id'])))
            command = ['python3', str(Path(admission.__file__)), '--request', str(path),
                       '--port', str(port), '--cert', str(folder / 'client.crt'),
                       '--key', str(folder / 'client.key'), '--ca', str(folder / 'ca.crt')]
            process = await asyncio.create_subprocess_exec(*command,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            try:
                stdout, stderr = await asyncio.wait_for(process.communicate(), 15)
                self.assertEqual(process.returncode, 0, stderr)
                self.assertEqual(json.loads(stdout)['state'], 'REVOKED')
            finally:
                if process.returncode is None:
                    process.kill()
                    await process.wait()
            self.assertFalse((await send('client', request('status', admission_id=binding['admission_id'])))['allow'])
        finally:
            server.close()
            await server.wait_closed()
            await service.close()
        self.assertFalse(service.tasks)
        self.assertEqual(service.verifications, 0)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inspector', type=Path, default=Path('build-tpm/lab_quote_inspect'))
    args = parser.parse_args()
    INSPECTOR = args.inspector.resolve()
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(AdmissionTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(0 if result.wasSuccessful() else 1)
