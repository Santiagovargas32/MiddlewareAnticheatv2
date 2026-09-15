"""Check owned process management, identity and occupied ports."""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import lab
from lab_processes import identity


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    evidence=dict(cases=[],checks=[],passed=False)
    with tempfile.TemporaryDirectory(prefix='lab-cli-') as temp:
        runtime=Path(temp)
        def run(command,extra=(),code=0):
            result=subprocess.run([sys.executable,str(lab.ROOT/'scripts/lab.py'),command,'--runtime',str(runtime),*extra],capture_output=True,text=True,timeout=8)
            evidence['checks'].append(dict(command=command,arguments=list(extra),exit_code=result.returncode,stdout=result.stdout,stderr=result.stderr))
            assert result.returncode==code,result
            return json.loads(result.stdout)
        try:
            ports=['--port',str(lab.free_port()),'--adapter-port',str(lab.free_port())]
            first=run('start',ports)
            assert first['running'] and run('status')['running']
            again=run('start',ports)
            assert [p['pid'] for p in first['processes']]==[p['pid'] for p in again['processes']]
            for port in [p['port'] for p in first['processes']]:
                result=subprocess.run([str(lab.ROOT/'build/lab_client'),'--port',str(port),'--count','1','--op','file'],capture_output=True,text=True,timeout=3)
                assert result.returncode==0 and json.loads(result.stdout.splitlines()[-1])['ok']
            assert run('stop')['stopped'] and not run('status')['running']
            assert all(identity(p['pid']) is None for p in first['processes'])
            evidence['cases'].append('start_status_native_clients_idempotence_stop')
            with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as occupied:
                occupied.bind(('127.0.0.1',0))
                run('start',['--port',str(occupied.getsockname()[1])],1)
                assert occupied.fileno()>=0 and not run('status')['running']
            evidence['cases'].append('occupied_port_fails_without_stopping_owner')
            # Deliberately stale instance for an owned sentinel; it must survive stop.
            sentinel=subprocess.Popen([sys.executable,'-c','import time; time.sleep(10)'])
            try:
                record=identity(sentinel.pid)
                assert record is not None
                record.update(name='lab_server',start_ticks='-1',port=7777)
                (runtime/'state.json').write_text(json.dumps([record]))
                assert not run('status')['running'] and run('stop')['stopped']
                assert sentinel.poll() is None,'old PID instance was signalled'
            finally:
                sentinel.terminate();sentinel.wait(timeout=2)
            evidence['cases'].append('stale_process_identity_preserved')
            evidence['passed']=True
        except (OSError,ValueError,AssertionError,subprocess.SubprocessError) as error:
            evidence['error']=str(error)
        finally:
            run('stop')
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(evidence,indent=2)+'\n')
    print(f"OK: {len(evidence['cases'])} grupos de CLI" if evidence['passed'] else json.dumps(evidence,indent=2))
    return 0 if evidence['passed'] else 1


if __name__=='__main__': raise SystemExit(main())
