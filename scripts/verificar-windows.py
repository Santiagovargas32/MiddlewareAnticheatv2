"""Cross-compile real Windows console executables; never claim runtime validation."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    env=os.environ.copy()
    local=ROOT/'results/toolchain/root/usr/bin'
    if not shutil.which('x86_64-w64-mingw32-gcc') and (local/'x86_64-w64-mingw32-gcc').is_file():
        env['PATH']=str(local)+os.pathsep+env['PATH']
    build=ROOT/'build-windows'
    evidence=dict(scope='cross compilation only',environment=platform.platform(),checks=[],artifacts=[],
                  compilation='IN_PROGRESS',windows_runtime='BLOCKED',reason='No Windows runtime selected or executed')
    commands=[['x86_64-w64-mingw32-gcc','--version'],
              ['cmake','-S',str(ROOT),'-B',str(build),'-G','Ninja','-DCMAKE_TOOLCHAIN_FILE=cmake/mingw64.cmake','-DCMAKE_BUILD_TYPE=Release','-DCMAKE_C_FLAGS=-Werror'],
              ['cmake','--build',str(build),'--parallel','2']]
    try:
        for command in commands:
            result=subprocess.run(command,env=env,cwd=ROOT,capture_output=True,text=True,timeout=60)
            evidence['checks'].append(dict(command=command,exit_code=result.returncode,stdout=result.stdout,stderr=result.stderr))
            if result.returncode: raise RuntimeError('cross compilation failed')
        for name in ['lab_app.exe','unit_tests.exe','evidence_tests.exe']:
            binary=build/name
            result=subprocess.run(['x86_64-w64-mingw32-objdump','-p',str(binary)],env=env,capture_output=True,text=True,check=True,timeout=10)
            dlls=[line.strip().split(': ',1)[1] for line in result.stdout.splitlines() if 'DLL Name:' in line]
            if any(dll.lower() not in ['bcrypt.dll','kernel32.dll','msvcrt.dll'] for dll in dlls): raise RuntimeError('unpackaged runtime DLL')
            evidence['artifacts'].append(dict(path=str(binary.relative_to(ROOT)),sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),imports=dlls))
        evidence['compilation']='DONE'
    except (OSError,RuntimeError,subprocess.SubprocessError) as error:
        evidence.update(compilation='BLOCKED',error=str(error))
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(evidence,indent=2)+'\n')
    print('DONE: PE Windows compilados con -Werror. BLOCKED: ejecución Windows real pendiente.' if evidence['compilation']=='DONE' else json.dumps(evidence,indent=2))
    return 0 if evidence['compilation']=='DONE' else 1


if __name__=='__main__': raise SystemExit(main())
