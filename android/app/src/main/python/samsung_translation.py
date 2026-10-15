"""Use the Samsung UI bridge for translation while retaining original rendering."""
from collections import OrderedDict
import re
import time

def install(module, bridge):
    original_single, original_batch = module.qwen_translate, module.qwen_translate_batch
    module._qwen_translate_batch_uncached = original_batch

    cache = OrderedDict()
    def remember(text, result):
        cache[text] = result
        cache.move_to_end(text)
        while len(cache) > 512: cache.popitem(last=False)

    def samsung(text):
        if text in cache:
            cache.move_to_end(text)
            return cache[text]
        started = time.perf_counter()
        result = str(bridge.samsungTranslate(text))
        remember(text, result)
        module.logging.info("[Samsung] Translation %.3fs (%d characters)", time.perf_counter() - started, len(text))
        return result

    def translate(text, target_lang="en", ocr_lang="ja"):
        if not bridge.samsungEnabled():
            return original_single(text, target_lang, ocr_lang)
        if target_lang != "en":
            raise ValueError("Samsung bridge currently supports English output only")
        if not text.strip():
            return ""
        if not any(character.isalpha() for character in text):
            return ""
        result = samsung(text.strip())
        if result.strip() == text.strip():
            return ""  # Samsung identified English; preserve the existing lettering.
        validated = module._validated_translation(text, result, target_lang)
        if not validated:
            raise ValueError("Samsung translation failed target-language validation")
        return validated

    def batch(texts, target_lang="en", ocr_lang="ja", context_aware=False, name_map=None, llm=None):
        if not bridge.samsungEnabled():
            return original_batch(texts, target_lang, ocr_lang, context_aware, name_map, llm)
        bridge.samsungBeginBatch()
        try:
            missing = list(dict.fromkeys(text.strip() for text in texts
                if text.strip() not in cache and any(character.isalpha() for character in text)))
            joined = '\n\n'.join(f'<<<{index:03d}>>>\n{text}' for index, text in enumerate(missing))
            if 1 < len(missing) < 1000 and len(joined) <= 4000 and all('<<<' not in text and '>>>' not in text for text in missing):
                try:
                    started = time.perf_counter()
                    output = str(bridge.samsungTranslate(joined))
                    markers = list(re.finditer(r'<<<(\d{3})>>>', output))
                    if len(markers) != len(missing) or output[:markers[0].start()].strip() or [int(marker[1]) for marker in markers] != list(range(len(missing))):
                        raise ValueError('Samsung did not preserve paragraph identifiers')
                    parts = [output[marker.end():markers[index+1].start() if index+1 < len(markers) else len(output)].strip()
                             for index, marker in enumerate(markers)]
                    if not all(part and (part == source or module._validated_translation(source, part, target_lang)) for source, part in zip(missing, parts)):
                        raise ValueError('Samsung paragraph failed target-language validation')
                    for source, part in zip(missing, parts): remember(source, part)
                    module.logging.info('[Samsung] Page batch: %d regions, %.3fs', len(missing), time.perf_counter()-started)
                except Exception as error:
                    module.logging.info('[Samsung] Paragraph batch unavailable; using individual regions: %s', error)
            return [translate(text, target_lang, ocr_lang) for text in texts]
        finally:
            bridge.samsungEndBatch()

    module.qwen_translate, module.qwen_translate_batch = translate, batch

    @module.app.get("/v1/samsung/status")
    async def status():
        return {"enabled": bool(bridge.samsungEnabled()), "target": "en", "npu_verified": False}

    @module.app.post("/v1/samsung/settings")
    async def settings(request: module.Request):
        try:
            body = await request.json()
        except ValueError:
            raise module.HTTPException(400, "Invalid JSON settings")
        if not isinstance(body, dict):
            raise module.HTTPException(400, "Settings must be a JSON object")
        enabled = body.get("enabled")
        if type(enabled) is not bool:
            raise module.HTTPException(400, "enabled must be a boolean")
        async with module._job_lock:
            if any(job.get("status") in {"pending", "processing"} or job.get("rendering") for job in module._jobs.values()):
                raise module.HTTPException(409, "Wait for the current page to finish before changing translation engine")
            try:
                await module.asyncio.get_running_loop().run_in_executor(module._llm_executor, bridge.samsungSetEnabled, enabled)
            except Exception as error:
                raise module.HTTPException(503, str(error))
        return await status()

    @module.app.post("/v1/samsung/check")
    async def check(request: module.Request):
        try:
            body = await request.json()
        except ValueError:
            raise module.HTTPException(400, "Invalid JSON request")
        if not isinstance(body, dict):
            raise module.HTTPException(400, "Request must be a JSON object")
        text = body.get("text")
        if not isinstance(text, str) or not 1 <= len(text.strip()) <= 4000:
            raise module.HTTPException(400, "Text must contain 1–4000 characters")
        try:
            result = await module.asyncio.get_running_loop().run_in_executor(module._llm_executor, bridge.samsungTranslate, text.strip())
            return {"text": str(result)}
        except Exception as error:
            raise module.HTTPException(503, str(error))
