package org.mangaamtl.android;

import android.app.*;
import android.content.*;
import android.content.pm.ServiceInfo;
import android.graphics.*;
import android.hardware.display.*;
import android.hardware.input.InputManager;
import android.media.*;
import android.media.projection.*;
import android.os.*;
import android.provider.Settings;
import android.util.Base64;
import android.util.DisplayMetrics;
import android.view.*;
import android.widget.Button;
import android.widget.Toast;
import java.io.*;
import java.net.*;
import java.nio.ByteBuffer;
import java.util.concurrent.*;
import java.util.*;
import org.json.*;
import com.chaquo.python.*;

/** One clean frame in flight; transparent text regions never consume app touches. */
public final class LiveTranslationService extends Service {
    private final Handler main = new Handler(Looper.getMainLooper());
    private final ExecutorService worker = Executors.newSingleThreadExecutor();
    private HandlerThread captureThread;
    private Handler capture;
    private WindowManager windows;
    private Button button;
    private Overlay overlay;
    private MediaProjection projection;
    private VirtualDisplay display;
    private ImageReader reader;
    private volatile int generation;
    private volatile boolean running;
    private volatile boolean ocrBusy;
    private long lastFrame;
    private long retryAfter;
    private PyObject tracker;
    private float overlayAlpha;
    private final Map<String, Piece> rendered = new LinkedHashMap<>();
    private volatile List<Piece> pieces = Collections.emptyList();
    private volatile RectF controlBounds = new RectF();
    private volatile HttpURLConnection activeConnection;
    private int screenWidth, screenHeight;
    @Override public IBinder onBind(Intent intent) { return null; }

