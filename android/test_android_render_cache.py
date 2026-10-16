import sys
from pathlib import Path
import types
import unittest
sys.path.insert(0, str(Path(__file__).parent/'app/src/main/python'))
import android_render


class RenderCacheTests(unittest.IsolatedAsyncioTestCase):
    async def test_repeat_render_reuses_bytes_but_settings_and_content_invalidate(self):
        calls, inactive = [], set()
        def response(content, media_type='image/png'):
            return types.SimpleNamespace(body=content, status_code=200, media_type=media_type)
        async def original(job_id, job):
            calls.append(job_id)
            return response(('render-'+str(len(calls))).encode())
        async def active(job_id):
            if job_id in inactive: raise ValueError('Page is no longer active')
        module = types.SimpleNamespace(_render_translated_image=original, _ensure_job_active=active,
            _inpaint_mode='blur', _ocr_mode='lens', _current_font_path='font-one', _current_stroke_width=0,
            logging=types.SimpleNamespace(info=lambda *args: None), Response=response)
        android_render.install_image_cache(module)
        job = dict(request_fingerprint='image-one', target_lang='en', result=dict(translations=[dict(text='source', translation='translated')]))
        first = await module._render_translated_image('one', job)
        self.assertEqual((await module._render_translated_image('two', job)).body, first.body)
        self.assertEqual(len(calls), 1)
        inactive.add('gone')
        with self.assertRaisesRegex(ValueError, 'no longer active'): await module._render_translated_image('gone', job)
        for name, value in [('_current_stroke_width', 2), ('_current_font_path', 'font-two'),
                            ('_android_font_revision', 1), ('_inpaint_mode', 'none')]:
            before = len(calls); setattr(module, name, value)
            await module._render_translated_image('changed', job)
            self.assertEqual(len(calls), before+1)
        job['result']['translations'][0]['translation'] = 'different context'
        before = len(calls); await module._render_translated_image('text', job)
        self.assertEqual(len(calls), before+1)
        module._inpaint_mode = 'high'
        before = len(calls)
        await module._render_translated_image('high-one', job); await module._render_translated_image('high-two', job)
        self.assertEqual(len(calls), before+2, 'Neural model changes must not reuse a Blur render')
