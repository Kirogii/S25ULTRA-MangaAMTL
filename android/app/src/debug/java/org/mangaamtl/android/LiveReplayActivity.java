package org.mangaamtl.android;

import android.app.Activity;
import android.content.Intent;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.media.projection.MediaProjectionConfig;
import android.media.projection.MediaProjectionManager;
import android.os.Bundle;
import android.view.ViewGroup;
import android.widget.*;
import java.io.File;

/** Controlled sample-only screen for unattended real capture/overlay checks. */
public final class LiveReplayActivity extends Activity {
    private ScrollView scroll;
    private Bitmap page;
    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        page = BitmapFactory.decodeFile(new File(getFilesDir(), "capture-benchmark.png").getAbsolutePath());
        if (page == null) { finish(); return; }
        LinearLayout root = new LinearLayout(this); root.setOrientation(LinearLayout.VERTICAL);
        root.setOnApplyWindowInsetsListener((view,insets) -> {
            android.graphics.Insets bars = insets.getInsets(android.view.WindowInsets.Type.systemBars()
                | android.view.WindowInsets.Type.displayCutout());
            view.setPadding(bars.left,bars.top,bars.right,bars.bottom);
            return insets;
        });
        TextView header = new TextView(this); header.setText("MangaAMTL controlled capture replay");
        header.setBackgroundColor(0xffeeeeee); header.setTextColor(0xff111111); header.setPadding(12,12,12,12);
        root.addView(header);
        scroll = new ScrollView(this);
        LinearLayout pages = new LinearLayout(this); pages.setOrientation(LinearLayout.VERTICAL);
        for (int i = 0; i < 3; i++) {
            ImageView image = new ImageView(this); image.setImageBitmap(page); image.setAdjustViewBounds(true);
            pages.addView(image,new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT));
        }
        scroll.addView(pages);
        root.addView(scroll,new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT,0,1));
        TextView footer = new TextView(this); footer.setText("Fixed bottom bar - sample content only");
        footer.setBackgroundColor(0xffeeeeee); footer.setTextColor(0xff111111); footer.setPadding(12,12,12,12);
        root.addView(footer); setContentView(root);
        applyCommand(getIntent());
    }
    @Override protected void onNewIntent(Intent intent) { super.onNewIntent(intent); setIntent(intent); applyCommand(intent); }
    private void applyCommand(Intent intent) {
        if (intent.hasExtra("scroll_y")) scroll.post(() -> {
            int target = intent.getIntExtra("scroll_y",0);
            if (intent.getBooleanExtra("smooth",false)) scroll.smoothScrollTo(0,target);
            else scroll.scrollTo(0,target);
            android.util.Log.i("MangaAMTLReplay","Scroll command="+target+", current="+scroll.getScrollY());
        });
        if (intent.getBooleanExtra("capture",false)) {
            intent.removeExtra("capture");
            MediaProjectionManager manager = getSystemService(MediaProjectionManager.class);
            startActivityForResult(manager.createScreenCaptureIntent(MediaProjectionConfig.createConfigForDefaultDisplay()),71);
        }
        if (intent.getBooleanExtra("stop_capture",false))
            startService(new Intent(this,LiveTranslationService.class).setAction("stop"));
    }
    @Override protected void onActivityResult(int request,int result,Intent data) {
        super.onActivityResult(request,result,data);
        if (request == 71 && result == RESULT_OK && data != null) {
            startForegroundService(new Intent(this,ServerService.class));
            startForegroundService(new Intent(this,LiveTranslationService.class)
                .putExtra("capture_result",result).putExtra("capture_data",data));
            android.util.Log.i("MangaAMTLReplay","Controlled capture started");
        }
    }
}
