import ast
import asyncio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys
import threading
import unittest

sys.path.insert(0, str(Path(__file__).parent / 'app/src/main/python'))
import android_lens


class LensTests(unittest.IsolatedAsyncioTestCase):
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
