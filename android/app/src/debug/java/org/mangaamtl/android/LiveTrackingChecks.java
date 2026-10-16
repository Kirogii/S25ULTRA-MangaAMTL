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
                tracker.track(screen(20).tobytes(), 200, 360)
                assert half in tracker.items
                assert abs(tracker.items[half][1]-22/360) < .015
                assert abs(tracker.items[fixed][1]-335/360) < .01
                started = time.perf_counter()
                for _ in range(10):
                    state = json.loads(tracker.track(screen(20).tobytes(), 200, 360))
                    assert fixed in tracker.items
                stable_ms = (time.perf_counter()-started)*100
                for offset in range(40, 221, 20):
                    tracker.track(screen(offset).tobytes(), 200, 360)
                assert half not in tracker.items, ('Offscreen region was not hidden', tracker.items.get(half), tracker.clips.get(half))
                restored = []
                for offset in range(200, -1, -20):
                    state = json.loads(tracker.track(screen(offset).tobytes(), 200, 360))
                    restored.extend(item['id'] for item in state['add'])
                assert half in restored and half in tracker.items, ('Restore failed', restored, list(tracker.items))
                assert state['dirty'] is None, ('Restored screen requested OCR', state['dirty'])
                report = json.dumps(dict(passed=True, stable_track_ms=stable_ms,
                    partial_region_visible=True, bottom_bar_fixed=True, offscreen_restore_without_ocr=True))
                """, scope);
            result.putString("result", scope.callAttr("get", "report").toString());
            finish(0, result);
        } catch (Exception | AssertionError error) { result.putString("error", error.toString()); finish(1, result); }
    }
}
