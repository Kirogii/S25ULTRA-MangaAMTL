"""Guard exact upstream sizing/color/render methods (Kirogii/MangaAMTL a3da2588068f20c744d796ecdf79add1a09299e1)."""
import ast
import hashlib
from pathlib import Path
import unittest

EXPECTED = {
    'clean_text_for_font': '059387364076ac66036620b5c58e64d155dc7863e7cd75ecd30392d1b97cfee7',
    'detect_text_colors_batch': '70c914d933a32f78d8120d22aa8d0aa4196bfc49bb804691bcf190eddf54bc15',
    '_get_font_cached': '55061b918d2c3f6a02b1b337ecca56e38a8c0c57ec6ec73eec055a5fc3ff1001',
    'get_current_font': '4120104c758a4b11280179f4da5462639c11e3008082cbb712413b7c641fbcd5',
    '_normalize_text_for_wrapping': '9752a3d7ec25f16c7d009b7f5432a0aa3c3809f6e48007f182edefb2e6b1ac0d',
    '_break_long_word': 'ad65b543a022c98a195087c55403b0cae1e5419c897bc0e103818625e200ffe3',
    'wrap_text': 'aa441206968be3be2ee7304c9e88f84d6a8b267aee33f2587b5e6723b70c7425',
    '_measure_block': '20bd7d366b2923d801f79d47e0646b3cf0aa4be17bcb0511227b85fb72f823c9',
    'fit_font_and_wrap': '2d73d3d6f77cdd0542ab8d8f10d6bee166887ca372dd786762f882329f324d8a',
    '_render_translated_image': 'fbd493573eff32daf382890d2a2d10852fc9d39a66cc4c6a13466e1cd2a6f1d6',
}


class UpstreamRenderingTests(unittest.TestCase):
    def test_sizing_wrapping_colors_and_call_site_are_exact_upstream_source(self):
        source = (Path(__file__).parent.parent / 'app.py').read_text(encoding='utf-8')
        functions = {node.name: ast.get_source_segment(source, node) for node in ast.parse(source).body
                     if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
        # Blur intentionally changes color dispatch and mask preparation only.
        functions['_render_translated_image'] = functions['_render_translated_image'].replace(
            'all_box_colors = (phantom_text_colors_batch if _inpaint_mode == "blur" else detect_text_colors_batch)(orig_bgr, all_bboxes_for_color)',
            'all_box_colors = detect_text_colors_batch(orig_bgr, all_bboxes_for_color)').replace(
            'mask_dilate_kernel = 1 if inpaint_mode == "blur" else 3', 'mask_dilate_kernel = 3').replace(
            'if ocr_mode == "local_vision" and inpaint_mode != "blur":', 'if ocr_mode == "local_vision":')
        for name, expected in EXPECTED.items():
            with self.subTest(method=name):
                self.assertEqual(hashlib.sha256(functions[name].encode()).hexdigest(), expected)


if __name__ == '__main__': unittest.main()
