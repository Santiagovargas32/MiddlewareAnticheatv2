"""Build and test the Linux contract in a disposable directory, with deadlines."""
import argparse
import hashlib
import json
import os
import signal
from pathlib import Path
import subprocess
import tempfile
import time
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]


def run(command, limit):
    start = time.monotonic()
    try:
        process = subprocess.Popen(command, cwd=ROOT, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True, start_new_session=True)
        try:
            stdout, stderr = process.communicate(timeout=limit)
            code = process.returncode
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            stdout, stderr = process.communicate()
            code = 124
            stderr += '\nTimeout del verificador; grupo de procesos propio terminado.'
        record = dict(command=command, exit_code=code, stdout=stdout, stderr=stderr)
    except OSError as error:
        record = dict(command=command, exit_code=127, stdout='', stderr=str(error))
    record.update(elapsed_seconds=round(time.monotonic() - start, 3), timeout_seconds=limit)
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, help='Write a JSON evidence record')
    args = parser.parse_args()
    sources = [ROOT / 'CMakeLists.txt'] + sorted((ROOT / 'lab').rglob('*.c')) + sorted((ROOT / 'lab').rglob('*.h')) + sorted((ROOT / 'tests').glob('*.c'))
    evidence = {'date': datetime.now(timezone.utc).isoformat(),
                'scope': 'Build Linux Release y pruebas del contrato; integración pendiente',
                'source_sha256': {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},
                'checks': []}
    for command in [['cc', '--version'], ['cmake', '--version'], ['ninja', '--version']]:
        result = run(command, 10)
        evidence['checks'].append(result)
        if result['exit_code']:
            break
    else:
        with tempfile.TemporaryDirectory(prefix='middleware-check-') as directory:
            commands = [
                ['cmake', '-S', str(ROOT), '-B', directory, '-G', 'Ninja', '-DCMAKE_BUILD_TYPE=Release', '-DCMAKE_C_FLAGS=-Werror'],
                ['cmake', '--build', directory, '--parallel', '2'],
                ['ctest', '--test-dir', directory, '--output-on-failure', '--timeout', '10'],
                [str(Path(directory) / 'unit_tests')],
            ]
            for command in commands:
                result = run(command, 60)
                evidence['checks'].append(result)
                if result['exit_code']:
                    break
            else:
                # Check the range before narrowing to the 16-bit port field.
                for port in ['0', '65536', '-1', 'abc', '7777x']:
                    result = run([str(Path(directory) / 'lab_server'), '--port', port], 2)
                    result['expected_exit_code'] = 2
                    evidence['checks'].append(result)
    evidence['passed'] = all(r['exit_code'] == r.get('expected_exit_code', 0) for r in evidence['checks'])
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(evidence, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    for result in evidence['checks']:
        if result['exit_code'] != result.get('expected_exit_code', 0):
            print(result['stdout'] + result['stderr'])
    print('OK: build Release con -Werror, contrato y rechazos de puerto; integración pendiente.' if evidence['passed'] else 'FAIL: revisar evidencia de compilación/pruebas.')
    return 0 if evidence['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
