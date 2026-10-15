package org.mangaamtl.android;
import android.app.*;
import android.content.Intent;
import android.os.*;
import com.chaquo.python.*;
import com.chaquo.python.android.AndroidPlatform;
import java.io.*;
import java.nio.file.*;

public final class ServerService extends Service {
    static volatile String status = "Server stopped.";
    static volatile int consolePort = 7860;
    static volatile boolean active;
    private Thread worker;
    private PowerManager.WakeLock wake;
    private volatile boolean stopping;
    @Override public IBinder onBind(Intent intent) { return null; }
    @Override public int onStartCommand(Intent intent, int flags, int id) {
        android.util.Log.i("MangaAMTL", "Service command: " + (intent == null ? null : intent.getAction()));
        if (intent != null && "stop".equals(intent.getAction())) {
            stopping = true;
            status = "Stopping server…";
            if (worker == null) stopSelf();
            else if (Python.isStarted()) Python.getInstance().getModule("android_server").callAttr("stop");
            return START_NOT_STICKY;
        }
        if (worker != null) return START_NOT_STICKY;
        active = true;
        NotificationManager manager = getSystemService(NotificationManager.class);
        manager.createNotificationChannel(new NotificationChannel("server", "Localhost server", NotificationManager.IMPORTANCE_LOW));
        PendingIntent open = PendingIntent.getActivity(this, 0, new Intent(this, MainActivity.class), PendingIntent.FLAG_IMMUTABLE);
        startForeground(1, new Notification.Builder(this, "server").setContentTitle("MangaAMTL NPU server")
                .setContentText("localhost:7860 · tap to manage").setSmallIcon(android.R.drawable.stat_notify_sync).setContentIntent(open).setOngoing(true).build());
        wake = getSystemService(PowerManager.class).newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "MangaAMTL:server"); wake.acquire();
        worker = new Thread(() -> {
            try {
                File models = Models.install(this, text -> status = text);
                for (String name : new String[]{"app.py", "jinja.txt", "model-catalog.json", "fonts/NotoCJK.ttc"}) {
                    File destination = new File(getFilesDir(), name);
                    destination.getParentFile().mkdirs();
                    if (name.startsWith("fonts/") && destination.isFile()) continue;
                    File temporary = new File(destination.getPath() + ".part");
                    try (InputStream input = getAssets().open(name); FileOutputStream output = new FileOutputStream(temporary)) { input.transferTo(output); output.getFD().sync(); }
                    Files.move(temporary.toPath(), destination.toPath(), StandardCopyOption.REPLACE_EXISTING);
                }
                if (stopping) return;
                synchronized (Python.class) {
                    if (!Python.isStarted()) Python.start(new AndroidPlatform(this));
                }
                status = "Starting Python localhost server…";
                try (PageEngine engine = new PageEngine(this, models)) {
                    PyObject runtime = Python.getInstance().getModule("android_server");
                    status = "Server running · localhost:8000 and localhost:7860\nKeep this service running while using the extension.";
                    runtime.callAttr("serve", getFilesDir().getAbsolutePath(), engine);
                }
            } catch (Exception | LinkageError error) {
                status = "Server failed: " + error;
                android.util.Log.e("MangaAMTL", status, error);
            } finally {
                active = false;
                android.util.Log.i("MangaAMTL", "Server worker finished; stopping=" + stopping + "; status=" + status);
                if (wake != null && wake.isHeld()) wake.release();
                stopSelf();
            }
        }, "manga-localhost");
        worker.start();
        return START_NOT_STICKY;
    }
    @Override public void onDestroy() {
        active = false;
        android.util.Log.i("MangaAMTL", "Service destroyed; stopping=" + stopping + "; status=" + status);
        stopping = true;
        if (Python.isStarted()) { try { Python.getInstance().getModule("android_server").callAttr("stop"); } catch (Exception ignored) { } }
        if (wake != null && wake.isHeld()) wake.release();
        if (!status.startsWith("Server failed")) status = "Server stopped.";
        super.onDestroy();
    }
}