    @Override public void onCreate() {
        super.onCreate(); windows = getSystemService(WindowManager.class);
        captureThread = new HandlerThread("Live clean frames"); captureThread.start();
        capture = new Handler(captureThread.getLooper());
    }
    private void foreground(boolean capturing) {
        NotificationManager manager = getSystemService(NotificationManager.class);
        manager.createNotificationChannel(new NotificationChannel("live", "Live screen translation", NotificationManager.IMPORTANCE_LOW));
        PendingIntent stop = PendingIntent.getService(this, 0, new Intent(this, LiveTranslationService.class).setAction("stop"), PendingIntent.FLAG_IMMUTABLE);
        PendingIntent open = PendingIntent.getActivity(this, 1, new Intent(this, MainActivity.class), PendingIntent.FLAG_IMMUTABLE);
        Notification notification = new Notification.Builder(this, "live")
            .setContentTitle(capturing ? "Live screen translation is capturing" : "Live translation button ready")
            .setContentText(capturing ? "Tap Stop to end screen capture" : "Tap the floating Live button to start")
            .setSmallIcon(android.R.drawable.ic_menu_view).setContentIntent(open).setOngoing(true)
            .addAction(new Notification.Action.Builder(null, "Stop", stop).build()).build();
        startForeground(2, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE
            | (capturing ? ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PROJECTION : 0));
    }
    @Override public int onStartCommand(Intent intent, int flags, int id) {
        if (intent != null && "stop".equals(intent.getAction())) { stopSelf(); return START_NOT_STICKY; }
        if (!Settings.canDrawOverlays(this)) { stopSelf(); return START_NOT_STICKY; }
        try {
            Intent data = intent == null ? null : intent.getParcelableExtra("capture_data", Intent.class);
            foreground(data != null || running);
            if (button == null) createWindows();
            if (data != null) startCapture(intent.getIntExtra("capture_result", Activity.RESULT_CANCELED), data);
            if (intent != null && "refresh".equals(intent.getAction()) && running) {
                generation++;
                if (activeConnection != null) activeConnection.disconnect();
                capture.post(() -> {
                    generation++;
                    tracker = Python.getInstance().getModule("live_tracking").callAttr("Tracker");
                    ocrBusy = false; retryAfter = 0;
                });
                for (Piece piece : rendered.values()) piece.bitmap.recycle();
                rendered.clear(); overlay.refresh();
            }
        } catch (Exception error) { fail(error); }
        return START_NOT_STICKY;
    }
    private void createWindows() {
        overlay = new Overlay(this);
        WindowManager.LayoutParams textParams = new WindowManager.LayoutParams(-1, -1,
            WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE | WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE
                | WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN,
            PixelFormat.TRANSLUCENT);
        textParams.gravity = Gravity.TOP | Gravity.LEFT;
        textParams.layoutInDisplayCutoutMode = WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_SHORT_EDGES;
        // Android rejects touches through opaque, untrusted overlay windows.
        overlayAlpha = textParams.alpha = Math.min(.79f, getSystemService(InputManager.class).getMaximumObscuringOpacityForTouch());
        windows.addView(overlay, textParams);
        button = new Button(this); button.setText("Live"); button.setContentDescription("Start live screen translation");
        WindowManager.LayoutParams control = new WindowManager.LayoutParams(-2, -2,
            WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE, PixelFormat.TRANSLUCENT);
        control.gravity = Gravity.TOP | Gravity.LEFT; control.x = 16; control.y = 160;
        windows.addView(button, control);
        button.post(this::updateControlBounds);
        button.setOnClickListener(view -> {
            if (running) { stopCapture(); foreground(false); }
            else startActivity(new Intent(this, MainActivity.class).putExtra("live_capture", true)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_SINGLE_TOP));
        });
        button.setOnTouchListener(new View.OnTouchListener() {
            float x, y; int left, top; boolean dragged;
            public boolean onTouch(View view, android.view.MotionEvent event) {
                if (event.getAction() == MotionEvent.ACTION_DOWN) {
                    x = event.getRawX(); y = event.getRawY(); left = control.x; top = control.y; dragged = false;
                } else if (event.getAction() == MotionEvent.ACTION_MOVE) {
                    float dx = event.getRawX()-x, dy = event.getRawY()-y;
                    dragged |= Math.abs(dx)+Math.abs(dy) > 12;
                    if (dragged) {
                        Rect bounds = windows.getMaximumWindowMetrics().getBounds();
                        control.x = Math.max(0, Math.min(bounds.width()-button.getWidth(), left+(int)dx));
                        control.y = Math.max(0, Math.min(bounds.height()-button.getHeight(), top+(int)dy));
                        windows.updateViewLayout(button, control); button.post(LiveTranslationService.this::updateControlBounds);
                    }
                } else if (event.getAction() == MotionEvent.ACTION_UP && !dragged) { view.performClick(); }
                return true;
            }
        });
    }
    private void startCapture(int result, Intent data) {
        stopCapture(); foreground(true);
        projection = getSystemService(MediaProjectionManager.class).getMediaProjection(result, data);
        MediaProjection currentProjection = projection;
        projection.registerCallback(new MediaProjection.Callback() {
            @Override public void onStop() { if (projection == currentProjection) { stopCapture(); foreground(false); } }
            @Override public void onCapturedContentResize(int width, int height) {
                if (running && (width != screenWidth || height != screenHeight)) resize(width, height);
            }
        }, main);
        DisplayMetrics metrics = new DisplayMetrics(); windows.getDefaultDisplay().getRealMetrics(metrics);
        screenWidth = metrics.widthPixels; screenHeight = metrics.heightPixels;
        tracker = Python.getInstance().getModule("live_tracking").callAttr("Tracker");
        lastFrame = 0; retryAfter = 0; ocrBusy = false;
        int[] size = captureSize(screenWidth, screenHeight);
        reader = ImageReader.newInstance(size[0], size[1], PixelFormat.RGBA_8888, 2);
        reader.setOnImageAvailableListener(this::frame, capture);
        display = projection.createVirtualDisplay("MangaAMTL live", size[0], size[1], metrics.densityDpi,
            DisplayManager.VIRTUAL_DISPLAY_FLAG_AUTO_MIRROR, reader.getSurface(), null, capture);
        running = true; button.setText("Stop"); button.setContentDescription("Stop live screen capture");
        android.util.Log.i("MangaAMTLLive", "Capture started: " + screenWidth + "x" + screenHeight);
        button.post(this::updateControlBounds);
    }
    private int[] captureSize(int width, int height) {
        float scale = Math.min(1f, 1600f/Math.max(width, height));
        return new int[]{Math.max(1, Math.round(width*scale)), Math.max(1, Math.round(height*scale))};
    }
    private void resize(int width, int height) {
        generation++; screenWidth = width; screenHeight = height;
        tracker = Python.getInstance().getModule("live_tracking").callAttr("Tracker");
        rendered.clear(); overlay.refresh(); lastFrame = 0;
        int[] size = captureSize(width, height);
        ImageReader old = reader;
        reader = ImageReader.newInstance(size[0], size[1], PixelFormat.RGBA_8888, 2);
        reader.setOnImageAvailableListener(this::frame, capture);
        display.resize(size[0], size[1], getResources().getDisplayMetrics().densityDpi);
        display.setSurface(reader.getSurface()); old.close(); button.post(this::updateControlBounds);
    }
    private void updateControlBounds() {
        if (button == null || screenWidth <= 0 || screenHeight <= 0) return;
        int[] location = new int[2]; button.getLocationOnScreen(location);
        controlBounds = new RectF((float)location[0]/screenWidth, (float)location[1]/screenHeight,
            (float)(location[0]+button.getWidth())/screenWidth, (float)(location[1]+button.getHeight())/screenHeight);
    }
    private static RectF rect(JSONArray a) throws JSONException {
        return new RectF((float)a.getDouble(0), (float)a.getDouble(1), (float)a.getDouble(2), (float)a.getDouble(3));
    }
    private static JSONArray array(RectF r) throws JSONException {
        return new JSONArray().put(r.left).put(r.top).put(r.right).put(r.bottom);
    }
    private void apply(JSONObject result) throws JSONException {
        JSONArray removed = result.optJSONArray("remove");
        if (removed != null) for (int i = 0; i < removed.length(); i++) {
            Piece old = rendered.remove(removed.getString(i));
            if (old != null) old.bitmap.recycle();
        }
        JSONArray moved = result.optJSONArray("move");
        if (moved != null) for (int i = 0; i < moved.length(); i++) {
            JSONObject item = moved.getJSONObject(i);
            Piece old = rendered.get(item.getString("id"));
            if (old != null) rendered.put(old.id, new Piece(old, rect(item.getJSONArray("rect")), rect(item.getJSONArray("clip"))));
        }
        JSONArray added = result.optJSONArray("add");
        if (added != null) for (int i = 0; i < added.length(); i++) {
            JSONObject item = added.getJSONObject(i);
            byte[] png = Base64.decode(item.getString("overlay"), Base64.DEFAULT);
            Bitmap bitmap = BitmapFactory.decodeByteArray(png, 0, png.length);
            if (bitmap != null) {
                Piece piece = new Piece(item.getString("id"), bitmap, rect(item.getJSONArray("rect")), rect(item.getJSONArray("clip")));
                rendered.put(piece.id, piece);
            }
        }
        overlay.refresh();
    }
    private static int restore(int value, int overlay, float alpha) {
        return Math.max(0, Math.min(255, Math.round((value-alpha*overlay)/(1-alpha))));
    }
    private static int sample(Piece piece, float nx, float ny) {
        float u = (nx-piece.bounds.left)/piece.bounds.width()*piece.width-.5f;
        float v = (ny-piece.bounds.top)/piece.bounds.height()*piece.height-.5f;
        int left = (int)Math.floor(u), top = (int)Math.floor(v);
        float fx = u-left, fy = v-top;
        float alpha = 0, red = 0, green = 0, blue = 0;
        for (int row = 0; row < 2; row++) for (int col = 0; col < 2; col++) {
            int x = Math.max(0, Math.min(piece.width-1, left+col));
            int y = Math.max(0, Math.min(piece.height-1, top+row));
            int color = piece.pixels[y*piece.width+x];
            float weightedAlpha = (col == 0 ? 1-fx : fx)*(row == 0 ? 1-fy : fy)*Color.alpha(color);
            alpha += weightedAlpha;
            red += weightedAlpha*Color.red(color); green += weightedAlpha*Color.green(color); blue += weightedAlpha*Color.blue(color);
        }
        return alpha <= 0 ? Color.TRANSPARENT : Color.argb(Math.round(alpha), Math.round(red/alpha), Math.round(green/alpha), Math.round(blue/alpha));
    }
    private byte[] gray(Image image, int width, int height, List<Piece> snapshot, RectF control) {
        Image.Plane plane = image.getPlanes()[0];
        ByteBuffer buffer = plane.getBuffer();
        byte[] values = new byte[width*height];
        for (int y = 0; y < height; y++) for (int x = 0; x < width; x++) {
            int sx = Math.min(image.getWidth()-1, (int)((x+.5f)*image.getWidth()/width));
            int sy = Math.min(image.getHeight()-1, (int)((y+.5f)*image.getHeight()/height));
            int offset = sy*plane.getRowStride()+sx*plane.getPixelStride();
            int r = buffer.get(offset)&255, g = buffer.get(offset+1)&255, b = buffer.get(offset+2)&255;
            values[y*width+x] = (byte)((r*77+g*150+b*29)>>8);
        }
        boolean[] restored = new boolean[values.length];
        for (int i = snapshot.size()-1; i >= 0; i--) {
            Piece piece = snapshot.get(i);
            RectF area = new RectF(piece.bounds);
            if (!area.intersect(piece.clip)) continue;
            int left = Math.max(0, (int)(area.left*width)), top = Math.max(0, (int)(area.top*height));
            int right = Math.min(width, (int)Math.ceil(area.right*width)), bottom = Math.min(height, (int)Math.ceil(area.bottom*height));
            for (int y = top; y < bottom; y++) for (int x = left; x < right; x++) {
                int index = y*width+x;
                if (restored[index]) continue;
                float nx = ((int)((x+.5f)*image.getWidth()/width)+.5f)/image.getWidth();
                float ny = ((int)((y+.5f)*image.getHeight()/height)+.5f)/image.getHeight();
                int color = sample(piece, nx, ny);
                float alpha = overlayAlpha*Color.alpha(color)/255f;
                if (alpha <= 0) continue;
                int shade = (Color.red(color)*77+Color.green(color)*150+Color.blue(color)*29)>>8;
                values[index] = (byte)restore(values[index]&255, shade, alpha);
                restored[index] = true;
            }
        }
        for (int y = Math.max(0, (int)(control.top*height)); y < Math.min(height, (int)Math.ceil(control.bottom*height)); y++)
            for (int x = Math.max(0, (int)(control.left*width)); x < Math.min(width, (int)Math.ceil(control.right*width)); x++)
                values[y*width+x] = 0;
        return values;
    }
    private Bitmap cleanCrop(Image image, Rect crop, List<Piece> snapshot, RectF control) throws IOException {
        Image.Plane plane = image.getPlanes()[0];
        if (plane.getPixelStride() != 4) throw new IOException("Unsupported capture pixel stride");
        ByteBuffer buffer = plane.getBuffer();
        int width = crop.width(), height = crop.height();
        int[] pixels = new int[width*height];
        for (int y = 0; y < height; y++) for (int x = 0; x < width; x++) {
            int offset = (y+crop.top)*plane.getRowStride()+(x+crop.left)*plane.getPixelStride();
            pixels[y*width+x] = Color.rgb(buffer.get(offset)&255, buffer.get(offset+1)&255, buffer.get(offset+2)&255);
        }
        boolean[] restored = new boolean[pixels.length];
        for (int i = snapshot.size()-1; i >= 0; i--) {
            Piece piece = snapshot.get(i);
            RectF area = new RectF(piece.bounds);
            if (!area.intersect(piece.clip)) continue;
            int left = Math.max(crop.left, (int)Math.ceil(area.left*image.getWidth()));
            int top = Math.max(crop.top, (int)Math.ceil(area.top*image.getHeight()));
            int right = Math.min(crop.right, (int)Math.ceil(area.right*image.getWidth()));
            int bottom = Math.min(crop.bottom, (int)Math.ceil(area.bottom*image.getHeight()));
            for (int y = top; y < bottom; y++) for (int x = left; x < right; x++) {
                int index = (y-crop.top)*width+x-crop.left;
                if (restored[index]) continue;
                int overlayColor = sample(piece, (x+.5f)/image.getWidth(), (y+.5f)/image.getHeight()), color = pixels[index];
                float alpha = overlayAlpha*Color.alpha(overlayColor)/255f;
                if (alpha <= 0) continue;
                pixels[index] = Color.rgb(restore(Color.red(color), Color.red(overlayColor), alpha),
                    restore(Color.green(color), Color.green(overlayColor), alpha),
                    restore(Color.blue(color), Color.blue(overlayColor), alpha));
                restored[index] = true;
            }
        }
        for (int y = Math.max(crop.top, (int)(control.top*image.getHeight())); y < Math.min(crop.bottom, (int)Math.ceil(control.bottom*image.getHeight())); y++)
            for (int x = Math.max(crop.left, (int)(control.left*image.getWidth())); x < Math.min(crop.right, (int)Math.ceil(control.right*image.getWidth())); x++)
                pixels[(y-crop.top)*width+x-crop.left] = Color.BLACK;
        return Bitmap.createBitmap(pixels, width, height, Bitmap.Config.ARGB_8888);
    }
    private void frame(ImageReader source) {
        if (source != reader) return;
        try (Image image = source.acquireLatestImage()) {
            if (image == null || !running || image.getTimestamp()-lastFrame < 80_000_000L) return;
            lastFrame = image.getTimestamp();
            int epoch = generation;
            PyObject currentTracker = tracker;
            List<Piece> snapshot = pieces;
            RectF control = controlBounds;
            float scale = Math.min(1f, 512f/Math.max(image.getWidth(), image.getHeight()));
            int width = Math.max(1, Math.round(image.getWidth()*scale)), height = Math.max(1, Math.round(image.getHeight()*scale));
            JSONArray ignore = new JSONArray().put(array(control));
            JSONObject update = new JSONObject(currentTracker.callAttr("track", gray(image, width, height, snapshot, control),
                width, height, ignore.toString()).toString());
            main.post(() -> {
                if (!running || generation != epoch) return;
                try { apply(update); } catch (Exception error) { fail(error); }
            });
            JSONArray requested = update.optJSONArray("dirty");
            if (requested == null || ocrBusy || System.nanoTime() < retryAfter) return;
            RectF area = rect(requested);
            Rect crop = new Rect(Math.max(0, (int)(area.left*image.getWidth())), Math.max(0, (int)(area.top*image.getHeight())),
                Math.min(image.getWidth(), (int)Math.ceil(area.right*image.getWidth())), Math.min(image.getHeight(), (int)Math.ceil(area.bottom*image.getHeight())));
            if (crop.width() < 4 || crop.height() < 4) return;
            RectF actual = new RectF((float)crop.left/image.getWidth(), (float)crop.top/image.getHeight(),
                (float)crop.right/image.getWidth(), (float)crop.bottom/image.getHeight());
            Bitmap bitmap = cleanCrop(image, crop, snapshot, control);
            int serial = currentTracker.callAttr("begin", array(actual).toString()).toInt();
            boolean useCache = getSharedPreferences("live", 0).getBoolean("cache", true);
            ocrBusy = true;
            worker.execute(() -> {
                try {
                    ByteArrayOutputStream encoded = new ByteArrayOutputStream();
                    bitmap.compress(Bitmap.CompressFormat.PNG, 100, encoded); bitmap.recycle();
                    if (generation != epoch) throw new CancellationException("Capture stopped");
                    JSONObject response = send(encoded.toByteArray(), useCache);
                    android.util.Log.i("MangaAMTLLive", "Region frame: "+response.optInt("regions")+" regions, "
                        +response.optInt("cache_hits")+" cache hits, backend="+response.optString("translation_backend")
                        +", OCR="+response.optDouble("ocr_seconds")+"s, translation="+response.optDouble("translation_seconds")
                        +"s, total="+response.optDouble("seconds")+"s, crop="+actual);
                    capture.post(() -> {
                        if (generation != epoch || !running) { ocrBusy = false; return; }
                        try {
                            JSONObject result = new JSONObject(currentTracker.callAttr("finish", serial, response.toString()).toString());
                            android.util.Log.i("MangaAMTLLive", "Accepted overlays: "+result.getJSONArray("add").length());
                            main.post(() -> {
                                if (running && generation == epoch) {
                                    try { apply(result); } catch (Exception error) { fail(error); }
                                }
                            });
                        } catch (Exception error) { main.post(() -> fail(error)); }
                        finally { ocrBusy = false; }
                    });
                } catch (Exception error) {
                    capture.post(() -> {
                        currentTracker.callAttr("abort", serial);
                        ocrBusy = false;
                        if (running && generation == epoch) {
                            retryAfter = System.nanoTime()+2_000_000_000L;
                            main.post(() -> Toast.makeText(this, "Live translation: "+error.getMessage(), Toast.LENGTH_LONG).show());
                        }
                    });
                }
            });
        } catch (Exception error) { main.post(() -> { if (running) fail(error); }); }
    }
    private JSONObject send(byte[] png, boolean useCache) throws Exception {
        String boundary = "MangaAMTLLiveFrame";
        String language = getSharedPreferences("live", 0).getString("source", "auto");
        String background = getSharedPreferences("live", 0).getBoolean("blur", true) ? "blur" : "none";
        HttpURLConnection connection = (HttpURLConnection)new URL("http://127.0.0.1:" + ServerService.consolePort + "/v1/live").openConnection();
        activeConnection = connection;
        connection.setRequestMethod("POST"); connection.setConnectTimeout(5000); connection.setReadTimeout(45000);
        connection.setDoOutput(true); connection.setRequestProperty("Content-Type", "multipart/form-data; boundary="+boundary);
        try {
            try (OutputStream output = connection.getOutputStream()) {
                output.write(("--"+boundary+"\r\nContent-Disposition: form-data; name=\"cache_enabled\"\r\n\r\n"+useCache+"\r\n--"+boundary+"\r\nContent-Disposition: form-data; name=\"ocr_lang\"\r\n\r\n"+language+"\r\n--"+boundary+"\r\nContent-Disposition: form-data; name=\"background_mode\"\r\n\r\n"+background+"\r\n--"+boundary+"\r\nContent-Disposition: form-data; name=\"image\"; filename=\"screen.png\"\r\nContent-Type: image/png\r\n\r\n").getBytes(java.nio.charset.StandardCharsets.UTF_8));
                output.write(png); output.write(("\r\n--"+boundary+"--\r\n").getBytes(java.nio.charset.StandardCharsets.UTF_8));
            }
            int status = connection.getResponseCode();
            try (InputStream input = status == 200 ? connection.getInputStream() : connection.getErrorStream()) {
                if (input == null) throw new IOException("HTTP " + status);
                JSONObject result = new JSONObject(new String(input.readAllBytes(), java.nio.charset.StandardCharsets.UTF_8));
                if (status != 200) throw new IOException(result.optString("detail", "HTTP " + status));
                return result;
            }
        } finally {
            if (activeConnection == connection) activeConnection = null;
            connection.disconnect();
        }
    }
    private void stopCapture() {
        running = false; generation++; main.removeCallbacksAndMessages(null);
        HttpURLConnection connection = activeConnection;
        if (connection != null) connection.disconnect();
        MediaProjection old = projection; projection = null;
        if (display != null) { display.release(); display = null; }
        if (reader != null) { reader.close(); reader = null; }
        if (old != null) old.stop();
        for (Piece piece : rendered.values()) piece.bitmap.recycle();
        rendered.clear();
        if (overlay != null) overlay.refresh();
        if (button != null) { button.setVisibility(View.VISIBLE); button.setText("Live"); button.setContentDescription("Start live screen translation"); }
    }
    private void fail(Exception error) {
        android.util.Log.e("MangaAMTLLive", "Live screen translation failed", error);
        Toast.makeText(this, "Live translation: " + error.getMessage(), Toast.LENGTH_LONG).show();
        stopSelf();
    }
    @Override public void onDestroy() {
        stopCapture(); worker.shutdownNow(); captureThread.quitSafely();
        if (button != null) windows.removeView(button);
        if (overlay != null) windows.removeView(overlay);
        getSharedPreferences("live", 0).edit().putBoolean("enabled", false).apply();
        super.onDestroy();
    }
    private static final class Piece {
        final String id;
        final Bitmap bitmap;
        final int width, height;
        final int[] pixels;
        final RectF bounds, clip;
        Piece(String id, Bitmap bitmap, RectF bounds, RectF clip) {
            this.id = id; this.bitmap = bitmap; this.bounds = bounds; this.clip = clip;
            width = bitmap.getWidth(); height = bitmap.getHeight(); pixels = new int[width*height];
            bitmap.getPixels(pixels, 0, width, 0, 0, width, height);
        }
        Piece(Piece old, RectF bounds, RectF clip) {
            id = old.id; bitmap = old.bitmap; pixels = old.pixels; width = old.width; height = old.height;
            this.bounds = bounds; this.clip = clip;
        }
    }
    private final class Overlay extends View {
        private final Paint paint = new Paint(Paint.FILTER_BITMAP_FLAG);
        private final int[] location = new int[2];
        private final RectF destination = new RectF();
        Overlay(Context context) { super(context); setImportantForAccessibility(IMPORTANT_FOR_ACCESSIBILITY_NO); }
        void refresh() { pieces = Collections.unmodifiableList(new ArrayList<>(rendered.values())); postInvalidateOnAnimation(); }
        @Override protected void onDraw(Canvas canvas) {
            super.onDraw(canvas);
            getLocationOnScreen(location);
            for (Piece piece : pieces) {
                int saved = canvas.save();
                canvas.clipRect(piece.clip.left*screenWidth-location[0], piece.clip.top*screenHeight-location[1],
                    piece.clip.right*screenWidth-location[0], piece.clip.bottom*screenHeight-location[1]);
                destination.set(piece.bounds.left*screenWidth-location[0], piece.bounds.top*screenHeight-location[1],
                    piece.bounds.right*screenWidth-location[0], piece.bounds.bottom*screenHeight-location[1]);
                canvas.drawBitmap(piece.bitmap, null, destination, paint);
                canvas.restoreToCount(saved);
            }
        }
    }
}
