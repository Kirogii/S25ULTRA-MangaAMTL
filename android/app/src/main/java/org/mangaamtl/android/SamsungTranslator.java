package org.mangaamtl.android;

import android.content.Context;
import android.hardware.display.*;
import android.media.ImageReader;
import android.graphics.PixelFormat;
import android.os.*;

final class SamsungTranslator {
    private static VirtualDisplay activeDisplay;
    private static ImageReader activeImages;
    private static HandlerThread activeReader;
    private static boolean batch;
    static synchronized void beginBatch() { batch = true; }
    static synchronized void endBatch() { batch = false; release(); }
    private static void release() {
        if (activeDisplay != null) { activeDisplay.release(); activeDisplay = null; }
        if (activeImages != null) { activeImages.close(); activeImages = null; }
        if (activeReader != null) { activeReader.quitSafely(); activeReader = null; }
    }
    static boolean enabled(Context context) { return context.getSharedPreferences("samsung", 0).getBoolean("enabled", false); }
    @android.annotation.SuppressLint("WrongConstant") // Public SDK omits the verified destroy-on-removal flag.
    static synchronized String translate(Context context, String text) throws Exception {
        if (text.isBlank()) return "";
        if (text.length() > 4000) throw new IllegalArgumentException("Samsung text exceeds 4000 characters");
        IBinder helper = SamsungSetup.ensure(context);
        Parcel request = Parcel.obtain(), response = Parcel.obtain();
        try {
            if (activeDisplay == null) {
                activeReader = new HandlerThread("Samsung display frames"); activeReader.start();
                activeImages = ImageReader.newInstance(540, 960, PixelFormat.RGBA_8888, 2);
                activeImages.setOnImageAvailableListener(source -> {
                    try (var image = source.acquireLatestImage()) { }
                    catch (IllegalStateException ignored) { /* Display was released while a frame callback was queued. */ }
                }, new Handler(activeReader.getLooper()));
                // DESTROY_CONTENT_ON_REMOVAL prevents moving Samsung onto the main screen during cleanup.
                activeDisplay = context.getSystemService(DisplayManager.class).createVirtualDisplay("MangaAMTL Samsung", 540, 960, 160, activeImages.getSurface(),
                    DisplayManager.VIRTUAL_DISPLAY_FLAG_PUBLIC | DisplayManager.VIRTUAL_DISPLAY_FLAG_OWN_CONTENT_ONLY | 256);
            }
            request.writeInterfaceToken("org.mangaamtl.android.Samsung");
            request.writeInt(activeDisplay.getDisplay().getDisplayId()); request.writeString(text);
            if (!helper.transact(1, request, response, 0)) throw new IllegalStateException("Samsung helper protocol mismatch");
            response.readException();
            String result = response.readString();
            if (result == null || result.isBlank()) throw new IllegalStateException("Samsung returned empty translation");
            return result;
        } finally {
            if (!batch) release();
            request.recycle(); response.recycle();
        }
    }
}
