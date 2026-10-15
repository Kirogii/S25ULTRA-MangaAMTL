"""Compare bounded page overlap with serial processing through the real phone API."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import io
import json
from pathlib import Path
import time

import requests
from PIL import Image


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workers', type=int, choices=(1, 2, 3), default=1)
    parser.add_argument('--count', type=int, default=8)
    parser.add_argument('--label', required=True)
    args = parser.parse_args()
    assert 1 <= args.count <= 32
    root = Path(__file__).parent
    payload = (root.parent / 'Images/Raw.png').read_bytes()

    def page(index):
        # Distinct corner pixels prevent the backend's duplicate-job shortcut.
        source = Image.open(io.BytesIO(payload)).convert('RGB')
        source.putpixel((0, 0), (index, 255, 255))
        encoded = io.BytesIO()
        source.save(encoded, format='PNG', compress_level=1)
        with requests.Session() as client:
            client.trust_env = False
            def request(method, path, **kwargs):
                response = client.request(method, 'http://127.0.0.1:17860' + path, timeout=90, **kwargs)
                response.raise_for_status()
                return response
            started = time.perf_counter()
            job = request('POST', '/v1/translate', files={'image': ('page.png', encoded.getvalue(), 'image/png')},
                data={'target_lang': 'en', 'ocr_lang': 'ja', 'inpaint': 'true'}).json()['job_id']
            deadline = started + 180
            while time.perf_counter() < deadline:
                request('POST', '/v1/health', json={'job_id': job, 'active': True})
                status = request('GET', '/v1/translate/' + job).json()
                if status['status'] in {'failed', 'cancelled'}: raise RuntimeError(status)
                if status['status'] == 'completed': break
                time.sleep(.1)
            else: raise TimeoutError(job)
            while time.perf_counter() < deadline:
                output = request('POST', '/v1/translate/' + job + '/image', headers={'Prefer': 'respond-async'})
                if output.status_code != 202: break
                time.sleep(.1)
            else: raise TimeoutError(job)
            decoded = Image.open(io.BytesIO(output.content))
            assert decoded.size == (1010, 1450)
            report = dict(index=index, seconds=time.perf_counter()-started, job=job)
            print(json.dumps(report), flush=True)
            return report

    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        reports = list(executor.map(page, range(args.count)))
    total = time.perf_counter()-started
    assert len({page['job'] for page in reports}) == args.count, 'Duplicate jobs invalidate the throughput comparison'
    result = dict(workers=args.workers, count=args.count, total_seconds=total,
                  seconds_per_image=total/args.count, pages=reports)
    print(json.dumps(result), flush=True)
    (root / 'evidence/speed' / (args.label + '.json')).write_text(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
