"""Real hidden raylib window: malformed frames and changed identity fail closed."""
import argparse
import json
from pathlib import Path
import struct
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def fixture():
    data = bytearray(80)
    data[:8] = b'LGST\x01\0\0\x01'
    data[20] = 1; data[36] = 2
    struct.pack_into('<iiBBBB', data, 52, 0, 0, 100, 4, 0, 0)
    struct.pack_into('<iiBBBB', data, 64, 500, 0, 100, 4, 0, 0)
    data[76] = 3
    return bytes(data)


def frame(data):
    return struct.pack('!I', len(data)) + data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', type=Path, default=ROOT / 'build-graphics/lab_game_viewer')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    report = dict(passed=False, scope='actual hidden renderer; synthetic pipe frames, not game admission', cases=[])
    valid = fixture()
    changed = bytearray(valid); changed[36] = 3
    for name, data, expected_updates in [
        ('oversized_frame', struct.pack('!I', 81), 0),
        ('changed_session', frame(valid) + frame(changed), 1),
        ('truncated_frame', frame(valid)[:-1], 0),
        ('unknown_error', frame(b'LGRE\xff'), 0)
    ]:
        result = subprocess.run([str(args.binary.resolve()), '--hidden', '--seconds', '1'],
                                input=data, capture_output=True, timeout=5)
        if result.returncode != 1:
            report['error'] = name + ': unexpected exit ' + str(result.returncode)
            break
        records = [json.loads(line) for line in result.stderr.splitlines() if line.startswith(b'{')]
        if len(records) != 1 or records[0]['event'] != 'renderer_exit' or records[0]['updates'] != expected_updates:
            report['error'] = name + ': no renderer evidence (check display/runtime)'
            break
        if b'AddressSanitizer' in result.stderr or b'runtime error:' in result.stderr:
            report['error'] = name + ': sanitizer diagnostic'
            break
        report['cases'].append(name)
    else:
        report['passed'] = True
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
