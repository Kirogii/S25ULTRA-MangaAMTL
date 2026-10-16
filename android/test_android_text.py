"""Compare cached measurements with the original layout algorithm."""
import ast
from pathlib import Path
import re
import sys
from types import SimpleNamespace
import unittest
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).parent / 'app/src/main/python'))
import android_text


class TextTests(unittest.TestCase):
    def test_original_layouts_preserved_with_fewer_measurements(self):
        root = Path(__file__).parent.parent
        names = {'_normalize_text_for_wrapping', '_break_long_word', 'wrap_text',
                 '_measure_block', 'fit_font_and_wrap'}
        tree = ast.parse((root / 'app.py').read_text(encoding='utf-8'))
        tree.body = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
        scope = dict(re=re, ImageFont=ImageFont)
        exec(compile(tree, '<original layout>', 'exec'), scope)
        original = scope['fit_font_and_wrap']
        module = SimpleNamespace(fit_font_and_wrap=original, clear_font_cache=lambda: None)
        android_text.install(module)
        # The upstream function refers to its own font cache through its globals.
        scope['fit_font_and_wrap'] = module.fit_font_and_wrap
        draw = ImageDraw.Draw(Image.new('RGB', (400, 400)))
        calls = []
        def length(*args, **kwargs):
            calls.append(1)
            return draw.textlength(*args, **kwargs)
        measured = SimpleNamespace(textlength=length, textbbox=draw.textbbox)
        font = 'C:/Windows/Fonts/arial.ttf'
        for text, width, height, vertical in [
            ('I want to build it with my own hands.', 83, 139, False),
            ('word word word word', 100, 100, False),
            ('supercalifragilisticexpialidocious', 20, 40, False),
            ('', 80, 80, False), ('ABCD ABCD', 80, 80, True),
        ]:
            with self.subTest(text=text, vertical=vertical):
                options = dict(font_path=font, min_size=10, max_size=96, is_vertical=vertical)
                calls.clear()
                expected = original(measured, text, width, height, **options)
                original_count = len(calls)
                calls.clear()
                actual = module.fit_font_and_wrap(measured, text, width, height, **options)
                self.assertEqual(actual, expected)
                self.assertLessEqual(len(calls), original_count)
                if text.startswith('word'):
                    self.assertLess(len(calls), original_count)
                calls.clear()
                self.assertEqual(module.fit_font_and_wrap(measured, text, width, height, **options), expected)
                self.assertEqual(len(calls), 0, 'An unchanged completed layout must skip measurement')
                actual[1].append('caller mutation')
                self.assertEqual(module.fit_font_and_wrap(measured, text, width, height, **options), expected)
                module.clear_font_cache()
                calls.clear()
                self.assertEqual(module.fit_font_and_wrap(measured, text, width, height, **options), expected)
                if text.strip(): self.assertGreater(len(calls), 0, 'Font changes must invalidate completed layouts')


if __name__ == '__main__':
    unittest.main()
