import sys
from pathlib import Path
import unittest
from PIL import Image
sys.path.insert(0, str(Path(__file__).parent / 'app/src/main/python'))
from live_ocr import pack, unpack, OcrCache


class TextCropTests(unittest.TestCase):
    def test_ocr_cache_requires_exact_pixels_language_and_profile(self):
        cache = OcrCache(); page = Image.new('RGB', (40, 40), 'white')
        key = cache.key(page, 'ja', 'live')
        regions = [dict(text='asd', bbox=[1, 2, 20, 30])]
        cache.put(key, regions)
        hit = cache.get(key); hit[0]['bbox'][0] = 99
        self.assertEqual(cache.get(key), regions, 'Callers must not mutate cached boxes')
        changed = page.copy(); changed.putpixel((10, 10), (0, 0, 0))
        self.assertIsNone(cache.get(cache.key(changed, 'ja', 'live')))
        self.assertIsNone(cache.get(cache.key(page, 'ko', 'live')))
        self.assertIsNone(cache.get(cache.key(page, 'ja', 'manga')))
        cache.clear(); self.assertIsNone(cache.get(key))

    def test_ocr_cache_is_bounded_and_does_not_cache_failed_empty_results(self):
        cache = OcrCache()
        cache.put('empty', []); self.assertIsNone(cache.get('empty'))
        for i in range(40): cache.put(i, [dict(text=str(i))])
        self.assertLessEqual(len(cache.values), 32)
        self.assertIsNone(cache.get(0))
    def test_sparse_text_is_packed_once_and_coordinates_return_to_screen(self):
        page = Image.new('RGB', (700, 1200), 'white')
        page.paste('black', (30, 600, 180, 640))
        packed, slots = pack(page, [[30, 600, 180, 640], [40, 610, 90, 630], [500, 900, 650, 950]])
        self.assertEqual(len(slots), 2, 'Overlapping YOLO and general detections must not duplicate text')
        self.assertLess(packed.width*packed.height, page.width*page.height*.2)
        source, box = slots[0]
        block = dict(text='sentence', bbox=[box[0]+10, box[1]+10, box[2]-10, box[3]-10])
        restored = unpack([block], slots)[0]
        self.assertEqual(restored['bbox'], [source[0]+10, source[1]+10, source[2]-10, source[3]-10])
        self.assertEqual(restored['text'], 'sentence')

    def test_dense_or_undetected_screen_falls_back_without_losing_labels(self):
        page = Image.new('RGB', (200, 300))
        for boxes in ([], [[0, 0, 200, 300]]):
            image, slots = pack(page, boxes)
            self.assertIs(image, page)
            self.assertIsNone(slots)
        regions = [dict(text='GUI', bbox=[1, 2, 30, 40])]
        self.assertEqual(unpack(regions, None), regions)

    def test_separator_text_is_not_mapped_to_unrelated_screen_position(self):
        page = Image.new('RGB', (700, 1200))
        _, slots = pack(page, [[30, 600, 180, 640]])
        self.assertEqual(unpack([dict(text='noise', bbox=[0, 0, 4, 4])], slots), [])


if __name__ == '__main__': unittest.main()
