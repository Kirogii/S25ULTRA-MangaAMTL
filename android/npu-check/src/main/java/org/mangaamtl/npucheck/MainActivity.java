package org.mangaamtl.npucheck;

import android.app.Activity;
import android.os.Build;
import android.os.Bundle;
import android.util.Log;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import ai.onnxruntime.OnnxTensor;
import ai.onnxruntime.OrtEnvironment;
import ai.onnxruntime.OrtException;
import ai.onnxruntime.OrtSession;
import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.nio.FloatBuffer;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.Map;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import org.json.JSONArray;
import org.json.JSONObject;

public final class MainActivity extends Activity {
    private final ExecutorService worker = Executors.newSingleThreadExecutor();
    private TextView status;
    private Button run;

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        LinearLayout layout = new LinearLayout(this);
        layout.setOrientation(LinearLayout.VERTICAL);
        int pad = (int) (24 * getResources().getDisplayMetrics().density);
        layout.setPadding(pad, pad * 2, pad, pad);
        TextView title = new TextView(this);
        title.setText("MangaAMTL · NPU validation");
        title.setTextSize(24);
        layout.addView(title);
        TextView explanation = new TextView(this);
        explanation.setText("Development check for the MangaAMTL server's NPU runtime.\n\nChecks a known neural operation on Qualcomm HTP, validates its answer and profile, and verifies that an unsupported operation is refused. No CPU or GPU inference fallback.");
        explanation.setTextSize(16);
        layout.addView(explanation);
        run = new Button(this);
        run.setText("Test NPU");
        layout.addView(run);
        status = new TextView(this);
        status.setTextSize(16);
        layout.addView(status);
        ScrollView scroll = new ScrollView(this);
        scroll.addView(layout);
        setContentView(scroll);
        run.setOnClickListener(view -> startCheck());
        if (getIntent().getBooleanExtra("run_check", false)) startCheck();
    }

    private File asset(String name) throws Exception {
        File file = new File(getFilesDir(), name);
        try (InputStream input = getAssets().open(name); FileOutputStream output = new FileOutputStream(file)) {
            input.transferTo(output);
        }
        return file;
    }

    private void startCheck() {
        run.setEnabled(false);
        status.setText("Running on " + Build.MODEL + " / " + Build.SOC_MODEL + "…");
        worker.execute(() -> {
            JSONObject report = new JSONObject();
            String message;
            try {
                report.put("device", Build.MODEL);
                report.put("soc", Build.SOC_MODEL);
                report.put("android_api", Build.VERSION.SDK_INT);
                String model = getIntent().getStringExtra("model");
                if (model != null) {
                    report.put("model_check", ModelCheck.run(this, model));
                    report.put("passed", true);
                    saveAndDisplay(report, report.toString(2));
                    return;
                }
                File nativeDir = new File(getApplicationInfo().nativeLibraryDir);
                String profile;
                try (OrtSession session = NpuRuntime.open(asset("matmul.onnx"), nativeDir, new File(getFilesDir(), "npu-profile"));
                     OnnxTensor input = OnnxTensor.createTensor(OrtEnvironment.getEnvironment(), FloatBuffer.wrap(new float[]{1, 2, 3, 4}), new long[]{1, 4});
                     OrtSession.Result result = session.run(Map.of("input", input))) {
                    float[][] values = (float[][]) result.get(0).getValue();
                    if (Math.abs(values[0][0] - 50) > 0.1 || Math.abs(values[0][1] - 60) > 0.1) {
                        throw new IllegalStateException("NPU returned an incorrect result");
                    }
                    report.put("result", new JSONArray(values[0]));
                    profile = session.endProfiling();
                }
                JSONArray events = new JSONArray(new String(Files.readAllBytes(new File(profile).toPath()), StandardCharsets.UTF_8));
                int qnnEvents = 0;
                int otherEvents = 0;
                for (int i = 0; i < events.length(); i++) {
                    JSONObject args = events.getJSONObject(i).optJSONObject("args");
                    if (args == null || !args.has("provider")) continue;
                    if (args.getString("provider").equals("QNNExecutionProvider")) qnnEvents++;
                    else otherEvents++;
                }
                report.put("qnn_kernel_events", qnnEvents);
                report.put("other_kernel_events", otherEvents);
                if (qnnEvents == 0 || otherEvents != 0) throw new IllegalStateException("Profile does not prove exclusive QNN execution");
                boolean rejected = false;
                try (OrtSession ignored = NpuRuntime.open(asset("unsupported.onnx"), nativeDir, new File(getFilesDir(), "negative-profile"))) {
                    // Session creation must reject an operation that QNN cannot execute.
                } catch (OrtException expected) {
                    rejected = expected.getMessage().contains("CPU EP fallback")
                            || expected.getMessage().contains("fallback to CPU EP");
                    report.put("unsupported_error", expected.getMessage());
                }
                report.put("unsupported_model_rejected", rejected);
                if (!rejected) throw new IllegalStateException("CPU fallback rejection was not verified");
                report.put("passed", true);
                message = "PASS: HTP inference returned [50, 60].\nQNN kernel events: " + qnnEvents + "\nOther kernel events: 0\nUnsupported model refused.\n\nThis check validates the runtime; see DEVICE_TESTS.md for page and model checks.";
            } catch (Exception | LinkageError error) {
                Log.e("MangaNpuCheck", "NPU check failed", error);
                try { report.put("passed", false); report.put("error", error.toString()); } catch (Exception ignored) { }
                message = "FAIL: " + error + "\n\nNo inference fallback was used.";
            }
            saveAndDisplay(report, message);
        });
    }

    private void saveAndDisplay(JSONObject report, String message) {
        try {
            Files.write(new File(getFilesDir(), "report.json").toPath(), report.toString(2).getBytes(StandardCharsets.UTF_8));
        } catch (Exception error) { Log.e("MangaNpuCheck", "Could not save report", error); }
        Log.i("MangaNpuCheck", report.toString());
        runOnUiThread(() -> { status.setText(message); run.setEnabled(true); });
    }

    @Override public void onDestroy() {
        worker.shutdown();
        super.onDestroy();
    }
}
