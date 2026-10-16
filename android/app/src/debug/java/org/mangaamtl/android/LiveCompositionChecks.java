package org.mangaamtl.android;

import android.app.Instrumentation;
import android.graphics.*;
import android.media.*;
import android.os.*;
import android.view.Surface;
import java.lang.reflect.*;
import java.util.*;
import com.chaquo.python.*;
import com.chaquo.python.android.AndroidPlatform;

/** Exercise the actual capture reconstruction against synthetic Canvas layers. */
public final class LiveCompositionChecks extends Instrumentation {
    @Override public void onCreate(Bundle arguments) { super.onCreate(arguments); start(); }
    @Override public void onStart() {
        Bundle result = new Bundle();
        try (ImageReader reader = ImageReader.newInstance(200, 360, PixelFormat.RGBA_8888, 2)) {
            int original = Color.rgb(180, 150, 110);
            Bitmap layer = Bitmap.createBitmap(200, 360, Bitmap.Config.ARGB_8888);
            Canvas canvas = new Canvas(layer);
            Bitmap lower = Bitmap.createBitmap(80, 72, Bitmap.Config.ARGB_8888); lower.eraseColor(Color.rgb(20, 50, 200));
            Bitmap upper = Bitmap.createBitmap(80, 72, Bitmap.Config.ARGB_8888); upper.eraseColor(Color.argb(128, 240, 210, 30));
            RectF first = new RectF(.1f, .2f, .5f, .4f), second = new RectF(.2f, .25f, .6f, .45f);
            Paint paint = new Paint(Paint.FILTER_BITMAP_FLAG);
            canvas.drawBitmap(lower, null, new RectF(20, 72, 100, 144), paint);
            canvas.drawBitmap(upper, null, new RectF(40, 90, 120, 162), paint);
            Surface surface = reader.getSurface();
            Canvas capture = surface.lockCanvas(null); capture.drawColor(original);
            paint.setAlpha(201); capture.drawBitmap(layer, 0, 0, paint); surface.unlockCanvasAndPost(capture);
            Image image = null;
            for (int i = 0; i < 100 && image == null; i++) { image = reader.acquireLatestImage(); if (image == null) SystemClock.sleep(10); }
            if (image == null) throw new AssertionError("Synthetic capture unavailable");
            try (Image frame = image) {
                LiveTranslationService service = new LiveTranslationService();
                Field generation = LiveTranslationService.class.getDeclaredField("generation"); generation.setAccessible(true);
                Field busy = LiveTranslationService.class.getDeclaredField("ocrBusy"); busy.setAccessible(true);
                Field retry = LiveTranslationService.class.getDeclaredField("retryAfter"); retry.setAccessible(true);
                Field connection = LiveTranslationService.class.getDeclaredField("activeConnection"); connection.setAccessible(true);
                final boolean[] disconnected = {false};
                java.net.HttpURLConnection pending = new java.net.HttpURLConnection(new java.net.URL("http://127.0.0.1/")) {
                    @Override public void disconnect() { disconnected[0] = true; }
                    @Override public boolean usingProxy() { return false; }
                    @Override public void connect() {}
                };
                generation.setInt(service, 4); busy.setBoolean(service, true); retry.setLong(service, Long.MAX_VALUE);
                connection.set(service, pending);
                Method invalidate = LiveTranslationService.class.getDeclaredMethod("invalidateWork"); invalidate.setAccessible(true);
                invalidate.invoke(service);
                if (generation.getInt(service) != 5 || busy.getBoolean(service) || retry.getLong(service) != 0 || !disconnected[0])
                    throw new AssertionError("Capture invalidation did not cancel old work and reset readiness");
                result.putBoolean("capture_invalidation_cancels_work", true);
                Field alpha = LiveTranslationService.class.getDeclaredField("overlayAlpha"); alpha.setAccessible(true); alpha.setFloat(service, 201/255f);
                Class<?> piece = Class.forName("org.mangaamtl.android.LiveTranslationService$Piece");
                Constructor<?> constructor = piece.getDeclaredConstructor(String.class, Bitmap.class, RectF.class, RectF.class); constructor.setAccessible(true);
                List<Object> pieces = List.of(constructor.newInstance("lower", lower, first, new RectF(0, 0, 1, 1)),
                    constructor.newInstance("upper", upper, second, new RectF(0, 0, 1, 1)));
                Method gray = LiveTranslationService.class.getDeclaredMethod("gray", Image.class, int.class, int.class, List.class, RectF.class); gray.setAccessible(true);
                Method clean = LiveTranslationService.class.getDeclaredMethod("cleanCrop", Image.class, Rect.class, List.class, RectF.class); clean.setAccessible(true);
                byte[] values = (byte[])gray.invoke(service, frame, 200, 360, pieces, new RectF());
                Bitmap restored = (Bitmap)clean.invoke(service, frame, new Rect(0, 0, 200, 360), pieces, new RectF());
                int shade = (180*77+150*150+110*29)>>8, grayError = 0, colorError = 0;
                for (int y = 65; y < 170; y++) for (int x = 15; x < 125; x++) {
                    grayError = Math.max(grayError, Math.abs((values[y*200+x]&255)-shade));
                    int color = restored.getPixel(x, y);
                    colorError = Math.max(colorError, Math.max(Math.abs(Color.red(color)-180),
                        Math.max(Math.abs(Color.green(color)-150), Math.abs(Color.blue(color)-110))));
                }
                result.putInt("gray_max_error", grayError); result.putInt("color_max_error", colorError);
                if (!Python.isStarted()) Python.start(new AndroidPlatform(getTargetContext()));
                PyObject scope = Python.getInstance().getBuiltins().callAttr("dict");
                scope.callAttr("__setitem__", "restored_pixels", values);
                scope.callAttr("__setitem__", "shade", shade);
                Python.getInstance().getBuiltins().callAttr("exec", """
                    import json
                    from live_tracking import Tracker
                    tracker = Tracker()
                    tracker.track(bytes([shade])*72000, 200, 360)
                    serial = tracker.begin('[0,0,1,1]')
                    tracker.finish(serial, json.dumps(dict(width=200,height=360,
                        items=[dict(bbox=[20,72,120,162],overlay='synthetic')])))
                    for _ in range(10):
                        state = json.loads(tracker.track(restored_pixels, 200, 360))
                        assert state['dirty'] is None and not state['remove'], state
                    """, scope);
                result.putBoolean("stationary_repeat_ocr", false);
                Field rendered = LiveTranslationService.class.getDeclaredField("rendered"); rendered.setAccessible(true);
                @SuppressWarnings("unchecked") Map<String, Object> renderMap = (Map<String, Object>)rendered.get(service);
                renderMap.put("lower", pieces.get(0)); renderMap.put("upper", pieces.get(1));
                for (String name : List.of("screenWidth", "screenHeight")) {
                    Field size = LiveTranslationService.class.getDeclaredField(name); size.setAccessible(true);
                    size.setInt(service, name.equals("screenWidth") ? 200 : 360);
                }
                Class<?> viewClass = Class.forName("org.mangaamtl.android.LiveTranslationService$Overlay");
                Constructor<?> viewConstructor = viewClass.getDeclaredConstructor(LiveTranslationService.class, android.content.Context.class); viewConstructor.setAccessible(true);
                Object view = viewConstructor.newInstance(service, getTargetContext());
                Method refresh = viewClass.getDeclaredMethod("refresh"); refresh.setAccessible(true); refresh.invoke(view);
                Field displayed = LiveTranslationService.class.getDeclaredField("displayedPieces"); displayed.setAccessible(true);
                if (!((List<?>)displayed.get(service)).isEmpty()) throw new AssertionError("Undrawn overlays leaked into capture reconstruction");
                Method draw = viewClass.getDeclaredMethod("onDraw", Canvas.class); draw.setAccessible(true); draw.invoke(view, canvas);
                if (((List<?>)displayed.get(service)).size() != 2) throw new AssertionError("Drawn overlays were not published");
                result.putBoolean("queued_overlays_excluded", true);
                RectF[] boundsCases = {new RectF(-.1f,.2f,.3f,.4f),new RectF(.2f,-.1f,.6f,.1f),
                    new RectF(.2f,.9f,.6f,1.1f),new RectF(.9f,.2f,1.1f,.4f)};
                RectF[] clipCases = {new RectF(.1f,.25f,.25f,.35f),new RectF(0,.02f,1,1),
                    new RectF(0,0,1,.98f),new RectF(0,0,.98f,1)};
                for (int caseIndex=0; caseIndex<boundsCases.length; caseIndex++) {
                    renderMap.clear();
                    renderMap.put("clipped",constructor.newInstance("clipped",lower,boundsCases[caseIndex],clipCases[caseIndex]));
                    refresh.invoke(view); layer.eraseColor(Color.TRANSPARENT); draw.invoke(view,canvas);
                    RectF shown = new RectF(boundsCases[caseIndex]); shown.intersect(clipCases[caseIndex]);
                    for (int y=0;y<360;y++) for (int x=0;x<200;x++) {
                        float px=x+.5f,py=y+.5f;
                        boolean inside=px>shown.left*200+2 && px<shown.right*200-2
                            && py>shown.top*360+2 && py<shown.bottom*360-2;
                        boolean outside=px<shown.left*200-2 || px>shown.right*200+2
                            || py<shown.top*360-2 || py>shown.bottom*360+2;
                        int color=layer.getPixel(x,y);
                        if (inside && color!=Color.rgb(20,50,200)) throw new AssertionError("Visible clipped overlay missing: "+caseIndex);
                        if (outside && Color.alpha(color)!=0) throw new AssertionError("Overlay escaped clip: "+caseIndex);
                    }
                }
                result.putInt("actual_view_clipping_cases",boundsCases.length);
                restored.recycle();
                finish(grayError <= 8 && colorError <= 8 ? 0 : 1, result);
            }
        } catch (Exception | AssertionError error) { result.putString("error", error.toString()); finish(1, result); }
    }
}
