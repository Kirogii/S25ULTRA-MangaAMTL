package org.mangaamtl.npucheck;

import android.content.Context;
import ai.onnxruntime.OnnxTensor;
import ai.onnxruntime.OnnxJavaType;
import ai.onnxruntime.OrtEnvironment;
import ai.onnxruntime.OrtSession;
import ai.onnxruntime.TensorInfo;
import java.io.File;
import java.nio.FloatBuffer;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.HashMap;
import java.util.Map;
import org.json.JSONArray;
import org.json.JSONObject;

/** Synthetic-input compatibility check, not an OCR/translation accuracy test. */
final class ModelCheck {
    static JSONObject run(Context context, String relativePath) throws Exception {
        File root = new File(context.getFilesDir(), "models").getCanonicalFile();
        File model = new File(root, relativePath).getCanonicalFile();
        if (!model.toPath().startsWith(root.toPath()) || !model.getName().endsWith(".onnx") || !model.isFile()) {
            throw new IllegalArgumentException("Model must be an ONNX file inside " + root + "; requested " + model + "; exists=" + model.isFile());
        }
        JSONObject report = new JSONObject();
        report.put("model", relativePath);
        report.put("synthetic_inputs", true);
        long start = System.nanoTime();
        Map<String, OnnxTensor> inputs = new HashMap<>();
        try (OrtSession session = NpuRuntime.open(model, new File(context.getApplicationInfo().nativeLibraryDir), new File(context.getFilesDir(), "model-profile"))) {
            report.put("prepare_ms", (System.nanoTime() - start) / 1_000_000);
            for (var entry : session.getInputInfo().entrySet()) {
                if (!(entry.getValue().getInfo() instanceof TensorInfo info) || info.type != OnnxJavaType.FLOAT) {
                    throw new IllegalArgumentException("Probe requires float32 inputs");
                }
                long count = 1;
                for (long dimension : info.getShape()) {
                    if (dimension <= 0) throw new IllegalArgumentException("Export static shapes before NPU testing");
                    count = Math.multiplyExact(count, dimension);
                }
                if (count > 16_777_216) throw new IllegalArgumentException("Input too large for the compatibility probe");
                float[] values = new float[(int) count];
                java.util.Arrays.fill(values, 0.5f);
                inputs.put(entry.getKey(), OnnxTensor.createTensor(OrtEnvironment.getEnvironment(), FloatBuffer.wrap(values), info.getShape()));
            }
            start = System.nanoTime();
            try (OrtSession.Result result = session.run(inputs)) {
                if (result.size() == 0) throw new IllegalStateException("No model outputs");
                for (var output : result) {
                    if (!(output.getValue() instanceof OnnxTensor tensor) || tensor.getInfo().type != OnnxJavaType.FLOAT) {
                        throw new IllegalStateException("Probe requires float32 outputs");
                    }
                    FloatBuffer values = tensor.getFloatBuffer();
                    while (values.hasRemaining()) {
                        if (!Float.isFinite(values.get())) throw new IllegalStateException("Non-finite model output");
                    }
                }
                report.put("inference_ms", (System.nanoTime() - start) / 1_000_000);
            }
            String profile = session.endProfiling();
            JSONArray events = new JSONArray(new String(Files.readAllBytes(new File(profile).toPath()), StandardCharsets.UTF_8));
            int qnn = 0;
            int other = 0;
            for (int i = 0; i < events.length(); i++) {
                JSONObject args = events.getJSONObject(i).optJSONObject("args");
                if (args == null || !args.has("provider")) continue;
                if (args.getString("provider").equals("QNNExecutionProvider")) qnn++;
                else other++;
            }
            report.put("qnn_kernel_events", qnn);
            report.put("other_kernel_events", other);
            if (qnn == 0 || other != 0) throw new IllegalStateException("Profile does not prove exclusive QNN execution");
            report.put("passed", true);
        } finally {
            for (OnnxTensor input : inputs.values()) input.close();
        }
        return report;
    }
}
