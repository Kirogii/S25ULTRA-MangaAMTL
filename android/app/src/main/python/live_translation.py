"""Screen text overlays with exact, context-scoped translation reuse."""
import asyncio
import base64
from collections import OrderedDict
import io
import re
import time
import numpy as np
from PIL import Image, ImageDraw


class TranslationCache:
    def __init__(self, limit=512):
        self.values = OrderedDict()
        self.limit = limit

    def get(self, key):
        if key not in self.values:
            return None
        self.values.move_to_end(key)
        return self.values[key]

    def put(self, key, value):
        self.values[key] = value
        self.values.move_to_end(key)
        while len(self.values) > self.limit:
            self.values.popitem(last=False)


def background_layer(module, page, regions, mode):
    if mode == 'none':
        return Image.new('RGBA', page.size)
    mask = np.zeros((page.height, page.width), np.uint8)
    for region in regions:
        for box in region.get('bboxes', [region['bbox']]):
            x1, y1, x2, y2 = [int(v) for v in box]
            mask[max(0, y1):min(page.height, y2), max(0, x1):min(page.width, x2)] = 255
    erased = module.blur_inpaint(module.pil_to_cv2(page), mask)
    layer = module.cv2_to_pil(erased).convert('RGBA')
    layer.putalpha(Image.fromarray(mask))
    return layer


def samsung_batch(module, bridge, texts, target):
    if target != 'en':
        raise ValueError('Samsung live translation supports English output')
    results = [''] * len(texts)
    pending = [(i, text) for i, text in enumerate(texts) if any(c.isalpha() for c in text)]
    bridge.samsungBeginBatch()
    try:
        while pending:
            group, size = [], 0
            while pending and size + len(pending[0][1]) + 16 <= 4000:
                item = pending.pop(0)
                group.append(item)
                size += len(item[1]) + 16
            if not group:
                raise ValueError('A screen text region exceeds Samsung’s 4000-character limit')
            if any('<<<' in text or '>>>' in text for _, text in group):
                raise ValueError('Screen text contains reserved translation markers')
            joined = '\n\n'.join(f'<<<{i:03d}>>>\n{text}' for i, (_, text) in enumerate(group))
            output = str(bridge.samsungTranslate(joined))
            markers = list(re.finditer(r'<<<(\d{3})>>>', output))
            if len(markers) != len(group) or [int(m[1]) for m in markers] != list(range(len(group))) or output[:markers[0].start()].strip():
                raise ValueError('Samsung did not preserve screen text identifiers')
            for i, ((index, source), marker) in enumerate(zip(group, markers)):
                text = output[marker.end():markers[i+1].start() if i+1 < len(markers) else len(output)].strip()
                if text == source:
                    continue
                translated = module._validated_translation(source, text, target)
                if not translated:
                    raise ValueError('Screen translation failed language validation')
                results[index] = translated
    finally:
        bridge.samsungEndBatch()
    return results


