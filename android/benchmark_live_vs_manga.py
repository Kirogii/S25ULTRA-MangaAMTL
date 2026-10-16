"""Alternate identical saved images through live and manga APIs without screen capture."""
import argparse
import base64
import io
import json
from pathlib import Path
import statistics
import time
import requests
from PIL import Image


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repeat', type=int, default=5)
    parser.add_argument('--label', default='live-vs-manga-baseline')
    parser.add_argument('--patches-only', action='store_true')
    parser.add_argument('--fresh-pixels', action='store_true', help='Change image pixels each pair to measure OCR cache misses')
    parser.add_argument('--identical', action='store_true', help='Reuse the exact image to measure the repeat-image path')
    args = parser.parse_args()
    if args.repeat < 3: parser.error('--repeat must be at least 3')
    if args.fresh_pixels and args.identical: parser.error('Choose either fresh pixels or identical images')
    client = requests.Session(); client.trust_env = False
    base = 'http://127.0.0.1:17860'
    def request(method, path, **kwargs):
        response = client.request(method, base+path, timeout=90, **kwargs)
        response.raise_for_status()
        return response
    for _ in range(60):
        try:
            if request('GET', '/health').ok: break
        except requests.RequestException: time.sleep(.5)
    else: raise RuntimeError('Phone server unavailable')
    root = Path(__file__).parent
    original_bytes = (root.parent/'Images/Raw.png').read_bytes()
    source = Image.open(io.BytesIO(original_bytes)).convert('RGB')
    previous_mode = request('GET', '/GetInpaintMode').json()['inpaint_mode']
    request('POST', '/SetInpaintMode', json={'mode': 'blur'})
    reports = []
    nonce = int(time.time_ns() & 0xffffff)
    try:
        for iteration in range(args.repeat):
            image = source.copy()
            if args.fresh_pixels:
                image = image.point(lambda value: max(0, value-iteration-1))
            elif not args.identical:
                image.putpixel((0, 0), ((nonce >> 16)&255, (nonce >> 8)&255, nonce&255))
                image.putpixel((1, 0), (iteration, 255, 255))
            if args.identical:
                payload = original_bytes  # Match the extension's original-file upload path.
            else:
                encoded = io.BytesIO(); image.save(encoded, 'PNG', compress_level=1)
                payload = encoded.getvalue()
            for pipeline in (('manga', 'live') if iteration % 2 == 0 else ('live', 'manga')):
                started = time.perf_counter()
                if pipeline == 'live':
                    result = request('POST', '/v1/live', files={'image': ('page.png', payload, 'image/png')},
                        data={'target_lang': 'en', 'ocr_lang': 'ja', 'cache_enabled': 'true', 'background_mode': 'blur',
                              'include_overlay': str(not args.patches_only).lower()}).json()
                    if args.patches_only:
                        assert result['overlay'] is None
                        for item in result['items']:
                            patch = Image.open(io.BytesIO(base64.b64decode(item['overlay']))); patch.load()
                            box = item['bbox']; assert patch.size == (box[2]-box[0], box[3]-box[1])
                        output = None
                    else: output = base64.b64decode(result['overlay'])
                    report = {k: result[k] for k in ('regions', 'cache_hits', 'ocr_seconds', 'translation_seconds', 'translation_backend')}
                else:
                    job = request('POST', '/v1/translate', files={'image': ('page.png', payload, 'image/png')},
                        data={'target_lang': 'en', 'ocr_lang': 'ja', 'inpaint': 'true'}).json()['job_id']
                    deadline = started+180
                    while time.perf_counter() < deadline:
                        request('POST', '/v1/health', json={'job_id': job, 'active': True})
                        status_response = request('GET', '/v1/translate/'+job+'?wait=0.5')
                        status = status_response.json()
                        if status['status'] in {'failed', 'cancelled'}: raise RuntimeError(status)
                        if status['status'] == 'completed': break
                        if status_response.headers.get('X-MangaAMTL-Wait') != '1': time.sleep(.05)
                    else: raise TimeoutError(job)
                    output = request('POST', '/v1/translate/'+job+'/image').content
                    report = dict(regions=len(status['result'].get('translations', [])), job=job)
                if output is not None:
                    decoded = Image.open(io.BytesIO(output)); decoded.load()
                    assert decoded.size == source.size
                report.update(pipeline=pipeline, iteration=iteration, seconds=time.perf_counter()-started)
                reports.append(report); print(json.dumps(report), flush=True)
        warm = {name: [r['seconds'] for r in reports if r['pipeline'] == name and r['iteration'] > 0] for name in ('live', 'manga')}
        medians = {name: statistics.median(values) for name, values in warm.items()}
        summary = dict(medians=medians, live_to_manga_ratio=medians['live']/medians['manga'],
                       patches_only=args.patches_only, fresh_pixels=args.fresh_pixels,
                       identical=args.identical, identical_encoding='original file' if args.identical else None, reports=reports)
        folder = root/'evidence/speed'; folder.mkdir(parents=True, exist_ok=True)
        (folder/(args.label+'.json')).write_text(json.dumps(summary, indent=2))
        print(json.dumps({k: summary[k] for k in ('medians', 'live_to_manga_ratio')}), flush=True)
    finally:
        request('POST', '/SetInpaintMode', json={'mode': previous_mode})


if __name__ == '__main__': main()
