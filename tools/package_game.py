#!/usr/bin/env python3
"""Create a reproducible source package for the DEVELOPMENT FPS; no secrets/build caches."""
import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path
import tarfile

from release_files import ROOT, public_files


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    paths = public_files()
    entries = {}
    for path in sorted(set(paths)):
        if path.is_symlink() or path.suffix in ('.key','.pem','.pyc'):
            raise SystemExit('Refusing private/unexpected file: '+str(path))
        entries[str(path.relative_to(ROOT))] = path.read_bytes()
    metadata = dict(version=(ROOT/'VERSION').read_text().strip(), profile='development_unattested', protected_game_complete=False, godot='4.7.2',
                    sha256={key:hashlib.sha256(data).hexdigest() for key,data in entries.items()})
    entries['PACKAGE.json'] = (json.dumps(metadata,indent=2)+'\n').encode()
    with args.output.open('xb') as output, gzip.GzipFile(filename='',mode='wb',fileobj=output,mtime=0) as compressed:
        with tarfile.open(mode='w',fileobj=compressed,format=tarfile.PAX_FORMAT) as archive:
            for name,data in sorted(entries.items()):
                member = tarfile.TarInfo('MiddlewareAnticheatv2/'+name)
                member.size = len(data)
                member.mode = 0o755 if name in ('game-client','game-server') else 0o644
                archive.addfile(member,io.BytesIO(data))
    print(json.dumps(dict(path=str(args.output),sha256=hashlib.sha256(args.output.read_bytes()).hexdigest(),files=len(entries),profile=metadata['profile'])))


if __name__ == '__main__': main()
