"""Run owned resources with an identified native lab_app (Linux or Windows)."""
import argparse
import hashlib
import json
import platform
import subprocess
import time
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', type=Path, default=Path('build/lab_app'))
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    evidence = dict(environment=platform.platform(), binary=str(args.binary.resolve()),
                    sha256=hashlib.sha256(args.binary.read_bytes()).hexdigest(), cases=[], passed=False)
    try:
        origin = {'Linux':'linux','Windows':'windows'}[platform.system()]
        subjects, instances = set(), set()
        for op in ['file','proc','sync']:
            for timeout_case in [False, True] if op != 'file' else [False]:
                command = [str(args.binary.resolve()), '--op', op, '--seed', '37', '--timeout-ms',
                           '50' if timeout_case else '2000', '--delay-ms', '1000' if timeout_case else '10']
                start = time.monotonic()
                run = subprocess.run(command, capture_output=True, text=True, timeout=4)
                data = json.loads(run.stdout)
                assert data['origin_os'] == origin and data['evidence_class'] == 'self_reported_lab'
                assert data['protocol'] == 'lab-observation/1'
                assert run.returncode == int(timeout_case) and data['ok'] == (not timeout_case), data
                assert (data['error'] != 0) == timeout_case
                assert len(bytes.fromhex(data['subject_id'])) == 16 and data['subject_id'] not in subjects
                assert len(bytes.fromhex(data['origin_instance'])) == 16 and data['origin_instance'] not in instances
                subjects.add(data['subject_id']); instances.add(data['origin_instance'])
                assert data['generation'] > 0 and data['process_id'] > 0
                if op == 'file':
                    expected = bytes((i * 7 + 37) & 255 for i in range(4096))
                    assert data['size'] == 4096 and data['sha256'] == hashlib.sha256(expected).hexdigest()
                if op == 'proc' and origin == 'linux':
                    assert not Path(f"/proc/{data['process_id']}").exists(), 'child still alive'
                if timeout_case:
                    assert time.monotonic() - start < 2, 'operation not cancelled promptly'
                evidence['cases'].append(dict(command=command, exit_code=run.returncode, observation=data))
        for arguments in [['--op','no'],['--op','file','--seed','-1'],['--op','file','--timeout-ms','0'],
                          ['--op','sync','--delay-ms','60001'],['--op','file','--seed','4294967296']]:
            run = subprocess.run([str(args.binary.resolve()), *arguments], capture_output=True, timeout=2)
            assert run.returncode == 2
        if origin == 'linux':
            with open('/dev/full','wb') as full:
                result=subprocess.run([str(args.binary.resolve()),'--op','file'],stdout=full,stderr=subprocess.PIPE,timeout=2)
                assert result.returncode == 1, 'stdout write failure reported as success'
            process=subprocess.Popen([str(args.binary.resolve()),'--op','proc','--timeout-ms','60000','--delay-ms','60000'],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            child=None
            try:
                deadline=time.monotonic()+2
                while time.monotonic()<deadline:
                    children=Path(f'/proc/{process.pid}/task/{process.pid}/children').read_text().split()
                    if children: child=int(children[0]);break
                    time.sleep(0.005)
                assert child is not None,'child readiness timeout'
                process.terminate();process.wait(timeout=2)
                deadline=time.monotonic()+2
                while time.monotonic()<deadline:
                    status=Path(f'/proc/{child}/stat')
                    if not status.exists() or status.read_text().rsplit(')',1)[1].split()[0]=='Z': break
                    time.sleep(0.005)
                else: raise AssertionError('owned child survived parent exit')
            finally:
                if process.poll() is None: process.kill();process.wait(timeout=2)
                process.stdout.close();process.stderr.close()
            evidence['cases'].append(dict(case='output_failure_and_child_terminated_with_parent'))
        evidence['passed'] = True
    except (OSError, ValueError, AssertionError, KeyError, subprocess.TimeoutExpired) as error:
        evidence['error'] = str(error)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(evidence, indent=2)+'\n')
    print(json.dumps(evidence, indent=2) if not evidence['passed'] else f"OK: {len(evidence['cases'])} operaciones y 5 rechazos CLI en {origin}")
    return 0 if evidence['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
