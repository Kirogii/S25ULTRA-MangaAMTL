"""Regression for English passthrough followed by Japanese translation."""
import json
from pathlib import Path
import time
import requests


def main():
    client = requests.Session()
    client.trust_env = False
    for attempt in range(60):
        try:
            if client.get('http://127.0.0.1:17860/health', timeout=1).ok: break
        except requests.RequestException: pass
        time.sleep(.5)
    else: raise RuntimeError('Phone server did not become ready')
    sources = ['This is already an English manga page.', '今日はいい天気ですね。',
               'I want to build it with my own hands.', '自分の手で作りたい']
    results = []
    for index, source in enumerate(sources):
        started = time.perf_counter()
        response = client.post('http://127.0.0.1:17860/v1/samsung/check', json={'text': source}, timeout=40)
        if not response.ok: raise RuntimeError(response.text)
        response.raise_for_status()
        text = response.json()['text']
        seconds = time.perf_counter()-started
        print(json.dumps(dict(index=index, seconds=seconds, text=text)), flush=True)
        assert text == source if index % 2 == 0 else text != source
        assert seconds < 10, 'English or target-language recovery is still waiting'
        results.append(dict(source=source, text=text, seconds=seconds))
    target = Path(__file__).parent / 'evidence/speed/samsung-language-recovery.json'
    target.parent.mkdir(exist_ok=True)
    target.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding='utf-8')


if __name__ == '__main__':
    main()
