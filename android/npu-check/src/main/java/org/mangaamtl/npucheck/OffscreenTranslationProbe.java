package org.mangaamtl.npucheck;

import android.app.Activity;
import android.app.ActivityOptions;
import android.content.Intent;
import android.hardware.display.DisplayManager;
import android.hardware.display.VirtualDisplay;
import android.media.ImageReader;
import android.graphics.PixelFormat;
import android.os.Bundle;
import android.widget.TextView;
import java.io.File;
import java.nio.file.Files;

/** Tests ordinary-app offscreen launch before production integration. */
public final class OffscreenTranslationProbe extends Activity {
    private ImageReader images;
    private VirtualDisplay display;
    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        TextView status = new TextView(this);
        setContentView(status);
        String result;
        try {
            images = ImageReader.newInstance(1080, 1920, PixelFormat.RGBA_8888, 2);
            display = getSystemService(DisplayManager.class).createVirtualDisplay(
                "MangaAMTL translation probe", 1080, 1920, 320, images.getSurface(),
                DisplayManager.VIRTUAL_DISPLAY_FLAG_PUBLIC | DisplayManager.VIRTUAL_DISPLAY_FLAG_OWN_CONTENT_ONLY);
            int id = display.getDisplay().getDisplayId();
            Intent intent = new Intent(Intent.ACTION_PROCESS_TEXT).setType("text/plain")
                .setClassName("com.samsung.android.app.interpreter", "com.samsung.android.app.interpreter.translation.view.TranslationActivity")
                .putExtra(Intent.EXTRA_PROCESS_TEXT, "自分の手で作りたい")
                .putExtra(Intent.EXTRA_PROCESS_TEXT_READONLY, true)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_MULTIPLE_TASK);
            boolean allowed = getSystemService(android.app.ActivityManager.class).isActivityStartAllowedOnDisplay(this, id, intent);
            result = "display=" + id + " allowed=" + allowed;
            if (allowed) startActivity(intent, ActivityOptions.makeBasic().setLaunchDisplayId(id).toBundle());
        } catch (Exception error) { result = error.toString(); }
        status.setText(result);
        try { Files.write(new File(getFilesDir(), "offscreen-translation-report.txt").toPath(), result.getBytes(java.nio.charset.StandardCharsets.UTF_8)); }
        catch (Exception error) { android.util.Log.e("OffscreenProbe", "Save failed", error); }
    }
    @Override public void onDestroy() {
        if (display != null) display.release();
        if (images != null) images.close();
        super.onDestroy();
    }
}
