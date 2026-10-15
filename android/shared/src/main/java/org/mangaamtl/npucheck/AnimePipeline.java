package org.mangaamtl.npucheck;

import ai.onnxruntime.*;
import java.io.File;
import java.nio.FloatBuffer;
import java.nio.file.Files;
import java.nio.charset.StandardCharsets;
import java.util.*;
import org.json.*;

/** Exact residual-block partitions; only one QNN session is resident at a time. */
public final class AnimePipeline {
    /** Reuse already-compiled contexts; raw ONNX compilation remains sequential and uncached here. */
    public static final class Cached implements AutoCloseable {
        private final JSONArray stages;
        private final File root, libraries, cache;
        private final OrtSession[] sessions;
        private final boolean[] verified;
        public Cached(File root, File libraries, File cache) throws Exception {
            this.root = root; this.libraries = libraries; this.cache = cache;
            stages = new JSONArray(new String(Files.readAllBytes(new File(root, "pipeline.json").toPath()), StandardCharsets.UTF_8));
            sessions = new OrtSession[stages.length()]; verified = new boolean[stages.length()];
            Set<String> available = new HashSet<>(Arrays.asList("image", "mask"));
            for (int i = 0; i < stages.length(); i++) {
                JSONObject stage = stages.getJSONObject(i);
                if (!stage.getString("file").matches("stage[0-9]+\\.ctx\\.onnx")) throw new IllegalArgumentException("Install the compiled manga model pack");
                JSONArray inputs = stage.getJSONArray("inputs");
                for (int j = 0; j < inputs.length(); j++) if (!available.contains(inputs.getString(j))) throw new IllegalArgumentException("Manga stages must form a sequential pipeline");
                available = new HashSet<>(Arrays.asList("image", "mask"));
                JSONArray outputs = stage.getJSONArray("outputs");
                for (int j = 0; j < outputs.length(); j++) available.add(outputs.getString(j));
            }
            if (!available.contains("output")) throw new IllegalArgumentException("Manga pipeline has no output");
        }
        public synchronized float[] run(FloatBuffer image, FloatBuffer mask, JSONObject evidence) throws Exception {
            long started = System.nanoTime();
            int loaded = 0;
            OrtSession.Result previous = null;
            try (OnnxTensor imageTensor = OnnxTensor.createTensor(OrtEnvironment.getEnvironment(), image, new long[]{1,3,512,512});
                 OnnxTensor maskTensor = OnnxTensor.createTensor(OrtEnvironment.getEnvironment(), mask, new long[]{1,1,512,512})) {
                Map<String, OnnxTensor> values = new HashMap<>();
                values.put("image", imageTensor); values.put("mask", maskTensor);
                for (int i = 0; i < stages.length(); i++) {
                    JSONObject stage = stages.getJSONObject(i);
                    if (sessions[i] == null) {
                        sessions[i] = NpuRuntime.open(new File(root, stage.getString("file")), libraries, new File(cache, "anime-cached-stage" + i));
                        loaded++;
                    }
                    Map<String, OnnxTensor> inputs = new HashMap<>();
                    JSONArray names = stage.getJSONArray("inputs");
                    for (int j = 0; j < names.length(); j++) inputs.put(names.getString(j), values.get(names.getString(j)));
                    OrtSession.Result current = sessions[i].run(inputs);
                    if (previous != null) previous.close();
                    previous = current;
                    values.clear(); values.put("image", imageTensor); values.put("mask", maskTensor);
                    names = stage.getJSONArray("outputs");
                    for (int j = 0; j < names.length(); j++) values.put(names.getString(j), (OnnxTensor) current.get(j));
                    if (!verified[i]) {
                        File profile = new File(sessions[i].endProfiling());
                        JSONArray events = new JSONArray(new String(Files.readAllBytes(profile.toPath()), StandardCharsets.UTF_8));
                        int qnn = 0, other = 0;
                        for (int j = 0; j < events.length(); j++) {
                            JSONObject args = events.getJSONObject(j).optJSONObject("args");
                            if (args != null && args.has("provider")) {
                                if (args.getString("provider").equals("QNNExecutionProvider")) qnn++; else other++;
                            }
                        }
                        if (qnn == 0 || other != 0) throw new IllegalStateException("Manga inpainting is not exclusively delegated to QNN");
                        verified[i] = true;
                        Files.deleteIfExists(profile.toPath());
                    }
                }
                FloatBuffer result = values.get("output").getFloatBuffer();
                float[] output = new float[result.remaining()]; result.get(output);
                for (float value : output) if (!Float.isFinite(value)) throw new IllegalStateException("Non-finite manga inpainting output");
                evidence.put("qnn_verified_stages", stages.length()).put("other_kernel_events", 0)
                    .put("sessions_loaded", loaded).put("total_seconds", (System.nanoTime()-started)/1e9);
                return output;
            } finally { if (previous != null) previous.close(); }
        }
        @Override public synchronized void close() {
            for (int i = 0; i < sessions.length; i++) {
                if (sessions[i] != null) { try { sessions[i].close(); } catch (Exception ignored) { } }
                sessions[i] = null; verified[i] = false;
            }
        }
    }
    public static float[] run(File root, File libraries, File cache, FloatBuffer image, FloatBuffer mask, JSONObject evidence) throws Exception {
        return run(root, libraries, cache, image, mask, evidence, null);
    }
    public static float[] run(File root, File libraries, File cache, FloatBuffer image, FloatBuffer mask, JSONObject evidence,
                             java.util.function.BiConsumer<String, float[]> calibration) throws Exception {
        JSONArray stages = new JSONArray(new String(Files.readAllBytes(new File(root, "pipeline.json").toPath()), StandardCharsets.UTF_8));
        Map<String, OnnxTensor> values = new HashMap<>();
        int qnn = 0, other = 0;
        try {
            values.put("image", OnnxTensor.createTensor(OrtEnvironment.getEnvironment(), image, new long[]{1,3,512,512}));
            values.put("mask", OnnxTensor.createTensor(OrtEnvironment.getEnvironment(), mask, new long[]{1,1,512,512}));
            for (int i = 0; i < stages.length(); i++) {
                JSONObject stage = stages.getJSONObject(i);
                Map<String, OnnxTensor> inputs = new HashMap<>();
                JSONArray names = stage.getJSONArray("inputs");
                for (int j = 0; j < names.length(); j++) inputs.put(names.getString(j), values.get(names.getString(j)));
                long started = System.nanoTime();
                try (OrtSession session = NpuRuntime.open(new File(root, stage.getString("file")), libraries, new File(cache, "anime-stage" + i))) {
                    evidence.put("stage" + i + "_load_seconds", (System.nanoTime()-started)/1e9);
                    started = System.nanoTime();
                    try (OrtSession.Result result = session.run(inputs)) {
                        names = stage.getJSONArray("outputs");
                        for (int j = 0; j < names.length(); j++) {
                            OnnxTensor tensor = (OnnxTensor) result.get(j);
                            FloatBuffer buffer = tensor.getFloatBuffer(); float[] copied = new float[buffer.remaining()]; buffer.get(copied);
                            if (calibration != null) calibration.accept("stage" + i + "-" + j, copied);
                            OnnxTensor previous = values.put(names.getString(j), OnnxTensor.createTensor(OrtEnvironment.getEnvironment(), FloatBuffer.wrap(copied), tensor.getInfo().getShape()));
                            if (previous != null) previous.close();
                        }
                    }
                    evidence.put("stage" + i + "_inference_seconds", (System.nanoTime()-started)/1e9);
                    JSONArray events = new JSONArray(new String(Files.readAllBytes(new File(session.endProfiling()).toPath()), StandardCharsets.UTF_8));
                    int stageQnn = 0;
                    for (int j = 0; j < events.length(); j++) {
                        JSONObject args = events.getJSONObject(j).optJSONObject("args");
                        if (args != null && args.has("provider")) { if (args.getString("provider").equals("QNNExecutionProvider")) stageQnn++; else other++; }
                    }
                    if (stageQnn == 0 || other != 0) throw new IllegalStateException("Manga inpainting is not exclusively delegated to QNN");
                    qnn += stageQnn;
                }
                Set<String> needed = new HashSet<>();
                needed.add("output");
                for (int next = i + 1; next < stages.length(); next++) {
                    JSONArray futureInputs = stages.getJSONObject(next).getJSONArray("inputs");
                    for (int j = 0; j < futureInputs.length(); j++) needed.add(futureInputs.getString(j));
                }
                Iterator<Map.Entry<String, OnnxTensor>> remaining = values.entrySet().iterator();
                while (remaining.hasNext()) {
                    Map.Entry<String, OnnxTensor> value = remaining.next();
                    if (!needed.contains(value.getKey())) { value.getValue().close(); remaining.remove(); }
                }
                evidence.put("stage" + i + "_retained_tensors", values.size());
            }
            evidence.put("qnn_kernel_events", qnn).put("other_kernel_events", other);
            FloatBuffer result = values.get("output").getFloatBuffer(); float[] output = new float[result.remaining()]; result.get(output);
            return output;
        } finally { for (OnnxTensor value : values.values()) value.close(); }
    }
}
