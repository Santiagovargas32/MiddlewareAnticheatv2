#!/usr/bin/env python3
"""Behavior tests for offline detector/label separation and metric handling."""
import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from run_game import ROOT, parse_args


class LauncherTests(unittest.TestCase):
    def test_rejects_invalid_addresses_ports_names_and_arguments(self):
        cases = [['--port','0'],['--port','65536'],['--join','not-an-ip'],
                 ['--name','two words'],['--port'],['--config','/missing-arena-file'],
                 ['--server','--join','127.0.0.1'],['--seconds','nan']]
        for arguments in cases:
            with self.subTest(arguments=arguments), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as error: parse_args(arguments)
                self.assertEqual(error.exception.code,2)
        options = parse_args(['--join','192.168.1.50','--port','7777','--name','Alice'])
        self.assertEqual(options.join,'192.168.1.50')
        self.assertEqual(options.port,7777)


class AnalysisTests(unittest.TestCase):
    def test_labels_join_after_detection_and_missing_denominators(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            telemetry = folder/'trace.jsonl'
            labels = folder/'labels.jsonl'
            records = []
            for index in range(100):
                records.append(dict(schema='arena-observation/1', session='synthetic', player=2,
                                    tick=index*3, server_ms=index*50, yaw=.6 if index%2 else -.6,
                                    pitch=0, error=.0001, delta=.05, visible_target=3))
            telemetry.write_text(''.join(json.dumps(x)+'\n' for x in records))
            def analyze(truth):
                command = [sys.executable,str(ROOT/'tools/analyze_match.py'),str(telemetry)]
                if truth: command += ['--ground-truth',str(labels)]
                result = subprocess.run(command,capture_output=True,text=True,timeout=15)
                self.assertEqual(result.returncode,0,result.stderr)
                return json.loads(result.stdout)
            missing = analyze(False)
            self.assertEqual(missing['unknown_labels'],100)
            self.assertIsNone(missing['precision'])
            for enabled in (True,False):
                labels.write_text(json.dumps(dict(schema='arena-ground-truth/1',session='synthetic',player=2,observed_server_tick=0,enabled=enabled))+'\n')
                measured = analyze(True)
                self.assertEqual(measured['max_score'],missing['max_score'])
                self.assertGreater(measured['confusion']['TP' if enabled else 'FP'],90)
            with telemetry.open('a') as stream: stream.write('{"interrupted":')
            interrupted = analyze(False)
            self.assertEqual(interrupted['samples'],100)
            self.assertGreater(interrupted['truncated_tail_bytes'],0)


if __name__ == '__main__': unittest.main()
