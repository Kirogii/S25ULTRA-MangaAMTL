import sys
import types
import unittest
import asyncio
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / "app/src/main/python"))
import samsung_translation

class SamsungTranslationTest(unittest.TestCase):
    def test_paragraph_batch_maps_results_and_primes_individual_cache(self):
        calls = []
        def generate(text):
            calls.append(text)
            return '<<<000>>>\none\n\n<<<001>>>\ntwo'
        bridge = types.SimpleNamespace(samsungEnabled=lambda: True, samsungTranslate=generate,
            samsungBeginBatch=lambda: None, samsungEndBatch=lambda: None)
        module = types.SimpleNamespace(app=types.SimpleNamespace(get=lambda *a: lambda f: f, post=lambda *a: lambda f: f),
            Request=object, logging=types.SimpleNamespace(info=lambda *a: None), qwen_translate=lambda *a: '',
            qwen_translate_batch=lambda *a: [], _validated_translation=lambda source, result, target: result)
        samsung_translation.install(module, bridge)
        self.assertEqual(module.qwen_translate_batch(['一', '二', '一', '123']), ['one', 'two', 'one', ''])
        self.assertEqual(module.qwen_translate('二'), 'two')
        self.assertEqual(len(calls), 1)

    def test_corrupted_paragraph_ids_fall_back_without_crossing_regions(self):
        calls = []
        def generate(text):
            calls.append(text)
            return {'一': 'one', '二': 'two'}.get(text, '<<<001>>>\ntwo\n<<<000>>>\none')
        bridge = types.SimpleNamespace(samsungEnabled=lambda: True, samsungTranslate=generate,
            samsungBeginBatch=lambda: None, samsungEndBatch=lambda: None)
        module = types.SimpleNamespace(app=types.SimpleNamespace(get=lambda *a: lambda f: f, post=lambda *a: lambda f: f),
            Request=object, logging=types.SimpleNamespace(info=lambda *a: None), qwen_translate=lambda *a: '',
            qwen_translate_batch=lambda *a: [], _validated_translation=lambda source, result, target: result)
        samsung_translation.install(module, bridge)
        self.assertEqual(module.qwen_translate_batch(['一', '二']), ['one', 'two'])
        self.assertEqual(calls[1:], ['一', '二'])

    def test_batch_releases_hidden_display_on_error(self):
        calls = []
        def fail(text): raise RuntimeError('Samsung unavailable')
        bridge = types.SimpleNamespace(samsungEnabled=lambda: True, samsungTranslate=fail,
            samsungBeginBatch=lambda: calls.append('begin'), samsungEndBatch=lambda: calls.append('end'))
        module = types.SimpleNamespace(app=types.SimpleNamespace(get=lambda *a: lambda f: f, post=lambda *a: lambda f: f),
            Request=object, logging=types.SimpleNamespace(info=lambda *a: None), qwen_translate=lambda *a: '',
            qwen_translate_batch=lambda *a: [], _validated_translation=lambda source, result, target: result)
        samsung_translation.install(module, bridge)
        with self.assertRaises(RuntimeError): module.qwen_translate_batch(['一'])
        self.assertEqual(calls, ['begin', 'end'])

    def test_repeats_and_english_do_not_wait_or_redraw(self):
        calls = []
        def generate(text):
            calls.append(text)
            return "hello" if text == "こんにちは" else text
        bridge = types.SimpleNamespace(samsungEnabled=lambda: True, samsungTranslate=generate)
        module = types.SimpleNamespace(app=types.SimpleNamespace(get=lambda *a: lambda f: f, post=lambda *a: lambda f: f),
            Request=object, logging=types.SimpleNamespace(info=lambda *a: None), qwen_translate=lambda *a: "",
            qwen_translate_batch=lambda *a: [], _validated_translation=lambda source, result, target: result)
        samsung_translation.install(module, bridge)
        self.assertEqual(module.qwen_translate("こんにちは"), "hello")
        self.assertEqual(module.qwen_translate("こんにちは"), "hello")
        self.assertEqual(calls, ["こんにちは"])
        self.assertEqual(module.qwen_translate("English only"), "")
        self.assertEqual(module.qwen_translate("English\n  only"), "")
        self.assertEqual(module.qwen_translate("123!?"), "")
        self.assertEqual(len(calls), 2)

    def test_settings_validation_and_busy_job(self):
        routes = {}
        app = types.SimpleNamespace(get=lambda path: lambda f: routes.setdefault(path, f),
            post=lambda path: lambda f: routes.setdefault(path, f))
        class HTTPError(Exception):
            def __init__(self, status, detail): self.status, self.detail = status, detail
        bridge = types.SimpleNamespace(enabled=False, samsungEnabled=lambda: bridge.enabled,
            samsungSetEnabled=lambda value: setattr(bridge, "enabled", value))
        module = types.SimpleNamespace(app=app, Request=object, HTTPException=HTTPError, asyncio=asyncio,
            _job_lock=asyncio.Lock(), _jobs={}, _llm_executor=None,
            qwen_translate=lambda *a: "", qwen_translate_batch=lambda *a: [])
        samsung_translation.install(module, bridge)
        async def run():
            async def body(): return {"enabled": "false"}
            request = types.SimpleNamespace(json=body)
            with self.assertRaises(HTTPError) as error: await routes['/v1/samsung/settings'](request)
            self.assertEqual(error.exception.status, 400)
            async def invalid_shape(): return []
            request.json = invalid_shape
            with self.assertRaises(HTTPError) as error: await routes['/v1/samsung/settings'](request)
            self.assertEqual(error.exception.status, 400)
            async def valid(): return {"enabled": True}
            request.json = valid
            module._jobs['page'] = {"status": "processing"}
            with self.assertRaises(HTTPError) as error: await routes['/v1/samsung/settings'](request)
            self.assertEqual(error.exception.status, 409)
            self.assertFalse(bridge.enabled)
            module._jobs.clear()
            self.assertTrue((await routes['/v1/samsung/settings'](request))['enabled'])
        asyncio.run(run())

    def test_selection_validation_and_order(self):
        bridge = types.SimpleNamespace(enabled=False, samsungEnabled=lambda: bridge.enabled,
            samsungTranslate=lambda text: {"一": "one", "二": "two"}[text],
            samsungBeginBatch=lambda: None, samsungEndBatch=lambda: None)
        app = types.SimpleNamespace(get=lambda *a: lambda f: f, post=lambda *a: lambda f: f)
        module = types.SimpleNamespace(app=app, Request=object,
            logging=types.SimpleNamespace(info=lambda *a: None),
            qwen_translate=lambda *a: "qwen", qwen_translate_batch=lambda *a: ["qwen"],
            _validated_translation=lambda source, result, target: result)
        samsung_translation.install(module, bridge)
        self.assertEqual(module.qwen_translate("一"), "qwen")
        self.assertEqual(module.qwen_translate_batch(["一"]), ["qwen"])
        bridge.enabled = True
        self.assertEqual(module.qwen_translate_batch(["二", "", "一"]), ["two", "", "one"])
        with self.assertRaises(ValueError): module.qwen_translate("一", "fr")
        module._validated_translation = lambda *a: ""
        with self.assertRaises(ValueError): module.qwen_translate("一")

if __name__ == "__main__": unittest.main()
