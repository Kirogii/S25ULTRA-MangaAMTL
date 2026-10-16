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

    def test_delayed_box_cannot_span_a_changed_section(self):
        tracker = Tracker()
        self.track(tracker,self.screen())
        token = tracker.begin('[0,0,1,1]')
        changed = self.screen().copy()
        changed[120:150,:100] = 0
        self.track(tracker,changed)
        response = dict(width=200,height=360,items=[dict(bbox=[20,140,80,180],overlay='stale')])
        self.assertEqual(json.loads(tracker.finish(token,json.dumps(response)))['add'],[])
        update = self.track(tracker,changed)
        self.assertIsNotNone(update['dirty'])
        self.assertLessEqual(update['dirty'][1],140/360)
        self.assertGreaterEqual(update['dirty'][3],180/360)

    def test_identical_overlap_does_not_replace_visible_overlay(self):
        tracker = Tracker()
        ids,response = self.fill(tracker)
        token = tracker.begin('[0,0,1,1]')
        result = json.loads(tracker.finish(token,json.dumps(response)))
        self.assertEqual(result['remove'],[])
        self.assertEqual(result['add'],[])
        self.assertCountEqual(tracker.items,ids)
        self.assertEqual(len(tracker.history),1,'Identical overlap must not duplicate screenshot history')

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

    def test_identical_frame_skips_flow_but_keeps_untranslated_work(self):
        from unittest.mock import patch
        tracker = Tracker()
        self.track(tracker,self.screen())
        with patch('live_tracking.cv2.calcOpticalFlowPyrLK', side_effect=AssertionError('Static frame used optical flow')):
            update = self.track(tracker,self.screen())
        self.assertIsNotNone(update['dirty'], 'Skipping motion must not skip OCR for untranslated pixels')
        ids,_ = self.fill(tracker)
        with patch('live_tracking.cv2.calcOpticalFlowPyrLK', side_effect=AssertionError('Static frame used optical flow')):
            update = self.track(tracker,self.screen())
        self.assertIsNone(update['dirty'])
        self.assertCountEqual([item['id'] for item in update['move']],ids)

    def test_scroll_back_restores_offscreen_text_without_ocr(self):
        tracker = Tracker()
        ids, _ = self.fill(tracker)
        for scroll in range(20, 221, 20):
            self.track(tracker, self.screen(scroll))
        self.assertNotIn(ids[1], tracker.items)
        restored = []
        for scroll in range(200, -1, -20):
            update = self.track(tracker, self.screen(scroll))
            restored.extend(item['id'] for item in update['add'])
        self.assertIn(ids[1], restored)
        self.assertAlmostEqual(tracker.items[ids[1]][1], 140/360, delta=.015)
        self.assertIsNone(update['dirty'], 'Previously captured screen should not require OCR again')

    def test_changed_text_is_not_restored_from_neighboring_tile(self):
        tracker = Tracker()
        ids, _ = self.fill(tracker)
        for scroll in range(20, 221, 20):
            self.track(tracker, self.screen(scroll))
        changed = self.screen().copy()
        changed[140:170, 20:80] = 0
        update = self.track(tracker, changed)
        self.assertNotIn(ids[1], tracker.items)
        self.assertIsNotNone(update['dirty'])

    def test_repeated_text_lines_do_not_alias_during_fast_scroll(self):
        import cv2
        body = np.full((1600, 240), 245, np.uint8)
        for y in range(30, 1600, 45):
            cv2.putText(body, f'Line {y} test words', (12, y), cv2.FONT_HERSHEY_SIMPLEX, .5, 30, 1, cv2.LINE_AA)
        def screen(offset):
            return np.concatenate([np.full((40,240),90,np.uint8), body[offset:offset+320], np.full((40,240),110,np.uint8)])
        for offset in [15, 40, 80, 120]:
            with self.subTest(offset=offset):
                tracker = Tracker()
                tracker.track(screen(0).tobytes(), 240, 400)
                serial = tracker.begin('[0,0,1,1]')
                added = json.loads(tracker.finish(serial, json.dumps(dict(width=240,height=400,
                    items=[dict(bbox=[10,145,200,180],overlay='text')]))))['add']
                key = added[0]['id']
                tracker.track(screen(offset).tobytes(), 240, 400)
                self.assertIn(key, tracker.items)
                self.assertAlmostEqual(tracker.items[key][1]*400, 145-offset, delta=2)
                delayed = Tracker()
                delayed.track(screen(0).tobytes(), 240, 400)
                token = delayed.begin('[0,0,1,1]')
                delayed.track(screen(offset).tobytes(), 240, 400)
                late = json.loads(delayed.finish(token, json.dumps(dict(width=240,height=400,
                    items=[dict(bbox=[10,145,200,180],overlay='text')]))))['add']
                self.assertEqual(len(late), 1, 'Still-visible delayed text must be accepted')
                self.assertAlmostEqual(late[0]['rect'][1]*400, 145-offset, delta=2)

    def test_resize_clears_old_geometry_and_rejects_inflight_result(self):
        tracker = Tracker()
        ids, response = self.fill(tracker)
        serial = tracker.begin('[0,0,1,1]')
        rotated = self.screen().T.copy()
        update = json.loads(tracker.track(rotated.tobytes(), 360, 200))
        self.assertCountEqual(update['remove'], ids)
        self.assertEqual(update['move'], [])
        self.assertEqual(tracker.history, [])
        self.assertEqual(update['dirty'], [0., 0., 1., 1.])
        self.assertEqual(json.loads(tracker.finish(serial, json.dumps(response)))['add'], [])
        self.assertIsNone(tracker.pending)

    def test_screenshot_history_is_bounded(self):
        tracker = Tracker()
        self.fill(tracker)
        for _ in range(25):
            tracker.remember([[0, 0, 1, 1]])
        self.assertLessEqual(len(tracker.history), 16)

    def test_clipped_region_uses_panel_motion_instead_of_header(self):
        tracker = Tracker()
        self.track(tracker, self.screen(20))
        tracker.items['edge'] = [.1, 2/360, .4, 42/360]
        tracker.clips['edge'] = [0, 40/360, 1, 300/360]
        self.track(tracker, self.screen(40))
        self.assertNotIn('edge', tracker.items)

    def test_overlay_reconstruction_noise_does_not_repeat_ocr(self):
        tracker = Tracker()
        ids, _ = self.fill(tracker)
        noisy = self.screen().copy()
        noisy[140:170:3, 20:80:3] = 255-noisy[140:170:3, 20:80:3]
        update = self.track(tracker, noisy)
        self.assertIn(ids[1], tracker.items)
        self.assertIsNone(update['dirty'])

    def test_transient_bad_frames_do_not_hide_stationary_translation(self):
        tracker = Tracker()
        ids,_ = self.fill(tracker)
        clean = self.screen()
        corrupt = clean.copy()
        corrupt[140:170,20:80] = 0
        for _ in range(8):
            for image in (corrupt,clean,clean):
                update = self.track(tracker,image)
                self.assertIn(ids[1],tracker.items)
                self.assertNotIn(ids[1],update['remove'])
                self.assertFalse(update['add'],'A retained overlay must not be recreated')
        self.assertFalse(tracker.suspect)

    def test_changed_menu_label_invalidates_only_its_translation(self):
        import cv2
        before = np.full((360, 200), 245, np.uint8)
        after = before.copy()
        cv2.putText(before, 'Account', (20,160), cv2.FONT_HERSHEY_SIMPLEX, .6, 20, 1, cv2.LINE_AA)
        cv2.putText(after, 'Settings', (20,160), cv2.FONT_HERSHEY_SIMPLEX, .6, 20, 1, cv2.LINE_AA)
        tracker = Tracker()
        self.track(tracker, before)
        serial = tracker.begin('[0,0,1,1]')
        response = dict(width=200,height=360,items=[
            dict(bbox=[15,135,160,175],overlay='label'),
            dict(bbox=[15,320,160,350],overlay='fixed')])
        added = json.loads(tracker.finish(serial,json.dumps(response)))['add']
        label, fixed = [item['id'] for item in added]
        update = self.track(tracker, after)
        self.assertIn(label,tracker.items)
        self.track(tracker,after)
        update = self.track(tracker,after)
        self.assertIn(label, update['remove'])
        self.assertNotIn(label, tracker.items)
        self.assertIn(fixed, tracker.items)
        self.assertIsNotNone(update['dirty'])

    def test_fractional_scroll_is_not_a_changed_label(self):
        import cv2
        image = np.full((360,200),245,np.uint8)
        cv2.putText(image,'Account',(20,160),cv2.FONT_HERSHEY_SIMPLEX,.6,20,1,cv2.LINE_AA)
        for offset in [.25,.5,1.5,2.5]:
            with self.subTest(offset=offset):
                tracker = Tracker()
                self.track(tracker,image)
                token = tracker.begin('[0,0,1,1]')
                added = json.loads(tracker.finish(token,json.dumps(dict(width=200,height=360,
                    items=[dict(bbox=[15,135,160,175],overlay='label')]))))['add']
                moved = cv2.warpAffine(image,np.float32([[1,0,0],[0,1,-offset]]),(200,360),borderValue=245)
                self.track(tracker,moved)
                self.assertIn(added[0]['id'],tracker.items)
                self.assertAlmostEqual(tracker.items[added[0]['id']][1]*360,135-offset,delta=.5)
                delayed = Tracker()
                self.track(delayed,image)
                token = delayed.begin('[0,0,1,1]')
                self.track(delayed,moved)
                late = json.loads(delayed.finish(token,json.dumps(dict(width=200,height=360,
                    items=[dict(bbox=[15,135,160,175],overlay='label')]))))['add']
                self.assertEqual(len(late),1,'Fractional motion must not reject a valid delayed result')

    def test_manga_artwork_keeps_visible_regions_when_direction_changes(self):
        from PIL import Image
        page = np.asarray(Image.open(Path(__file__).parent.parent/'Images/Raw.png').convert('L').resize((240,345)))
        rng = np.random.default_rng(12)
        body = np.concatenate([page,rng.integers(0,256,(600,240),dtype=np.uint8)])
        top = rng.integers(0,256,(40,240),dtype=np.uint8)
        bottom = rng.integers(0,256,(40,240),dtype=np.uint8)
        def screen(offset): return np.concatenate([top,body[offset:offset+280],bottom])
        boxes = [[814,505,932,733],[467,621,550,760],[91,617,154,773],
                 [487,195,568,385],[495,841,567,936],[815,1015,870,1155]]
        items = [dict(bbox=[int(a*240/1010),int(b*345/1450)+40,int(c*240/1010),int(d*345/1450)+40],
                      overlay='manga') for a,b,c,d in boxes]
        tracker = Tracker()
        def track_manga(image): return json.loads(tracker.track(image.tobytes(),240,360))
        track_manga(screen(0))
        token = tracker.begin('[0,0,1,1]')
        added = json.loads(tracker.finish(token,json.dumps(dict(width=240,height=360,items=items))))['add']
        for offset in [10,30,60,90,130,180,240,180,130,90,60,30,10,0]:
            track_manga(screen(offset))
            for item, source in zip(added,items):
                box = source['bbox']
                if min(320,box[3]-offset)-max(40,box[1]-offset) > 8:
                    self.assertIn(item['id'],tracker.items,(offset,box))
                if item['id'] in tracker.items:
                    self.assertAlmostEqual(tracker.items[item['id']][1]*360,box[1]-offset,delta=2)

    def test_two_panels_scroll_independently(self):
        rng = np.random.default_rng(14)
        left = rng.integers(0,256,(900,100),dtype=np.uint8)
        right = rng.integers(0,256,(900,100),dtype=np.uint8)
        def screen(a,b): return np.concatenate([left[a:a+360],right[b:b+360]],axis=1)
        tracker = Tracker()
        self.track(tracker,screen(0,0))
        token = tracker.begin('[0,0,1,1]')
        items = [dict(bbox=[10,140,90,180],overlay='left'),dict(bbox=[110,140,190,180],overlay='right')]
        added = json.loads(tracker.finish(token,json.dumps(dict(width=200,height=360,items=items))))['add']
        for a,b in [(20,40),(40,60),(20,80),(0,40),(0,0)]:
            self.track(tracker,screen(a,b))
            for item,offset in zip(added,[a,b]):
                self.assertIn(item['id'],tracker.items)
                self.assertAlmostEqual(tracker.items[item['id']][1]*360,140-offset,delta=2)

    def test_horizontal_scroll_clips_text_at_fixed_sidebar(self):
        rng = np.random.default_rng(17)
        body = rng.integers(0,256,(360,900),dtype=np.uint8)
        sidebar = rng.integers(0,256,(360,20),dtype=np.uint8)
        def screen(offset): return np.concatenate([sidebar,body[:,offset:offset+180]],axis=1)
        tracker = Tracker()
        self.track(tracker,screen(0))
        token = tracker.begin('[0,0,1,1]')
        added = json.loads(tracker.finish(token,json.dumps(dict(width=200,height=360,
            items=[dict(bbox=[22,140,62,180],overlay='edge')]))))['add']
        key = added[0]['id']
        self.track(tracker,screen(20))
        self.assertIn(key,tracker.items)
        self.assertAlmostEqual(tracker.items[key][0]*200,2,delta=2)
        self.assertAlmostEqual(tracker.clips[key][0]*200,20,delta=2)

    def test_repeated_scroll_sessions_do_not_accumulate_drift_or_coverage(self):
        tracker = Tracker()
        ids,_ = self.fill(tracker)
        for _ in range(8):
            for offset in list(range(5,101,5))+list(range(95,-1,-5)):
                self.track(tracker,self.screen(offset))
                self.assertIn(ids[1],tracker.items)
                self.assertAlmostEqual(tracker.items[ids[1]][1]*360,140-offset,delta=2)
                self.assertLessEqual(len(tracker.coverage),64)
                self.assertIn(ids[2],tracker.items)
                self.assertAlmostEqual(tracker.items[ids[2]][1]*360,335,delta=2)


if __name__ == '__main__': unittest.main()
