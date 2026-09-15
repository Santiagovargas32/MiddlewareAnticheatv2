#!/usr/bin/env python3
"""Compare this game's source assets to an operator-provisioned SHA256 manifest.

A local result is self-reported file integrity, never TPM proof or cheat absence.
"""
import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def inventory(root):
    files = sorted(p for p in (root/'game').rglob('*') if p.is_file() and '.godot' not in p.parts and p.suffix != '.uid')
    files += [root/name for name in ('game-client','game-server','tools/run_game.py')]
    for path in files:
        if path.is_symlink(): raise ValueError('Symlink not allowed: '+str(path))
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('create','verify'))
    parser.add_argument('manifest', type=Path)
    args = parser.parse_args()
    actual = inventory(ROOT)
    if args.action == 'create':
        with args.manifest.open('x') as stream:
            json.dump({'schema':'arena-client-manifest/1','files':actual},stream,indent=2)
        print('Created operator baseline. Distribute via trusted channel; do not regenerate after an unexpected mismatch.')
    else:
        expected = json.loads(args.manifest.read_text())
        if expected.get('schema') != 'arena-client-manifest/1' or not isinstance(expected.get('files'),dict):
            raise SystemExit('Invalid manifest')
        changes = sorted(key for key in set(actual)|set(expected['files']) if actual.get(key)!=expected['files'].get(key))
        print(json.dumps({'integrity':'FAIL' if changes else 'PASS','scope':'local file hashes only, self-reported','changed':changes},indent=2))
        raise SystemExit(1 if changes else 0)


if __name__ == '__main__': main()
