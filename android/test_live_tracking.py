"""Scrolling regions remain attached and clipped; independent bars stay put."""
import json
from pathlib import Path
import sys
import unittest
import numpy as np

sys.path.insert(0, str(Path(__file__).parent / 'app/src/main/python'))
from live_tracking import Tracker, visible


class TrackingTests(unittest.TestCase):
    def setUp(self):
        random = np.random.default_rng(7)
        self.body = random.integers(0, 256, (900, 200), dtype=np.uint8)
        self.top = random.integers(0, 256, (40, 200), dtype=np.uint8)
        self.bottom = random.integers(0, 256, (40, 200), dtype=np.uint8)

    def screen(self, scroll=0, top=None):
        return np.concatenate([self.top if top is None else top, self.body[scroll:scroll+280], self.bottom])

    def track(self, tracker, image):
        return json.loads(tracker.track(image.tobytes(), 200, 360))

    def fill(self, tracker):
        self.track(tracker, self.screen())
        serial = tracker.begin('[0,0,1,1]')
        response = dict(width=200, height=360, items=[
            dict(bbox=[20, 42, 80, 82], overlay='half'),
            dict(bbox=[20, 140, 80, 170], overlay='body'),
            dict(bbox=[20, 335, 80, 355], overlay='bottom')])
        added = json.loads(tracker.finish(serial, json.dumps(response)))['add']
        return [item['id'] for item in added], response

    def test_partial_region_moves_while_bottom_bar_stays(self):
        tracker = Tracker()
        ids, _ = self.fill(tracker)
        update = self.track(tracker, self.screen(20))
        self.assertIn(ids[0], tracker.items, 'Partly visible old text must not disappear')
        self.assertAlmostEqual(tracker.items[ids[0]][1], 22/360, delta=.015)
        self.assertAlmostEqual(tracker.items[ids[1]][1], 120/360, delta=.015)
        self.assertAlmostEqual(tracker.items[ids[2]][1], 335/360, delta=.01)
        self.assertLess(tracker.clips[ids[0]][1], tracker.items[ids[0]][3])
        self.assertIsNotNone(update['dirty'], 'Newly exposed content must enter OCR')

    def test_top_menu_change_does_not_invalidate_bottom(self):
        tracker = Tracker()
        ids, _ = self.fill(tracker)
        changed = np.random.default_rng(12).integers(0, 256, self.top.shape, dtype=np.uint8)
        update = self.track(tracker, self.screen(top=changed))
        self.assertIn(ids[2], tracker.items)
        self.assertAlmostEqual(tracker.items[ids[2]][1], 335/360, delta=.01)
        self.assertIsNotNone(update['dirty'])
        self.assertLess(update['dirty'][3], .4)

    def test_async_result_moves_to_current_content_location(self):
        tracker = Tracker()
        self.track(tracker, self.screen())
        serial = tracker.begin('[0,0,1,1]')
        self.track(tracker, self.screen(12))
        response = dict(width=200, height=360, items=[dict(bbox=[20, 140, 80, 170], overlay='body')])
        result = json.loads(tracker.finish(serial, json.dumps(response)))['add']
        self.assertEqual(len(result), 1)
        self.assertAlmostEqual(result[0]['rect'][1], 128/360, delta=.02)

    def test_static_screen_has_no_refresh_and_offscreen_regions_are_removed(self):
        tracker = Tracker()
        ids, _ = self.fill(tracker)
        for _ in range(3):
            update = self.track(tracker, self.screen())
            self.assertIsNone(update['dirty'])
            self.assertFalse(update['remove'])
        for scroll in range(20, 181, 20): self.track(tracker, self.screen(scroll))
        self.assertNotIn(ids[1], tracker.items)
        self.assertIn(ids[2], tracker.items)
        self.assertTrue(visible([.1, -.1, .4, .1]))
        self.assertFalse(visible([.1, -.3, .4, -.1]))


if __name__ == '__main__': unittest.main()
