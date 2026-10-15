package org.mangaamtl.android;
import android.app.Activity;
import android.content.Intent;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.widget.*;
import android.net.Uri;
import android.provider.OpenableColumns;
import com.chaquo.python.*;
import com.chaquo.python.android.AndroidPlatform;
import java.io.*;
import java.util.UUID;

public final class MainActivity extends Activity {
    private final Handler handler = new Handler(Looper.getMainLooper());
    private TextView status;
    private Button importFont;
    private boolean installingPack;
    private final Runnable refresh = new Runnable() {
        @Override public void run() { status.setText(installingPack ? "Installing and verifying model pack…" : ServerService.status); handler.postDelayed(this, 1000); }
    };
    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        LinearLayout panel = new LinearLayout(this); panel.setOrientation(LinearLayout.VERTICAL);
        int pad = (int)(24 * getResources().getDisplayMetrics().density);
        panel.setPadding(pad, pad * 2, pad, pad);
        TextView title = new TextView(this); title.setText("MangaAMTL NPU Server"); title.setTextSize(26); panel.addView(title);
        TextView help = new TextView(this); help.setText("Extension server URL: http://localhost:7860\nAlso accepts localhost:8000 when that port is free.\n\nChoose Samsung language packs or a downloaded Qwen model for translation. Google Lens uses the cloud; local OCR and inpainting use the NPU. Font sizing, text colors and drawing use app.py's original Python methods.\n\nInstall optional ZIP packs from Downloads using the buttons below; stop the server before installing. Keep the server running while using the extension."); help.setTextSize(16); panel.addView(help);
        String included = ((BuildConfig.BUNDLED_OCR ? "OCR " : "") + (BuildConfig.BUNDLED_INPAINTING ? "inpainting " : "") + (BuildConfig.BUNDLED_TRANSLATION ? "Qwen translator" : "")).trim();
        help.append("\nIncluded in this APK: " + (included.isEmpty() ? "no offline models" : included));
        Button start = new Button(this); start.setText("Start localhost server"); panel.addView(start);
        Button stop = new Button(this); stop.setText("Stop server"); panel.addView(stop);
        Button console = new Button(this); console.setText("Open server console"); panel.addView(console);
        Button models = new Button(this); models.setText("Find and download NPU models"); panel.addView(models);
        String[] categories = {"ocr", "inpainting", "translation"};
        for (int i = 0; i < categories.length; i++) {
            final int request = i + 2;
            Button install = new Button(this); install.setText("Install " + categories[i] + " model pack (.zip)"); panel.addView(install);
            install.setOnClickListener(v -> {
                if (ServerService.active || installingPack) {
                    new android.app.AlertDialog.Builder(this).setMessage("Stop the server and wait for it to finish before installing a model pack.").setPositiveButton("OK", null).show();
                    return;
                }
                startActivityForResult(new Intent(Intent.ACTION_OPEN_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE).setType("application/zip"), request);
            });
        }
        importFont = new Button(this); importFont.setText("Import overlay font (.ttf, .otf, .ttc)"); panel.addView(importFont);
        Switch samsung = new Switch(this); samsung.setText("Samsung language packs (English output)");
        samsung.setChecked(SamsungTranslator.enabled(this)); panel.addView(samsung);
        TextView samsungHelp = new TextView(this);
        samsungHelp.setText("Samsung translates on a hidden display while you keep browsing. Start Shizuku using Wireless debugging on this phone, authorize MangaAMTL, then enable this switch. No USB or computer is required. Shizuku needs restarting after a phone reboot. NPU use inside Samsung is unverified. English must be selected in Samsung Interpreter. Turn off to use the selected Qwen NPU model.");
        panel.addView(samsungHelp);
        Button setupSamsung = new Button(this); setupSamsung.setText("Open Shizuku / phone-only setup"); panel.addView(setupSamsung);
        setupSamsung.setOnClickListener(v -> {
            Intent open = getPackageManager().getLaunchIntentForPackage("moe.shizuku.privileged.api");
            startActivity(open != null ? open : new Intent(Intent.ACTION_VIEW, Uri.parse("https://shizuku.rikka.app/download/")));
        });
        samsung.setOnCheckedChangeListener((button, checked) -> {
            if (!checked) { getSharedPreferences("samsung", 0).edit().putBoolean("enabled", false).apply(); return; }
            if (rikka.shizuku.Shizuku.pingBinder() && rikka.shizuku.Shizuku.checkSelfPermission() != android.content.pm.PackageManager.PERMISSION_GRANTED) {
                samsung.setChecked(false);
                rikka.shizuku.Shizuku.requestPermission(27);
                return;
            }
            samsung.setEnabled(false);
            new Thread(() -> {
                try {
                    SamsungSetup.ensure(this);
                    getSharedPreferences("samsung", 0).edit().putBoolean("enabled", true).apply();
                    runOnUiThread(() -> samsung.setEnabled(true));
                } catch (Exception error) { runOnUiThread(() -> {
                    samsung.setEnabled(true);
                    samsung.setChecked(false);
                    new android.app.AlertDialog.Builder(this).setMessage(error.getMessage()).setPositiveButton("OK", null).show();
                }); }
            }, "samsung-helper-check").start();
        });
        status = new TextView(this); status.setTextSize(16); status.setAccessibilityLiveRegion(android.view.View.ACCESSIBILITY_LIVE_REGION_POLITE); panel.addView(status);
        ScrollView scroll = new ScrollView(this); scroll.addView(panel); setContentView(scroll);
        start.setOnClickListener(v -> { if (!installingPack) startForegroundService(new Intent(this, ServerService.class)); });
        stop.setOnClickListener(v -> startService(new Intent(this, ServerService.class).setAction("stop")));
        console.setOnClickListener(v -> startActivity(new Intent(Intent.ACTION_VIEW, android.net.Uri.parse("http://localhost:" + ServerService.consolePort + "/console"))));
        models.setOnClickListener(v -> startActivity(new Intent(Intent.ACTION_VIEW, android.net.Uri.parse("http://localhost:" + ServerService.consolePort + "/models"))));
        importFont.setOnClickListener(v -> startActivityForResult(new Intent(Intent.ACTION_OPEN_DOCUMENT)
                .addCategory(Intent.CATEGORY_OPENABLE).setType("*/*"), 1));
        if (getIntent().getBooleanExtra("start_server", false)) startForegroundService(new Intent(this, ServerService.class));
    }
    @Override protected void onActivityResult(int request, int result, Intent data) {
        super.onActivityResult(request, result, data);
        if (request >= 2 && request <= 4 && result == RESULT_OK && data != null && data.getData() != null) {
            if (ServerService.active || installingPack) return;
            installingPack = true;
            Uri pack = data.getData();
            String category = new String[]{"ocr", "inpainting", "translation"}[request - 2];
            new Thread(() -> {
                String message;
                try (InputStream input = getContentResolver().openInputStream(pack)) {
                    if (input == null) throw new IOException("Cannot open model pack");
                    Models.installPack(this, input, category);
                    message = category + " model pack installed. Start the server to use it.";
                } catch (Exception error) { message = "Model installation failed: " + error.getMessage(); }
                String feedback = message;
                runOnUiThread(() -> { installingPack = false; if (!isDestroyed()) new android.app.AlertDialog.Builder(this).setMessage(feedback).setPositiveButton("OK", null).show(); });
            }, "model-import").start();
            return;
        }
        if (request != 1 || result != RESULT_OK || data == null || data.getData() == null) return;
        Uri uri = data.getData();
        importFont.setEnabled(false);
        new Thread(() -> {
            File temporary = null;
            String message;
            try {
                String name = "";
                try (android.database.Cursor cursor = getContentResolver().query(uri, new String[]{OpenableColumns.DISPLAY_NAME}, null, null, null)) {
                    if (cursor != null && cursor.moveToFirst()) name = cursor.getString(0);
                }
                if (name == null || !name.toLowerCase(java.util.Locale.ROOT).matches(".*\\.(ttf|otf|ttc)$")) throw new IOException("Choose a TTF, OTF or TTC font file");
                String imported = "Imported-" + UUID.randomUUID().toString().substring(0, 8) + "-" + name.replaceAll("[^a-zA-Z0-9._-]", "_").toLowerCase(java.util.Locale.ROOT);
                File fonts = new File(getFilesDir(), "fonts");
                if (!fonts.isDirectory() && !fonts.mkdirs()) throw new IOException("Cannot create fonts folder");
                temporary = new File(fonts, imported + ".part");
                try (InputStream input = getContentResolver().openInputStream(uri); FileOutputStream output = new FileOutputStream(temporary)) {
                    if (input == null) throw new IOException("Cannot open this font");
                    byte[] buffer = new byte[65536]; long size = 0; int count;
                    while ((count = input.read(buffer)) != -1) {
                        size += count;
                        if (size > 320_000_000) throw new IOException("Font exceeds 320 MB");
                        output.write(buffer, 0, count);
                    }
                    output.getFD().sync();
                }
                synchronized (Python.class) {
                    if (!Python.isStarted()) Python.start(new AndroidPlatform(getApplicationContext()));
                }
                String selected = Python.getInstance().getModule("android_fonts").callAttr("import_font", getFilesDir().getAbsolutePath(), temporary.getAbsolutePath(), imported).toString();
                message = "Overlay font selected: " + selected;
            } catch (Exception error) { message = "Font import failed: " + error.getMessage(); }
            finally { if (temporary != null) temporary.delete(); }
            String feedback = message;
            runOnUiThread(() -> { if (isFinishing() || isDestroyed()) return; importFont.setEnabled(true); new android.app.AlertDialog.Builder(this).setMessage(feedback).setPositiveButton("OK", null).show(); });
        }, "font-import").start();
    }
    @Override public void onStart() { super.onStart(); handler.post(refresh); }
    @Override public void onStop() { handler.removeCallbacks(refresh); super.onStop(); }
}
