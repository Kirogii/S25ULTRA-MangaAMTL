"""Exact-text/context cache misses, disabling cache, and aligned overlays."""
import asyncio
import io
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch
from PIL import Image, ImageFont
import numpy as np

sys.path.insert(0, str(Path(__file__).parent / 'app/src/main/python'))
import live_translation


class LiveTests(unittest.IsolatedAsyncioTestCase):
    async def test_context_changes_and_extended_sentences_do_not_reuse_fragments(self):
        routes, calls, drawn = {}, [], []
        state = dict(texts=['asd'])
        async def ocr(image, language, live=False):
            self.assertTrue(live)
            return [dict(text=text, bbox=[5, 5+i*25, 95, 25+i*25]) for i, text in enumerate(state['texts'])]
        def translate(texts, target, source):
            calls.append(tuple(texts))
            if texts == ['bank', 'bank']: return ['river bank', 'money bank']
            return ['a' if text == 'asd' and len(texts) == 1 else 'ab' for text in texts]
        def fit(draw, text, width, height, **kwargs):
            drawn.append(text)
            return (10, [text], [12], width, height)
        class HTTPError(Exception):
            def __init__(self, status, detail): self.status, self.detail = status, detail
        module = types.SimpleNamespace(
            app=types.SimpleNamespace(post=lambda path: lambda handler: routes.setdefault(path, handler)),
            logging=types.SimpleNamespace(info=lambda *args: None),
            UploadFile=object, File=lambda *a: None, Form=lambda value: value, HTTPException=HTTPError,
            get_ocr_results=ocr, _current_qwen_path='model-one', _llm_executor=None,
            _qwen_translate_batch_uncached=translate, _current_font_path='C:/Windows/Fonts/arial.ttf',
            pil_to_cv2=lambda image: np.asarray(image), cv2_to_pil=Image.fromarray,
            blur_inpaint=lambda image, mask: image,
            phantom_text_colors_batch=lambda image, boxes: [((0, 0, 0), (255, 255, 255)) for box in boxes],
            detect_text_colors_batch=lambda image, boxes: [((0, 0, 0), (255, 255, 255)) for box in boxes],
            fit_font_and_wrap=fit,
            get_font=lambda path, size: ImageFont.truetype(path, size))
        live_translation.install(module, types.SimpleNamespace(samsungEnabled=lambda: state.get('samsung', False)))
        data = io.BytesIO(); Image.new('RGB', (100, 100), 'white').save(data, 'PNG')
        async def read(limit): return data.getvalue()
        image = types.SimpleNamespace(read=read)
        handler = routes['/v1/live']
        async def run(enabled=True):
            return await handler(image, enabled, 'auto', 'en')
        first = await run()
        self.assertEqual(first['cache_hits'], 0)
        self.assertEqual((await run())['cache_hits'], 1)
        state['texts'] = ['asd fg']
        self.assertEqual((await run())['cache_hits'], 0)
        state['texts'] = ['asd', 'other context']
        self.assertEqual((await run())['cache_hits'], 0)
        self.assertEqual((await run())['cache_hits'], 2)
        module._current_qwen_path = 'model-two'
        self.assertEqual((await run())['cache_hits'], 0)
        self.assertEqual((await run(False))['cache_hits'], 0)
        self.assertEqual((await run(False))['cache_hits'], 0)
        self.assertEqual(len(calls), 6)
        state['texts'] = ['bank', 'bank']
        self.assertEqual((await run())['cache_hits'], 0)
        self.assertEqual(drawn[-2:], ['river bank', 'money bank'])
        self.assertEqual((await run())['cache_hits'], 2)
        self.assertEqual(drawn[-2:], ['river bank', 'money bank'])
        import base64
        overlay = Image.open(io.BytesIO(base64.b64decode(first['overlay'])))
        self.assertEqual(overlay.mode, 'RGBA')
        self.assertEqual(overlay.getpixel((0, 0))[3], 0)
        self.assertEqual(overlay.getpixel((5, 5))[3], 255)
        state['samsung'] = True
        local_calls = len(calls)
        with patch.object(live_translation, 'samsung_batch', return_value=['Samsung one', 'Samsung two']) as samsung:
            selected = await run()
            self.assertEqual(selected['translation_backend'], 'samsung')
            self.assertEqual(selected['cache_hits'], 0, 'Backend changes must invalidate translation reuse')
            samsung.assert_called_once()
        self.assertEqual(len(calls), local_calls, 'Samsung selection must not call Qwen')
        state['samsung'] = False
        self.assertEqual((await run())['translation_backend'], 'qwen')

    def test_blur_uses_existing_eraser_and_none_is_transparent(self):
        calls = []
        def erase(image, mask):
            calls.append(mask.copy())
            result = image.copy(); result[mask > 0] = 123
            return result
        module = types.SimpleNamespace(pil_to_cv2=np.asarray, cv2_to_pil=Image.fromarray, blur_inpaint=erase)
        page = Image.new('RGB', (40, 40), 'white')
        regions = [dict(bbox=[4, 4, 30, 30], bboxes=[[8, 8, 20, 20]])]
        blurred = live_translation.background_layer(module, page, regions, 'blur')
        self.assertEqual(blurred.getpixel((10, 10)), (123, 123, 123, 255))
        self.assertEqual(blurred.getpixel((5, 5))[3], 0, 'Only detected text subregions should be erased')
        plain = live_translation.background_layer(module, page, regions, 'none')
        self.assertEqual(plain.getchannel('A').getextrema(), (0, 0))
        self.assertEqual(len(calls), 1)

    def test_cache_is_bounded(self):
        cache = live_translation.TranslationCache(limit=2)
        for key in ('a', 'b', 'c'): cache.put(key, key)
        self.assertIsNone(cache.get('a'))
        self.assertEqual(cache.get('b'), 'b')

    def test_samsung_batch_retains_region_ids_and_releases_on_failure(self):
        events = []
        bridge = types.SimpleNamespace(samsungBeginBatch=lambda: events.append('begin'),
            samsungEndBatch=lambda: events.append('end'),
            samsungTranslate=lambda text: '<<<000>>>\na\n<<<001>>>\nab')
        module = types.SimpleNamespace(_validated_translation=lambda source, output, target: output)
        self.assertEqual(live_translation.samsung_batch(module, bridge, ['asd', 'asd fg'], 'en'), ['a', 'ab'])
        bridge.samsungTranslate = lambda text: 'broken identifiers'
        with self.assertRaises(ValueError): live_translation.samsung_batch(module, bridge, ['asd'], 'en')
        self.assertEqual(events, ['begin', 'end', 'begin', 'end'])


if __name__ == '__main__': unittest.main()
