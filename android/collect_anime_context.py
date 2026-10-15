"""Collect self-contained QNN contexts only after the device reference test passes."""
import json
import argparse
from pathlib import Path
import re
import subprocess

ADB = [r'C:\Users\Admin\AppData\Local\Programs\SideQuest\resources\platform-tools\adb.exe', '-s', 'R5CY53N3X1D']
PACKAGE = 'org.mangaamtl.npucheck'

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model-dir', type=Path, default=Path(__file__).parent / 'models/anime')
    parser.add_argument('--output-dir', type=Path, default=Path(__file__).parent / 'models/anime-npu')
    args = parser.parse_args()
    def read(*args): return subprocess.check_output(ADB + list(args), timeout=60)
    report = json.loads(read('shell', 'run-as', PACKAGE, 'cat', 'files/anime-report.json'))
    assert report.get('passed') and report['qnn_kernel_events'] >= 20 and report['other_kernel_events'] == 0, report
    root = args.model_dir
    stages = json.loads((root / 'pipeline.json').read_text())
    cached = read('shell', 'run-as', PACKAGE, 'ls', '-t', 'files/qnn-cache').decode().splitlines()
    target = args.output_dir; target.mkdir(parents=True, exist_ok=True)
    for stage in stages:
        source = root / stage['file']
        prefix = stage['file'] + '-' + str(source.stat().st_size) + '-'
        name = next(name.strip() for name in cached if name.strip().startswith((prefix, 'prepare1-' + prefix)))
        assert re.fullmatch(r'[a-zA-Z0-9_.-]+', name), name
        output = stage['file'].replace('.onnx', '.ctx.onnx')
        (target / output).write_bytes(read('exec-out', 'run-as', PACKAGE, 'cat', 'files/qnn-cache/' + name))
        stage['file'] = output
    (target / 'pipeline.json').write_text(json.dumps(stages, indent=2), encoding='utf-8')
    (target / 'verified.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    (Path(__file__).parent / 'evidence/anime-npu-report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print('Collected', len(stages), 'verified QNN contexts')

if __name__ == '__main__': main()
