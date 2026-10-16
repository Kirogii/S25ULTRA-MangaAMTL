import ast
import asyncio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys
import threading
import types
import unittest

sys.path.insert(0, str(Path(__file__).parent / 'app/src/main/python'))
import android_lens


class LensTests(unittest.IsolatedAsyncioTestCase):
    def test_live_keeps_gui_text_outside_yolo_regions(self):
        blocks = [dict(text='manga', bbox=[0, 0, 10, 10]), dict(text='GUI label', bbox=[50, 50, 80, 70])]
        grouped = [dict(text='manga', bbox=[0, 0, 20, 20], bboxes=[[0, 0, 10, 10]])]
        self.assertEqual(android_lens.live_groups(lambda *args: grouped, blocks, [], (100, 100)), grouped+[blocks[1]])

    async def test_http_timing_preserves_response_and_errors_and_installs_once(self):
        calls, logs = [], []
        async def post(payload, session=None):
            calls.append((payload, session))
            if payload == 'failure': raise ValueError('Lens failed')
            return 'response'
        api = types.SimpleNamespace(request_handler=types.SimpleNamespace(post_raw=post))
        module = types.SimpleNamespace(get_lens_api=lambda: api,
            logging=types.SimpleNamespace(info=lambda *args: logs.append(args)))
        android_lens.install_http_timing(module)
        handler = module.get_lens_api().request_handler
        wrapper = handler.post_raw
        self.assertIs(module.get_lens_api().request_handler.post_raw, wrapper)
        self.assertEqual(await handler.post_raw('payload', session='session'), 'response')
        with self.assertRaisesRegex(ValueError, 'Lens failed'):
            await handler.post_raw('failure')
        self.assertEqual(calls, [('payload', 'session'), ('failure', None)])
        self.assertEqual(len(logs), 2)
        self.assertTrue(all(log[0] == '[Lens HTTP] %.3fs' and log[1] >= 0 for log in logs))

    async def test_lens_overlaps_detector_and_cleans_up_early_returns(self):
        tree = ast.parse('''async def google_lens_ocr(pil_img):
    result = await lens(pil_img)
    if not result:
        return []
    return _detect_yolo_text_boxes(pil_img)
''')
        android_lens.offload_detector(tree)
        started = threading.Event()
        release = threading.Event()
        def detect(image):
            started.set()
            if not release.wait(2):
                raise TimeoutError('Lens did not overlap detection')
            return [[1, 2, 3, 4]]
        async def lens(image):
            self.assertTrue(await asyncio.to_thread(started.wait, 1))
            release.set()
            return True
        with ThreadPoolExecutor(max_workers=1) as executor:
            scope = dict(asyncio=asyncio, lens=lens, _OCR_BOX_EXECUTOR=executor,
                         _detect_yolo_text_boxes=detect)
            exec(compile(tree, '<lens>', 'exec'), scope)
            self.assertEqual(await scope['google_lens_ocr']('page'), [[1, 2, 3, 4]])
            async def empty(image): return False
            scope['lens'] = empty
            def failed(image): raise ValueError('Unused detector error')
            scope['_detect_yolo_text_boxes'] = failed
            self.assertEqual(await scope['google_lens_ocr']('page'), [])
            async def failed_lens(image): raise RuntimeError('Lens unavailable')
            scope['lens'] = failed_lens
            with self.assertRaisesRegex(RuntimeError, 'Lens unavailable'):
                await scope['google_lens_ocr']('page')

    async def test_detector_runs_off_loop_and_propagates_result(self):
        tree = ast.parse('async def google_lens_ocr(pil_img):\n return _detect_yolo_text_boxes(pil_img)')
        android_lens.offload_detector(tree)
        loop_thread = threading.get_ident()
        def detect(image):
            self.assertNotEqual(threading.get_ident(), loop_thread)
            self.assertEqual(image, 'page')
            return [[1, 2, 3, 4]]
        with ThreadPoolExecutor(max_workers=1) as executor:
            scope = dict(asyncio=asyncio, _OCR_BOX_EXECUTOR=executor, _detect_yolo_text_boxes=detect)
            exec(compile(tree, '<lens>', 'exec'), scope)
            self.assertEqual(await scope['google_lens_ocr']('page'), [[1, 2, 3, 4]])
            def failed(image): raise ValueError('NPU failed')
            scope['_detect_yolo_text_boxes'] = failed
            with self.assertRaisesRegex(ValueError, 'NPU failed'):
                await scope['google_lens_ocr']('page')

    def test_current_upstream_only_changes_detector_call(self):
        tree = ast.parse((Path(__file__).parent.parent / 'app.py').read_text(encoding='utf-8'))
        before = {node.name: ast.dump(node) for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
        android_lens.offload_detector(tree)
        after = {node.name: ast.dump(node) for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
        self.assertEqual([name for name in before if before[name] != after[name]], ['google_lens_ocr'])


if __name__ == '__main__': unittest.main()
