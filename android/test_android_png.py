import io
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent / 'app/src/main/python'))
import android_png


class PngTests(unittest.TestCase):
    def test_lossless_and_explicit_compression_preserved(self):
        page = Image.open(Path(__file__).parent.parent / 'Images/Raw.png').convert('RGB')
        try:
            android_png.install()
            for options in ({}, {'compress_level': 9}):
                output = io.BytesIO()
                levels = []
                original = android_png.PngImagePlugin._save
                def checked(image, fp, filename):
                    levels.append(image.encoderinfo['compress_level'])
                    return original(image, fp, filename)
                with patch.object(android_png.PngImagePlugin, '_save', checked):
                    page.save(output, format='PNG', **options)
                decoded = Image.open(io.BytesIO(output.getvalue()))
                self.assertEqual(decoded.tobytes(), page.tobytes())
                self.assertEqual(levels, [options.get('compress_level', 1)])
        finally:
            Image.register_save('PNG', android_png.PngImagePlugin._save)


if __name__ == '__main__':
    unittest.main()
