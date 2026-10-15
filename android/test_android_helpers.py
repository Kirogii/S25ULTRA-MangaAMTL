"""Check font persistence and the short-request rendering adapter."""
import asyncio
import json
from pathlib import Path
import shutil
import sys
import tempfile
import threading
import types
import unittest
from unittest.mock import patch

from starlette.responses import JSONResponse, Response

sys.path.insert(0, str(Path(__file__).parent / 'app/src/main/python'))
import android_fonts
import android_render


class FontTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        (self.root / 'fonts').mkdir()
        self.incoming = self.root / 'fonts/import.part'
        self.settings = self.root / 'settings.json'
        self.settings.write_text(json.dumps({'ocr_mode': 'lens', 'font_path': 'old.ttf'}))

    def tearDown(self):
        self.temp.cleanup()

    def test_import_before_server_preserves_settings(self):
        shutil.copyfile('C:/Windows/Fonts/arial.ttf', self.incoming)
        with patch.dict(sys.modules, {'manga_android': None}):
            self.assertEqual(android_fonts.import_font(self.root, self.incoming, 'Custom.ttf'), 'Custom.ttf')
        settings = json.loads(self.settings.read_text())
        self.assertEqual(settings['ocr_mode'], 'lens')
        self.assertEqual(Path(settings['font_path']), self.root / 'fonts/Custom.ttf')
        self.assertFalse(self.incoming.exists())

    def test_import_selects_live_renderer(self):
        shutil.copyfile('C:/Windows/Fonts/arial.ttf', self.incoming)
        calls = []
        module = types.SimpleNamespace(__file__=str(self.root / 'app.py'), _font_config_lock=threading.Lock(),
            _current_font_path=Path('old.ttf'), clear_font_cache=lambda: calls.append('clear'))
        def save():
            calls.append('save')
            self.settings.write_text(json.dumps({'font_path': str(module._current_font_path)}))
        module._save_settings = save
        with patch.dict(sys.modules, {'manga_android': module}):
            android_fonts.import_font(self.root, self.incoming, 'Custom.ttf')
        self.assertEqual(module._current_font_path, self.root / 'fonts/Custom.ttf')
        self.assertEqual(calls, ['clear', 'save'])

    def test_invalid_font_does_not_replace_selection(self):
        self.incoming.write_bytes(b'not a font')
        with self.assertRaises(OSError):
            android_fonts.import_font(self.root, self.incoming, 'Bad.ttf')
        self.assertEqual(json.loads(self.settings.read_text())['font_path'], 'old.ttf')
        self.assertFalse((self.root / 'fonts/Bad.ttf').exists())

    def test_failed_save_restores_live_font(self):
        shutil.copyfile('C:/Windows/Fonts/arial.ttf', self.incoming)
        def fail_save():
            raise OSError('Storage unavailable')
        module = types.SimpleNamespace(__file__=str(self.root / 'app.py'), _font_config_lock=threading.Lock(),
            _current_font_path=Path('old.ttf'), clear_font_cache=lambda: None, _save_settings=fail_save)
        with patch.dict(sys.modules, {'manga_android': module}), self.assertRaises(OSError):
            android_fonts.import_font(self.root, self.incoming, 'Custom.ttf')
        self.assertEqual(module._current_font_path, Path('old.ttf'))
        self.assertFalse((self.root / 'fonts/Custom.ttf').exists())


class RenderTests(unittest.IsolatedAsyncioTestCase):
    async def test_history_bounds_release_delivered_images_and_preserve_live_jobs(self):
        from PIL import Image
        pages = [Image.new('RGB', (10, 10)) for _ in range(10)]
        jobs = {str(i): dict(status='completed', image=page, android_image_delivered=True, last_health=100) for i, page in enumerate(pages)}
        jobs['active'] = dict(status='processing', last_health=0)
        jobs['rendering'] = dict(status='completed', rendering=True, last_health=0)
        jobs['waiting-for-render'] = dict(status='completed', last_health=100)
        module = types.SimpleNamespace(_jobs=jobs)
        android_render.prune(module, now=101)
        self.assertNotIn('0', jobs)
        self.assertNotIn('1', jobs)
        for key in ('active', 'rendering', 'waiting-for-render', '9'): self.assertIn(key, jobs)
        with self.assertRaises(ValueError): pages[0].getpixel((0, 0))
        android_render.prune(module, now=300)
        self.assertEqual(set(jobs), {'active', 'rendering'})

    async def test_failed_render_releases_model_switch_guard(self):
        async def render(job_id):
            raise ValueError('Cannot render')
        module = types.SimpleNamespace(_jobs={'sample': {'status': 'completed'}}, JSONResponse=JSONResponse, get_translated_image=render)
        self.assertEqual((await android_render.image(module, 'sample')).status_code, 500)
        await asyncio.sleep(0)
        self.assertFalse(module._jobs['sample']['rendering'])
        self.assertEqual((await android_render.image(module, 'sample')).status_code, 500)

    async def test_render_starts_once_and_returns_cached_png(self):
        calls = []
        ready = asyncio.Event()
        async def render(job_id):
            calls.append(job_id)
            await ready.wait()
            return Response(b'PNG', media_type='image/png')
        module = types.SimpleNamespace(_jobs={'sample': {'status': 'completed'}}, JSONResponse=JSONResponse, get_translated_image=render)
        self.assertEqual((await android_render.image(module, 'sample')).status_code, 202)
        self.assertEqual((await android_render.image(module, 'sample')).status_code, 202)
        await asyncio.sleep(0)
        self.assertEqual(calls, ['sample'])
        ready.set()
        await asyncio.sleep(0)
        self.assertEqual((await android_render.image(module, 'sample')).body, b'PNG')
        self.assertEqual((await android_render.image(module, 'sample')).body, b'PNG')
        self.assertEqual((await android_render.image(module, 'missing')).status_code, 404)

    async def test_warm_render_returns_without_polling(self):
        async def render(job_id):
            await asyncio.sleep(.01)
            return Response(b'PNG', media_type='image/png')
        module = types.SimpleNamespace(_jobs={'sample': {'status': 'completed'}}, JSONResponse=JSONResponse, get_translated_image=render)
        self.assertEqual((await android_render.image(module, 'sample')).body, b'PNG')


if __name__ == '__main__':
    unittest.main()
