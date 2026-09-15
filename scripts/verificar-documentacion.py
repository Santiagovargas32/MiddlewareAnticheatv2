"""Verify public source inventory and local Markdown links, without the private history."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tools'))
from release_files import public_files


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--code-evidence',type=Path)
    args = parser.parse_args()
    paths = set(public_files())
    errors = []
    links = 0
    for path in sorted(paths):
        if path.suffix != '.md': continue
        raw = re.sub(r'```.*?```','',path.read_text(),flags=re.S)
        for link in re.findall(r'\[[^\]]+\]\(([^)]+)\)',raw):
            parsed = urlsplit(link)
            if parsed.scheme or parsed.netloc or not parsed.path: continue
            target = (path.parent/unquote(parsed.path)).resolve()
            links += 1
            if target not in paths:
                errors.append(f'{path.relative_to(ROOT)}: link not in public package: {link}')
    if args.code_evidence:
        hashes = json.loads(args.code_evidence.read_text())['source_sha256']
        for name,digest in hashes.items():
            path = ROOT/name
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=digest:
                errors.append('Changed source: '+name)
    if errors:
        print('\n'.join(errors),file=sys.stderr)
        return 1
    print(f'PASS: {len(paths)} public files, {links} local documentation links')
    return 0


if __name__ == '__main__': raise SystemExit(main())