def install(module, bridge):
    cache = TranslationCache()
    lock = asyncio.Lock()

    @module.app.post('/v1/live')
    async def translate(image: module.UploadFile = module.File(...),
                        cache_enabled: bool = module.Form(True),
                        ocr_lang: str = module.Form('auto'),
                        target_lang: str = module.Form('en'),
                        background_mode: str = module.Form('blur')):
        async with lock:
            started = time.perf_counter()
            payload = await image.read(16_000_001)
            if len(payload) > 16_000_000:
                raise module.HTTPException(413, 'Screen image exceeds 16 MB')
            try:
                if background_mode not in {'blur', 'none'}:
                    raise module.HTTPException(400, 'Live background must be blur or none')
                page = Image.open(io.BytesIO(payload))
                if page.width * page.height > 12_000_000:
                    raise ValueError('Screen image exceeds 12 megapixels')
                page = page.convert('RGB')
                regions = await module.get_ocr_results(page, ocr_lang, live=True)
                regions = [r for r in regions if str(r.get('text', '')).strip() and r.get('bbox')]
                ocr_finished = time.perf_counter()
                texts = [r['text'].strip() for r in regions]
                samsung = bool(bridge.samsungEnabled())
                # Full ordered screen context prevents word/subsentence cache collisions.
                context = (ocr_lang, target_lang, samsung, str(module._current_qwen_path), tuple(texts))
                translated, misses, hits = [None] * len(texts), [], 0
                if not cache_enabled:
                    cache.values.clear()
                for i, text in enumerate(texts):
                    value = cache.get((context, i, text)) if cache_enabled else None
                    if value is None:
                        misses.append(i)
                    else:
                        translated[i] = value
                        hits += 1
                if misses:
                    loop = asyncio.get_running_loop()
                    # Translate the full screen together even when some entries hit.
                    # Bypass Samsung's page cache, which intentionally has no context key.
                    if samsung:
                        fresh = await loop.run_in_executor(module._llm_executor, samsung_batch, module, bridge, texts, target_lang)
                    else:
                        fresh = await loop.run_in_executor(module._llm_executor, module._qwen_translate_batch_uncached,
                                                           texts, target_lang, ocr_lang)
                    if len(fresh) != len(texts):
                        raise ValueError('Screen translations are not aligned with text regions')
                    for i in misses:
                        translated[i] = fresh[i]
                        if cache_enabled:
                            cache.put((context, i, texts[i]), fresh[i])
                translation_finished = time.perf_counter()
                rendered_regions = [r for r, text in zip(regions, translated) if text]
                overlay = background_layer(module, page, rendered_regions, background_mode)
                draw = ImageDraw.Draw(overlay)
                color_detector = module.phantom_text_colors_batch if background_mode == 'blur' else module.detect_text_colors_batch
                colors = color_detector(module.pil_to_cv2(page), [r['bbox'] for r in regions]) if regions else []
                for region, text, (foreground, background) in zip(regions, translated, colors):
                    if not text:
                        continue
                    x1, y1, x2, y2 = region['bbox']
                    size, lines, heights, _, _ = module.fit_font_and_wrap(draw, text, x2-x1, y2-y1,
                        font_path=str(module._current_font_path), min_size=8, max_size=96)
                    font = module.get_font(str(module._current_font_path), size)
                    y = y1 + max(0, ((y2-y1)-sum(heights))/2)
                    for line, height in zip(lines, heights):
                        width = draw.textlength(line, font=font)
                        draw.text((x1+max(0, ((x2-x1)-width)/2), y), line, font=font, fill=tuple(foreground)+(255,))
                        y += height
                output = io.BytesIO()
                overlay.save(output, format='PNG', compress_level=1)
                items = []
                for region, text in zip(regions, translated):
                    if text:
                        box = [int(v) for v in region['bbox']]
                        patch = io.BytesIO()
                        overlay.crop(tuple(box)).save(patch, format='PNG', compress_level=1)
                        items.append(dict(bbox=box, overlay=base64.b64encode(patch.getvalue()).decode('ascii')))
                module.logging.info('[Live] %s: %d regions, %d cache hits, OCR %.3fs, translation %.3fs, render %.3fs',
                    'samsung' if samsung else 'qwen', len(regions), hits, ocr_finished-started,
                    translation_finished-ocr_finished, time.perf_counter()-translation_finished)
                return dict(overlay=base64.b64encode(output.getvalue()).decode('ascii'),
                            width=page.width, height=page.height, regions=len(regions),
                            cache_hits=hits, seconds=time.perf_counter()-started, items=items,
                            background_mode=background_mode, translation_backend='samsung' if samsung else 'qwen',
                            ocr_seconds=ocr_finished-started, translation_seconds=translation_finished-ocr_finished)
            except module.HTTPException:
                raise
            except Exception as error:
                raise module.HTTPException(503, str(error))
