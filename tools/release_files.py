"""One source inventory for public Git staging, packages and documentation checks.

Only source formats are distributable. Local history, credentials and caches
stay on disk; they never enter this inventory.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = ('.gitignore','README.md','VERSION','THIRD_PARTY_NOTICES.md',
         'CMakeLists.txt','game-client','game-server','AGENTS.md',
         '.github/pull_request_template.md')
FORMATS = {'game': {'.gd','.uid','.tscn','.cfg','.godot'},
           'tools': {'.py'}, 'scripts': {'.py'}, 'lab': {'.c','.h'},
           'tests': {'.py','.c','.md'}, 'cmake': {'.cmake'},
           'docs': {'.md','.json','.png'}, 'datasets': {'.md','.jsonl'},
           '.github/workflows': {'.yml','.yaml'}}


def public_files(root=ROOT):
    paths = [root/name for name in FILES]
    for folder, extensions in FORMATS.items():
        paths.extend(p for p in (root/folder).rglob('*')
                     if p.is_file() and p.suffix in extensions
                     and not any(part in ('.godot','__pycache__') for part in p.parts))
    for path in paths:
        if path.is_symlink() or not path.is_file():
            raise ValueError('Source missing or symlink: '+str(path.relative_to(root)))
        if path.stat().st_size > 5*1024*1024:
            raise ValueError('Unexpectedly large source: '+str(path.relative_to(root)))
    return sorted(set(paths))


if __name__ == '__main__':
    import sys
    separator = '\0' if '--null' in sys.argv else '\n'
    sys.stdout.write(separator.join(str(p.relative_to(ROOT)) for p in public_files())+separator)
