"""Exercise Blur helpers without importing heavyweight app/model dependencies."""
import ast
import asyncio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import threading
import unittest

import cv2
import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter


source = (Path(__file__).resolve().parents[1] / 'app.py').read_text(encoding='utf-8')
tree = ast.parse(source)
start = next(i for i, n in enumerate(tree.body) if isinstance(n, ast.FunctionDef) and n.name == 'median_rgba')
end = next(i for i, n in enumerate(tree.body) if isinstance(n, ast.AsyncFunctionDef) and n.name == 'inpaint_image_async')
ns = dict(Image=Image, ImageChops=ImageChops, ImageDraw=ImageDraw, ImageFilter=ImageFilter,
          RGB=tuple, RGBA=tuple, Rect=tuple, Quad=list, np=np, cv2=cv2,
          TEXT_COLOR_LIGHT=(255, 255, 255, 255), TEXT_COLOR_DARK=(0, 0, 0, 255),
          asyncio=asyncio, _inpaint_mode='blur', _inpaint_mode_lock=threading.Lock(),
          pil_to_cv2=lambda im: cv2.cvtColor(np.array(im), cv2.COLOR_RGB2BGR),
          cv2_to_pil=lambda im: Image.fromarray(cv2.cvtColor(im, cv2.COLOR_BGR2RGB)))
exec(compile(ast.Module(body=tree.body[start:end + 1], type_ignores=[]), '<blur>', 'exec'), ns)


class BlurTests(unittest.TestCase):
    def test_colors_and_erasure(self):
        for bg, fg in [(255, 0), (0, 255)]:
            image = np.full((80, 100, 3), bg, dtype=np.uint8)
            image[35:45, 40:60] = fg
            colors = ns['phantom_text_colors_batch'](image, [(30, 25, 70, 55)])
            self.assertEqual(colors, [((fg,) * 3, (bg,) * 3)])
            mask = np.zeros((80, 100), dtype=np.uint8)
            mask[25:55, 30:70] = 255
            expected = cv2.inpaint(image[17:63, 22:78], cv2.dilate(mask[17:63, 22:78],
                cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))), 3.0, cv2.INPAINT_TELEA)
            with ThreadPoolExecutor(1) as executor:
                ns['_inpaint_executor'] = executor
                result = asyncio.run(ns['inpaint_image_async'](image, mask))
            np.testing.assert_array_equal(result[17:63, 22:78], expected)
            np.testing.assert_array_equal(result[:17], image[:17])
            np.testing.assert_array_equal(ns['blur_inpaint'](image, np.zeros_like(mask)), image)


if __name__ == '__main__':
    unittest.main()
