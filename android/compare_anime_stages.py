"""Locate the first device/reference divergence using probe tensor dumps."""
import json
from pathlib import Path
import subprocess
import numpy as np

def main():
    root = Path(__file__).parent
    adb = [r'C:\Users\Admin\AppData\Local\Programs\SideQuest\resources\platform-tools\adb.exe', '-s', 'R5CY53N3X1D', 'exec-out', 'run-as', 'org.mangaamtl.npucheck', 'cat']
    stages = json.loads((root / 'models/anime/pipeline.json').read_text())
    report = []
    for index, stage in enumerate(stages):
        for number in range(len(stage['outputs'])):
            expected = np.fromfile(root / f'models/anime-reference-stage{index}-{number}.f32', dtype='<f4')
            raw = subprocess.check_output(adb + [f'files/stage{index}-{number}.f32'], timeout=30)
            actual = np.frombuffer(raw, dtype='<f4')
            assert actual.shape == expected.shape
            row = dict(stage=index, output=number, mean_error=float(np.abs(actual-expected).mean()),
                max_error=float(np.abs(actual-expected).max()), expected_range=[float(expected.min()),float(expected.max())],
                actual_range=[float(actual.min()),float(actual.max())], finite=bool(np.isfinite(actual).all()))
            report.append(row); print(json.dumps(row), flush=True)
    (root / 'evidence/anime-stage-comparison.json').write_text(json.dumps(report, indent=2))

if __name__ == '__main__': main()
