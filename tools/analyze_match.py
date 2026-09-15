#!/usr/bin/env python3
"""Replay the SAME Godot detector; ground truth is joined only after detection."""
import argparse
import json
from pathlib import Path
import subprocess
import tempfile
import os
from run_game import ROOT, engine


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('session', type=Path)
    parser.add_argument('--ground-truth', type=Path, action='append', default=[])
    parser.add_argument('--threshold', type=float, default=75)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if not 0 < args.threshold <= 100:
        parser.error('threshold must be in (0,100]')
    if args.session.stat().st_size > 128*1024*1024:
        parser.error('session exceeds 128 MiB')
    raw = args.session.read_bytes()
    tail_bytes = 0
    if raw and not raw.endswith(b'\n'):
        end = raw.rfind(b'\n')+1
        tail_bytes = len(raw)-end
        raw = raw[:end]
    with tempfile.TemporaryDirectory(prefix='arena-analyze-') as tmp:
        complete = Path(tmp)/'complete.jsonl'
        complete.write_bytes(raw)
        result = subprocess.run([engine(), '--headless', '--path', str(ROOT/'game'), '--script', 'tests/analyze.gd', '--', str(complete)],
                                text=True, capture_output=True, timeout=120, env=dict(os.environ, XDG_DATA_HOME=tmp))
    if result.returncode or 'SCRIPT ERROR' in result.stderr:
        raise SystemExit('Detector replay failed: '+result.stderr[-2000:])
    rows = [json.loads(line) for line in result.stdout.splitlines() if line.startswith('{')]
    truth = {}
    for path in args.ground_truth:
        if path.stat().st_size > 16*1024*1024:
            raise SystemExit('Ground truth exceeds 16 MiB')
        for line in path.read_text().splitlines():
            event = json.loads(line)
            if event.get('schema') != 'arena-ground-truth/1' or type(event.get('enabled')) is not bool:
                raise SystemExit('Invalid ground truth')
            if event.get('session') and event.get('player', 0) > 0:
                key = (event['session'], event['player'])
                truth.setdefault(key, []).append(event)
    for events in truth.values(): events.sort(key=lambda x: x['observed_server_tick'])
    confusion = dict(TP=0, TN=0, FP=0, FN=0)
    unknown = 0
    max_score = {}
    first_detected = {}
    for row in rows:
        key = (row['session'], row['player'])
        max_score[str(key)] = max(max_score.get(str(key), 0), row['score'])
        events = truth.get(key, [])
        # Exclude 12 ticks (~200ms at 60Hz) around each transition; observed ticks
        # are delayed by the network. No cross-host monotonic clock comparison.
        eligible = [e for e in events if e['observed_server_tick']+12 <= row['tick']]
        if not eligible or any(abs(e['observed_server_tick']-row['tick']) < 12 for e in events):
            unknown += 1
            continue
        label = eligible[-1]['enabled']
        detected = row['score'] >= args.threshold
        confusion['TP' if label and detected else 'FN' if label else 'FP' if detected else 'TN'] += 1
        if label and detected:
            first_detected.setdefault(str(key), row['tick']-eligible[-1]['observed_server_tick'])
    def ratio(a, b): return a/b if b else None
    tp, tn, fp, fn = (confusion[k] for k in ('TP', 'TN', 'FP', 'FN'))
    report = dict(scope='per-sample experimental metrics; labels external to detector; not proof of human false-positive rate',
                  samples=len(rows), truncated_tail_bytes=tail_bytes, unknown_labels=unknown, threshold=args.threshold, confusion=confusion,
                  precision=ratio(tp, tp+fp), recall=ratio(tp, tp+fn), false_positive_rate=ratio(fp, fp+tn),
                  false_negative_rate=ratio(fn, fn+tp), max_score=max_score,
                  detection_latency_observed_server_ticks=first_detected,
                  timing_limit='12-tick transition exclusion; observed server tick includes network uncertainty')
    output = json.dumps(report, indent=2)+'\n'
    if args.output: args.output.write_text(output)
    print(output, end='')


if __name__ == '__main__': main()
