#!/usr/bin/env python3
"""Run bounded FPS/tool/docs checks; no hardware, graphics or physical LAN claims."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from run_game import ROOT, engine


def main():
    result_dir = ROOT/'results/release-checks'
    result_dir.mkdir(parents=True,exist_ok=True)
    report = {'passed':False,'scope':'local headless processes, physics and software fixtures; no physical LAN/TPM', 'checks':[]}
    with tempfile.TemporaryDirectory(prefix='arena-release-') as tmp:
        env = dict(os.environ,XDG_DATA_HOME=tmp,XDG_CONFIG_HOME=tmp,XDG_CACHE_HOME=tmp)
        checks = [
            ('launch-help',[str(ROOT/'game-client'),'--help'],10),
            ('launch-version',[str(ROOT/'game-server'),'--version'],10),
            ('godot-rules',[engine(),'--headless','--path',str(ROOT/'game'),'--script','tests/rules.gd'],20),
            ('admission-boundary',[engine(),'--headless','--path',str(ROOT/'game'),'--script','tests/admission.gd'],15),
            ('gateway-routes',[engine(),'--headless','--path',str(ROOT/'game'),'--script','tests/gateway_rules.gd'],15),
            ('gateway-negative',[sys.executable,'tests/gateway_tests.py'],45),
            ('gateway-network',[sys.executable,'tools/verify_gateway.py'],60),
            ('tool-behavior',[sys.executable,'tools/test_game_tools.py'],30),
            ('fps-network',[sys.executable,'tools/verify_game.py'],60),
            ('documentation',[sys.executable,'scripts/verificar-documentacion.py'],10),
        ]
        for name,command,timeout in checks:
            print('RUN',name,flush=True)
            try:
                result = subprocess.run(command,cwd=ROOT,env=env,capture_output=True,text=True,timeout=timeout)
                output = result.stdout+result.stderr
                passed = result.returncode == 0 and 'SCRIPT ERROR' not in output and 'ERROR:' not in output
            except subprocess.TimeoutExpired:
                output = 'TIMEOUT'; passed = False
            (result_dir/(name+'.log')).write_text(output)
            report['checks'].append({'name':name,'passed':passed})
            if not passed:
                print(output[-4000:],file=sys.stderr)
                break
        else:
            report['passed'] = True
    (result_dir/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))
    return 0 if report['passed'] else 1


if __name__ == '__main__': raise SystemExit(main())
