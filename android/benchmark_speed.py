"""Measure the extension's submit, translate, and render workflow on the phone."""
import argparse
import io
import json
from pathlib import Path
import time
import requests
from PIL import Image


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', type=Path, default=Path(__file__).parent.parent / 'Images/Raw.png')
    parser.add_argument('--label', default='baseline')
    parser.add_argument('--repeat', type=int, default=1)
    parser.add_argument('--blank', action='store_true')
    parser.add_argument('--async-render', action='store_true')
    parser.add_argument('--wait-status', action='store_true')
    args = parser.parse_args()
    client = requests.Session()
    client.trust_env = False
    base = 'http://127.0.0.1:17860'
    def request(method, path, **kwargs):
        response = client.request(method, base + path, timeout=90, **kwargs)
        response.raise_for_status()
        return response
    image = args.image.read_bytes()
    if args.blank:
        buffer = io.BytesIO()
        Image.new('RGB', (800, 1200), 'white').save(buffer, format='PNG')
        image = buffer.getvalue()
    settings = request('GET', '/GetAllSettings').json()
    reports = []
    for iteration in range(args.repeat):
        started = time.perf_counter()
        submitted = request('POST', '/v1/translate', files={'image': ('page.png', image, 'image/png')},
                            data={'target_lang': 'en', 'ocr_lang': 'ja', 'inpaint': 'true'}).json()
        job = submitted['job_id']
        submitted_at = time.perf_counter()
        deadline = started + 180
        status_requests = 0
        while True:
            request('POST', '/v1/health', json={'job_id': job, 'active': True})
            status_response = request('GET', '/v1/translate/' + job + ('?wait=0.5' if args.wait_status else ''))
            status_requests += 1
            report = status_response.json()
            if report['status'] in {'failed', 'cancelled'}:
                raise RuntimeError(report)
            if report['status'] == 'completed':
                break
            if time.perf_counter() > deadline:
                raise TimeoutError(report)
            if status_response.headers.get('X-MangaAMTL-Wait') != '1':
                time.sleep(.1)
        translated_at = time.perf_counter()
        headers = {'Prefer': 'respond-async'} if args.async_render else {}
        while True:
            rendered = request('POST', '/v1/translate/' + job + '/image', headers=headers)
            if rendered.status_code != 202:
                output = rendered.content
                break
            time.sleep(.1)
        ended = time.perf_counter()
        result = dict(iteration=iteration, job=job, submit_seconds=submitted_at-started,
                      translate_seconds=translated_at-submitted_at, render_seconds=ended-translated_at,
                      total_seconds=ended-started, regions=len(report['result'].get('translations', [])),
                      status_requests=status_requests, wait_status=args.wait_status)
        print(json.dumps(result), flush=True)
        reports.append(result)
        folder = Path(__file__).parent / 'evidence/speed'
        folder.mkdir(parents=True, exist_ok=True)
        (folder / (args.label + f'-{iteration}.png')).write_bytes(output)
        (folder / (args.label + f'-{iteration}-job.json')).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    logs = request('GET', '/console/json').json()
    (folder / (args.label + '.json')).write_text(json.dumps(dict(settings=settings, reports=reports, logs=logs[-200:]), ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
