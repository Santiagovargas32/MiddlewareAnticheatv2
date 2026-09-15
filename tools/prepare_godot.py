#!/usr/bin/env python3
"""Install a pinned official Godot binary locally; no root or global changes."""
import hashlib
import os
from pathlib import Path
import platform
import tempfile
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
VERSION = '4.7.2'
ARCHIVE = f'Godot_v{VERSION}-stable_linux.x86_64.zip'
SHA512 = '9aa00f7a605200940bce3027a567b782f49bd8e940dd06ae9e987bd65aee1b1467edd56ed84fcdcbdd44354bf613bdbb4e5d2913e925850368e150c59ed54c65'
BINARY_SHA256 = '8d106cbe6144c2dc7e881d61d2429c1a8a76e6b22ef48bd5e48dcf934953f71e'
URL = f'https://github.com/godotengine/godot-builds/releases/download/{VERSION}-stable/{ARCHIVE}'


def main():
    if platform.system() != 'Linux' or platform.machine() != 'x86_64':
        raise SystemExit('This distribution is Linux x86_64; use GODOT_BIN for another Godot 4 installation.')
    dest = ROOT / f'results/toolchain/godot-{VERSION}'
    dest.mkdir(parents=True, exist_ok=True)
    executable = dest / 'godot'
    if executable.is_symlink():
        raise SystemExit('Refusing symlink at Godot executable path.')
    if executable.exists():
        with executable.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        if digest != BINARY_SHA256:
            raise SystemExit('Existing Godot differs from the pinned distribution; preserved without overwrite.')
        print('Godot '+VERSION+' verified and already prepared.')
        return
    with tempfile.TemporaryDirectory(prefix='godot-download-') as directory:
        archive = Path(directory) / ARCHIVE
        with urllib.request.urlopen(URL, timeout=60) as response, archive.open('wb') as output:
            total = 0
            while chunk := response.read(1024*1024):
                total += len(chunk)
                if total > 150*1024*1024:
                    raise RuntimeError('Download exceeds bound')
                output.write(chunk)
        if hashlib.sha512(archive.read_bytes()).hexdigest() != SHA512:
            raise RuntimeError('Official archive SHA512 mismatch')
        with zipfile.ZipFile(archive) as bundle:
            member = bundle.getinfo(ARCHIVE[:-4])
            if member.file_size > 250*1024*1024:
                raise RuntimeError('Binary exceeds bound')
            data = bundle.read(member)
            if hashlib.sha256(data).hexdigest() != BINARY_SHA256:
                raise RuntimeError('Godot binary SHA256 mismatch')
            with tempfile.TemporaryDirectory(prefix='install-', dir=dest) as install_dir:
                staged = Path(install_dir)/'godot'
                staged.write_bytes(data)
                staged.chmod(0o755)
                os.link(staged, executable)  # Atomic publication; never replace an existing file.
    print(dest / 'godot')


if __name__ == '__main__':
    main()
