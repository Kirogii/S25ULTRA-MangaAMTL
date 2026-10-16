package org.mangaamtl.android;

import android.app.Instrumentation;
import android.os.Bundle;
import com.chaquo.python.*;
import com.chaquo.python.android.AndroidPlatform;

/** Real Android OpenCV wheel checks, without capturing a user's display. */
public final class LiveTrackingChecks extends Instrumentation {
    @Override public void onCreate(Bundle arguments) { super.onCreate(arguments); start(); }
    @Override public void onStart() {
        Bundle result = new Bundle();
        try {
            if (!AppUpdates.newer("v1.0.1", "1.0.0") || !AppUpdates.newer("v1.10.0", "1.9.0")
                    || AppUpdates.newer("v1.0.0", "1.0.0") || AppUpdates.newer("v0.9.9", "1.0.0")
                    || AppUpdates.newer("v1.1.0-beta", "1.0.0")) throw new AssertionError("Update version comparison failed");
            if (!Python.isStarted()) Python.start(new AndroidPlatform(getTargetContext()));
            Python python = Python.getInstance();
            PyObject scope = python.getBuiltins().callAttr("dict");
            python.getBuiltins().callAttr("exec", """
                import json, time
                import numpy as np
                from live_tracking import Tracker
                rng = np.random.default_rng(7)
                body = rng.integers(0, 256, (900, 200), dtype=np.uint8)
                top = rng.integers(0, 256, (40, 200), dtype=np.uint8)
                bottom = rng.integers(0, 256, (40, 200), dtype=np.uint8)
                def screen(scroll=0): return np.concatenate([top, body[scroll:scroll+280], bottom])
                tracker = Tracker()
                tracker.track(screen().tobytes(), 200, 360)
                serial = tracker.begin('[0,0,1,1]')
                response = dict(width=200, height=360, items=[
                    dict(bbox=[20,42,80,82], overlay='half'),
                    dict(bbox=[20,335,80,355], overlay='bottom')])
                added = json.loads(tracker.finish(serial, json.dumps(response)))['add']
                half, fixed = [item['id'] for item in added]
                repeat = tracker.begin('[0,0,1,1]')
                unchanged = json.loads(tracker.finish(repeat,json.dumps(response)))
                assert not unchanged['add'] and not unchanged['remove'], 'Identical overlap churned visible overlays'
                tracker.track(screen(20).tobytes(), 200, 360)
                assert half in tracker.items
                assert abs(tracker.items[half][1]-22/360) < .015
                assert abs(tracker.items[fixed][1]-335/360) < .01
                started = time.perf_counter()
                for _ in range(10):
                    state = json.loads(tracker.track(screen(20).tobytes(), 200, 360))
                    assert fixed in tracker.items
                stable_ms = (time.perf_counter()-started)*100
                started = time.perf_counter()
                for offset in list(range(25,101,5))+list(range(95,19,-5)):
                    tracker.track(screen(offset).tobytes(),200,360)
                moving_ms = (time.perf_counter()-started)*1000/32
                moving_budget_met = moving_ms < 30
                import cProfile, pstats, io
                profiler = cProfile.Profile()
                profiler.enable()
                for offset in list(range(25,61,5))+list(range(55,19,-5)):
                    tracker.track(screen(offset).tobytes(),200,360)
                profiler.disable()
                profile_output = io.StringIO()
                pstats.Stats(profiler,stream=profile_output).sort_stats('cumtime').print_stats(14)
                profile_report = profile_output.getvalue()
                for offset in range(40, 221, 20):
                    tracker.track(screen(offset).tobytes(), 200, 360)
                assert half not in tracker.items, ('Offscreen region was not hidden', tracker.items.get(half), tracker.clips.get(half))
                restored = []
                for offset in range(200, -1, -20):
                    state = json.loads(tracker.track(screen(offset).tobytes(), 200, 360))
                    restored.extend(item['id'] for item in state['add'])
                assert half in restored and half in tracker.items, ('Restore failed', restored, list(tracker.items))
                assert state['dirty'] is None, ('Restored screen requested OCR', state['dirty'])
                old_ids = list(tracker.items)
                serial = tracker.begin('[0,0,1,1]')
                rotated = screen().T.copy()
                state = json.loads(tracker.track(rotated.tobytes(), 360, 200))
                assert set(state['remove']) == set(old_ids)
                assert not state['move'] and not tracker.history
                assert state['dirty'] == [0., 0., 1., 1.]
                assert not json.loads(tracker.finish(serial, json.dumps(response)))['add']
                import cv2
                document = np.full((1600,240),245,np.uint8)
                for y in range(30,1600,45):
                    cv2.putText(document, f'Line {y} test words', (12,y), cv2.FONT_HERSHEY_SIMPLEX,.5,30,1,cv2.LINE_AA)
                def repeated_screen(offset):
                    return np.concatenate([np.full((40,240),90,np.uint8),document[offset:offset+320],np.full((40,240),110,np.uint8)])
                for offset in [15,40,80,120]:
                    probe = Tracker()
                    probe.track(repeated_screen(0).tobytes(),240,400)
                    token = probe.begin('[0,0,1,1]')
                    added = json.loads(probe.finish(token,json.dumps(dict(width=240,height=400,
                        items=[dict(bbox=[10,145,200,180],overlay='text')]))))['add']
                    key = added[0]['id']
                    probe.track(repeated_screen(offset).tobytes(),240,400)
                    assert key in probe.items, ('Fast scroll hid visible text',offset)
                    assert abs(probe.items[key][1]*400-(145-offset)) < 2, ('Line alias',offset,probe.items[key])
                    delayed = Tracker()
                    delayed.track(repeated_screen(0).tobytes(),240,400)
                    token = delayed.begin('[0,0,1,1]')
                    delayed.track(repeated_screen(offset).tobytes(),240,400)
                    late = json.loads(delayed.finish(token,json.dumps(dict(width=240,height=400,
                        items=[dict(bbox=[10,145,200,180],overlay='text')]))))['add']
                    assert len(late) == 1, ('Delayed visible text lost',offset)
                    assert abs(late[0]['rect'][1]*400-(145-offset)) < 2, ('Delayed line alias',offset,late)
                before = np.full((360,200),245,np.uint8)
                after = before.copy()
                cv2.putText(before,'Account',(20,160),cv2.FONT_HERSHEY_SIMPLEX,.6,20,1,cv2.LINE_AA)
                cv2.putText(after,'Settings',(20,160),cv2.FONT_HERSHEY_SIMPLEX,.6,20,1,cv2.LINE_AA)
                probe = Tracker()
                probe.track(before.tobytes(),200,360)
                token = probe.begin('[0,0,1,1]')
                labels = json.loads(probe.finish(token,json.dumps(dict(width=200,height=360,items=[
                    dict(bbox=[15,135,160,175],overlay='label'),dict(bbox=[15,320,160,350],overlay='fixed')]))))['add']
                changed, fixed_label = [item['id'] for item in labels]
                state = json.loads(probe.track(after.tobytes(),200,360))
                assert changed in probe.items
                probe.track(after.tobytes(),200,360)
                state = json.loads(probe.track(after.tobytes(),200,360))
                assert changed in state['remove'] and changed not in probe.items
                assert fixed_label in probe.items and state['dirty'] is not None
                for offset in [.25,.5,1.5,2.5]:
                    probe = Tracker()
                    probe.track(before.tobytes(),200,360)
                    token = probe.begin('[0,0,1,1]')
                    label = json.loads(probe.finish(token,json.dumps(dict(width=200,height=360,
                        items=[dict(bbox=[15,135,160,175],overlay='label')]))))['add'][0]['id']
                    shifted = cv2.warpAffine(before,np.float32([[1,0,0],[0,1,-offset]]),(200,360),borderValue=245)
                    probe.track(shifted.tobytes(),200,360)
                    assert label in probe.items, ('Fractional scroll invalidated label',offset)
                    assert abs(probe.items[label][1]*360-(135-offset)) < .5
                from PIL import Image
                page = np.asarray(Image.open('/data/user/0/org.mangaamtl.android/files/capture-benchmark.png').convert('L').resize((240,345)))
                rng = np.random.default_rng(12)
                manga_body = np.concatenate([page,rng.integers(0,256,(600,240),dtype=np.uint8)])
                header = rng.integers(0,256,(40,240),dtype=np.uint8)
                footer = rng.integers(0,256,(40,240),dtype=np.uint8)
                def manga_screen(offset): return np.concatenate([header,manga_body[offset:offset+280],footer])
                boxes = [[814,505,932,733],[467,621,550,760],[91,617,154,773],
                    [487,195,568,385],[495,841,567,936],[815,1015,870,1155]]
                items = [dict(bbox=[int(a*240/1010),int(b*345/1450)+40,int(c*240/1010),int(d*345/1450)+40],overlay='manga')
                    for a,b,c,d in boxes]
                probe = Tracker()
                probe.track(manga_screen(0).tobytes(),240,360)
                token = probe.begin('[0,0,1,1]')
                added = json.loads(probe.finish(token,json.dumps(dict(width=240,height=360,items=items))))['add']
                for offset in [10,30,60,90,130,180,240,180,130,90,60,30,10,0]:
                    probe.track(manga_screen(offset).tobytes(),240,360)
                    for item,source in zip(added,items):
                        box = source['bbox']
                        if min(320,box[3]-offset)-max(40,box[1]-offset)>8:
                            assert item['id'] in probe.items, ('Visible manga text lost',offset,box)
                        if item['id'] in probe.items:
                            assert abs(probe.items[item['id']][1]*360-(box[1]-offset))<2
                rng = np.random.default_rng(17)
                horizontal_body = rng.integers(0,256,(360,900),dtype=np.uint8)
                sidebar = rng.integers(0,256,(360,20),dtype=np.uint8)
                def sideways(offset): return np.concatenate([sidebar,horizontal_body[:,offset:offset+180]],axis=1)
                probe = Tracker()
                probe.track(sideways(0).tobytes(),200,360)
                token = probe.begin('[0,0,1,1]')
                edge = json.loads(probe.finish(token,json.dumps(dict(width=200,height=360,
                    items=[dict(bbox=[22,140,62,180],overlay='edge')]))))['add'][0]['id']
                probe.track(sideways(20).tobytes(),200,360)
                assert edge in probe.items
                assert abs(probe.items[edge][0]*200-2)<2
                assert abs(probe.clips[edge][0]*200-20)<2
                probe = Tracker()
                probe.track(screen(0).tobytes(),200,360)
                token = probe.begin('[0,0,1,1]')
                changed_section = screen(0).copy()
                changed_section[120:150,:100] = 0
                probe.track(changed_section.tobytes(),200,360)
                rejected = json.loads(probe.finish(token,json.dumps(dict(width=200,height=360,
                    items=[dict(bbox=[20,140,80,180],overlay='stale')]))))
                assert not rejected['add'], 'Stale delayed text crossed a changed section'
                state = json.loads(probe.track(changed_section.tobytes(),200,360))
                assert state['dirty'] is not None and state['dirty'][1]<=140/360 and state['dirty'][3]>=180/360
                soak = Tracker()
                soak.track(screen(0).tobytes(),200,360)
                token = soak.begin('[0,0,1,1]')
                entries = json.loads(soak.finish(token,json.dumps(dict(width=200,height=360,items=[
                    dict(bbox=[20,140,80,170],overlay='body'),dict(bbox=[20,335,80,355],overlay='fixed')]))))['add']
                body_key,fixed_key = [item['id'] for item in entries]
                max_drift,peak_coverage = 0.,0
                cycle_ms = []
                for cycle in range(8):
                    started = time.perf_counter()
                    for offset in list(range(5,101,5))+list(range(95,-1,-5)):
                        soak.track(screen(offset).tobytes(),200,360)
                        assert body_key in soak.items and fixed_key in soak.items
                        drift = abs(soak.items[body_key][1]*360-(140-offset))
                        max_drift = max(max_drift,drift)
                        peak_coverage = max(peak_coverage,len(soak.coverage))
                        assert drift<2 and abs(soak.items[fixed_key][1]*360-335)<2
                        assert len(soak.coverage)<=64
                    cycle_ms.append((time.perf_counter()-started)*1000/40)
                flicker = Tracker()
                clean = screen(0)
                flicker.track(clean.tobytes(),200,360)
                token = flicker.begin('[0,0,1,1]')
                kept = json.loads(flicker.finish(token,json.dumps(dict(width=200,height=360,
                    items=[dict(bbox=[20,140,80,170],overlay='stationary')]))))['add'][0]['id']
                inconsistent = clean.copy()
                inconsistent[140:170,20:80] = 0
                for cycle in range(8):
                    for image in (inconsistent,clean,clean):
                        state = json.loads(flicker.track(image.tobytes(),200,360))
                        assert kept in flicker.items and not state['remove'] and not state['add'], 'Stationary overlay flickered'
                assert not flicker.suspect
                report = json.dumps(dict(passed=True, transient_stationary_frames_keep_overlay=True, soak_frames=320, soak_max_drift=max_drift, soak_peak_coverage=peak_coverage, soak_cycle_ms=cycle_ms, delayed_cross_section_rejected=True, horizontal_sidebar_clipping=True, real_manga_scroll_reversal=True, changed_menu_label_invalidated=True, resize_invalidates_stale_results=True, repeated_line_fast_scroll=True, stable_track_ms=stable_ms, moving_track_ms=moving_ms, moving_budget_met=moving_budget_met,
                    partial_region_visible=True, bottom_bar_fixed=True, offscreen_restore_without_ocr=True))
                """, scope);
            result.putString("result", scope.callAttr("get", "report").toString());
            result.putString("profile", scope.callAttr("get", "profile_report").toString());
            finish(0, result);
        } catch (Exception | AssertionError error) { result.putString("error", error.toString()); finish(1, result); }
    }
}
