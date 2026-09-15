"""Verify the local C game core and its scripted demonstration; no network/game engine."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def run(binary, *args, expected=0):
    result = subprocess.run([str(binary), *args], capture_output=True, text=True, timeout=10)
    if result.returncode != expected:
        raise RuntimeError(f'{binary.name}: exit {result.returncode}; {result.stderr[-1200:]}')
    if 'AddressSanitizer' in result.stderr or 'runtime error:' in result.stderr:
        raise RuntimeError('SANITIZER_DIAGNOSTIC')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build-dir', type=Path, default=ROOT / 'build')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    build = args.build_dir.resolve()
    report = dict(passed=False, scope='local C rules and scripted simulation; no authenticated transport',
                  date=datetime.now(timezone.utc).isoformat(), system=platform.platform(), cases=[])
    paths = ['lab/game/game.c', 'lab/game/game.h', 'lab/app/game_demo.c',
             'tests/game_tests.c', 'tests/game_entropy_fault.c', 'scripts/verificar-juego.py', 'CMakeLists.txt']
    report['source_sha256'] = {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in paths}
    try:
        checks = run(build / 'game_tests').stdout.splitlines()
        if len(checks) != 7 or not all(x.startswith('PASS: ') for x in checks):
            raise RuntimeError('RULE_TEST_GROUPS_MISSING')
        report['cases'].extend(x.removeprefix('PASS: ') for x in checks)
        events = [json.loads(line) for line in run(build / 'lab_game_demo').stdout.splitlines()]
        if len(events) != 10 or events[0] != dict(event='start', protocol='lab-game-input/1',
                scope='local_scripted_simulation', authenticated_transport=False, tick_ms=50):
            raise RuntimeError('DEMO_START_INVALID')
        expected = [(0, 0, 1, 1, 'ACCEPTED'), (0, 0, 2, 1, 'TICK_ALREADY_USED'),
                    (0, 0, 1, 1, 'SEQUENCE_REPLAY'), (1, 0, 2, 2, 'ACCEPTED'),
                    (2, 0, 3, 2, 'FIRE_COOLDOWN'), (2, 1, 1, 1, 'ACCEPTED'),
                    (5, 0, 3, 2, 'ACCEPTED'), (5, 1, 2, 3, 'SESSION_CLOSED')]
        for event, (tick, player, sequence, action, reason) in zip(events[1:-1], expected):
            if event != dict(event='input', tick=tick, player=player, sequence=sequence,
                             action=action, reason=reason):
                raise RuntimeError('DEMO_EVENT_INVALID')
        if events[-1] != dict(event='final', passed=True, tick=5, player0_x_mm=100,
                              player0_ammo=2, player0_hits=2, player1_x_mm=600,
                              player1_health=50, player1_open=False):
            raise RuntimeError('DEMO_FINAL_STATE_INVALID')
        report['demo'] = events[-1]
        report['cases'].append('demo_exact_events_and_final_state')
        run(build / 'lab_game_demo', '--unrecognized', expected=2)
        failed = run(build / 'game_demo_entropy_failure', expected=1)
        if failed.stdout or json.loads(failed.stderr) != {'error': 'INITIALIZATION_FAILED'}:
            raise RuntimeError('ENTROPY_FAILURE_NOT_CLOSED')
        report['cases'].append('argument_and_entropy_failure_no_constant_identity')
        report['passed'] = True
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        report['error'] = str(error)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
