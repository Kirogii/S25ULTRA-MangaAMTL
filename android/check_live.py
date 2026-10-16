"""Verify the live endpoint with a known page, without capturing a user's screen."""
import base64
import io
import json
from pathlib import Path
import time
import requests
from PIL import Image


def main():
    client = requests.Session()
    client.trust_env = False
    base = 'http://127.0.0.1:17860'
    for _ in range(40):
        try:
            if client.get(base+'/health', timeout=1).ok: break
        except requests.RequestException: pass
        time.sleep(.5)
    else: raise RuntimeError('Phone server unavailable')
    root = Path(__file__).parent
    image = (root.parent / 'Images/Raw.png').read_bytes()
    reports = []
    samsung = client.get(base+'/v1/samsung/status', timeout=5).json()['enabled']
    for enabled in (True, True, False):
        started = time.perf_counter()
        response = client.post(base+'/v1/live', files={'image': ('screen.png', image, 'image/png')},
            data={'cache_enabled': str(enabled).lower(), 'ocr_lang': 'ja',
                  'background_mode': 'blur' if enabled else 'none'}, timeout=60)
        if not response.ok: raise RuntimeError(response.text)
        result = response.json()
        assert result['translation_backend'] == ('samsung' if samsung else 'qwen'), result
        assert result['background_mode'] == ('blur' if enabled else 'none'), result
        output = base64.b64decode(result.pop('overlay'))
        items = result.pop('items')
        assert items and all(len(item['bbox']) == 4 and item['overlay'] for item in items)
        result['items_count'] = len(items)
        overlay = Image.open(io.BytesIO(output))
        assert overlay.mode == 'RGBA' and overlay.size == (1010, 1450)
        assert overlay.getchannel('A').getextrema() == (0, 255)
        result.update(cache_enabled=enabled, total_seconds=time.perf_counter()-started)
        reports.append(result)
        print(json.dumps(result), flush=True)
        (root / 'evidence/speed' / f'live-overlay-{len(reports)}.png').write_bytes(output)
    assert reports[1]['cache_hits'] == reports[1]['regions'] > 0, reports
    assert reports[2]['cache_hits'] == 0, reports
    (root / 'evidence/speed/live-endpoint.json').write_text(json.dumps(reports, indent=2))


if __name__ == '__main__': main()
