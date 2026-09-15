"""Ephemeral credentials for owned loopback demos, never enrollment for production."""
from pathlib import Path
import os
import stat
import subprocess


def certificates(directory):
    directory = Path(directory)
    info = directory.stat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077 or any(directory.iterdir()):
        raise ValueError('CERTIFICATE_DIRECTORY_MUST_BE_PRIVATE_AND_EMPTY')

    def run(*args):
        subprocess.run(['openssl', *args], cwd=directory, check=True, stdout=subprocess.DEVNULL,
                       stderr=subprocess.PIPE, timeout=10)

    run('req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-keyout', 'ca.key', '-out', 'ca.crt',
        '-subj', '/CN=Lab temporary CA', '-days', '1', '-addext', 'basicConstraints=critical,CA:TRUE',
        '-addext', 'keyUsage=critical,keyCertSign,cRLSign')
    for name, usage in [('server', 'serverAuth'), ('client', 'clientAuth'),
                         ('client2', 'clientAuth'), ('unknown', 'clientAuth')]:
        run('req', '-new', '-newkey', 'rsa:2048', '-nodes', '-keyout', name + '.key',
            '-out', name + '.csr', '-subj', '/CN=' + name)
        (directory / (name + '.ext')).write_text('basicConstraints=critical,CA:FALSE\n'
            'keyUsage=critical,digitalSignature,keyEncipherment\nextendedKeyUsage=' + usage +
            '\nsubjectAltName=DNS:localhost\n')
        run('x509', '-req', '-in', name + '.csr', '-CA', 'ca.crt', '-CAkey', 'ca.key',
            '-CAcreateserial', '-out', name + '.crt', '-days', '1', '-extfile', name + '.ext')
