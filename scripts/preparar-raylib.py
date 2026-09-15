"""Fetch pinned official raylib 5.5 Linux x86_64 files locally; no system install."""
import hashlib
from pathlib import Path
import platform
import subprocess
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[1]
URL = 'https://github.com/raysan5/raylib/releases/download/5.5/raylib-5.5_linux_amd64.tar.gz'
SHA256 = '3d95ef03d5b38dfa55c0a16ca122d382134b078f0e5b270b52fe7eae0549c000'
DEST = ROOT / 'results/toolchain/raylib-5.5'
FILES = ('include/raylib.h', 'lib/libraylib.so.5.5.0', 'LICENSE')


def main():
    if platform.system() != 'Linux' or platform.machine() != 'x86_64':
        raise RuntimeError('This pinned distribution requires Linux x86_64')
    cache = ROOT / 'results/downloads'
    cache.mkdir(parents=True, exist_ok=True)
    archive = cache / 'raylib-5.5_linux_amd64.tar.gz'
    if not archive.exists():
        with tempfile.TemporaryDirectory(prefix='raylib-download-', dir=cache) as temp:
            path = Path(temp) / 'download'
            subprocess.run(['curl', '--fail', '--location', '--max-time', '90', '--output',
                            str(path), URL], check=True, timeout=95)
            if hashlib.sha256(path.read_bytes()).hexdigest() != SHA256:
                raise RuntimeError('RAYLIB_ARCHIVE_HASH_MISMATCH')
            path.replace(archive)
    if archive.stat().st_size > 8 * 1024 * 1024 or hashlib.sha256(archive.read_bytes()).hexdigest() != SHA256:
        raise RuntimeError('RAYLIB_ARCHIVE_HASH_MISMATCH')
    with tarfile.open(archive, 'r:gz') as bundle:
        for name in FILES:
            entry = bundle.getmember('raylib-5.5_linux_amd64/' + name)
            if not entry.isfile() or not 0 < entry.size <= 8 * 1024 * 1024:
                raise RuntimeError('RAYLIB_MEMBER_INVALID')
            source = bundle.extractfile(entry)
            if source is None:
                raise RuntimeError('RAYLIB_MEMBER_MISSING')
            with source:
                data = source.read()
            target = DEST / name
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                if target.is_symlink() or target.read_bytes() != data:
                    raise RuntimeError('RAYLIB_LOCAL_FILE_DIFFERS: ' + name)
            else:
                with target.open('xb') as output:
                    output.write(data)
    alias = DEST / 'lib/libraylib.so.550'
    if alias.is_symlink():
        if alias.readlink() != Path('libraylib.so.5.5.0'):
            raise RuntimeError('RAYLIB_SONAME_LINK_DIFFERS')
    elif alias.exists():
        raise RuntimeError('RAYLIB_SONAME_PATH_OCCUPIED')
    else:
        alias.symlink_to('libraylib.so.5.5.0')
    print('raylib 5.5 ready:', DEST)
    print('SHA256:', SHA256, '(pinned downloaded release, not a signature verification)')


if __name__ == '__main__':
    main()
