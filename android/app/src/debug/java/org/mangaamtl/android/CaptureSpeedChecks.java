package org.mangaamtl.android;

import android.app.Instrumentation;
import android.graphics.*;
import android.media.*;
import android.os.*;
import java.io.*;
import java.lang.reflect.*;
import java.util.*;
import org.json.*;
import com.chaquo.python.*;
import com.chaquo.python.android.AndroidPlatform;

/** Measure capture preparation from a saved sample, without capturing the display. */
public final class CaptureSpeedChecks extends Instrumentation {
    @Override public void onCreate(Bundle arguments) { super.onCreate(arguments); start(); }
    @Override public void onStart() {
        Bundle result = new Bundle();
        try (ImageReader reader = ImageReader.newInstance(738, 1600, PixelFormat.RGBA_8888, 2)) {
            Bitmap source = BitmapFactory.decodeFile(new File(getTargetContext().getFilesDir(), "capture-benchmark.png").toString());
            if (source == null) throw new AssertionError("Saved capture benchmark image missing");
            Canvas canvas = reader.getSurface().lockCanvas(null);
            canvas.drawBitmap(source, null, new Rect(0, 0, 738, 1600), new Paint(Paint.FILTER_BITMAP_FLAG));
            reader.getSurface().unlockCanvasAndPost(canvas); source.recycle();
            Image image = null;
            for (int i = 0; i < 100 && image == null; i++) { image = reader.acquireLatestImage(); if (image == null) SystemClock.sleep(10); }
            if (image == null) throw new AssertionError("Synthetic capture unavailable");
            try (Image frame = image) {
                LiveTranslationService service = new LiveTranslationService();
                Method gray = LiveTranslationService.class.getDeclaredMethod("gray", Image.class, int.class, int.class, List.class, RectF.class); gray.setAccessible(true);
                Method clean = LiveTranslationService.class.getDeclaredMethod("cleanCrop", Image.class, Rect.class, List.class, RectF.class); clean.setAccessible(true);
                JSONArray reports = new JSONArray();
                for (Rect crop : List.of(new Rect(0, 0, 738, 1600), new Rect(0, 600, 738, 900))) {
                    double grayMs = 0, cleanMs = 0, pngMs = 0, webpMs = 0; int bytes = 0, webpBytes = 0;
                    for (int i = 0; i < 6; i++) {
                        long start = System.nanoTime();
                        gray.invoke(service, frame, 236, 512, Collections.emptyList(), new RectF());
                        long tracked = System.nanoTime();
                        Bitmap bitmap = (Bitmap)clean.invoke(service, frame, crop, Collections.emptyList(), new RectF());
                        long cleaned = System.nanoTime();
                        ByteArrayOutputStream output = new ByteArrayOutputStream(); bitmap.compress(Bitmap.CompressFormat.PNG, 100, output);
                        long encoded = System.nanoTime(); bytes = output.size();
                        ByteArrayOutputStream webp = new ByteArrayOutputStream(); bitmap.compress(Bitmap.CompressFormat.WEBP_LOSSLESS, 0, webp);
                        long webpEncoded = System.nanoTime(); webpBytes = webp.size();
                        if (i == 0) {
                            Bitmap decoded = BitmapFactory.decodeByteArray(webp.toByteArray(), 0, webpBytes);
                            int[] expected = new int[crop.width()*crop.height()], actual = new int[expected.length];
                            bitmap.getPixels(expected,0,crop.width(),0,0,crop.width(),crop.height());
                            decoded.getPixels(actual,0,crop.width(),0,0,crop.width(),crop.height());
                            if (!Arrays.equals(expected,actual)) throw new AssertionError("Lossless WebP changed RGB pixels");
                            decoded.recycle();
                        }
                        bitmap.recycle();
                        if (i == 5) {
                            try (FileOutputStream file = new FileOutputStream(new File(getTargetContext().getFilesDir(), "capture-"+crop.height()+".webp"))) { file.write(webp.toByteArray()); }
                        }
                        if (i > 0) { grayMs += (tracked-start)/1e6; cleanMs += (cleaned-tracked)/1e6; pngMs += (encoded-cleaned)/1e6; webpMs += (webpEncoded-encoded)/1e6; }
                    }
                    reports.put(new JSONObject().put("width",crop.width()).put("height",crop.height())
                        .put("gray_ms",grayMs/5).put("clean_ms",cleanMs/5).put("png_ms",pngMs/5).put("bytes",bytes)
                        .put("webp_ms",webpMs/5).put("webp_bytes",webpBytes));
                }
                if (!Python.isStarted()) Python.start(new AndroidPlatform(getTargetContext()));
                result.putBoolean("pillow_webp", Python.getInstance().getModule("PIL.features").callAttr("check", "webp").toBoolean());
                result.putString("result", reports.toString()); finish(0,result);
            }
        } catch (Exception | AssertionError error) { result.putString("error",error.toString()); finish(1,result); }
    }
}
