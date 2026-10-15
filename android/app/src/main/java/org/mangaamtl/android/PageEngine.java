package org.mangaamtl.android;
import android.content.Context;
import ai.onnxruntime.*;
import java.io.File;
import java.nio.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.*;
import org.json.*;
import org.mangaamtl.npucheck.NpuRuntime;
import org.mangaamtl.npucheck.AnimePipeline;

public final class PageEngine implements AutoCloseable {
    private final Context context;
    private final File models;
    private final Map<String, OrtSession> sessions = new HashMap<>();
    private final Set<String> verified = new HashSet<>();
    private final JSONObject evidence = new JSONObject();
    private Translator translator;
    private AnimePipeline.Cached anime;
    private File translationDirectory;
    public PageEngine(Context context, File models) { this.context = context; this.models = models; translationDirectory = new File(models, "translation"); }
    public synchronized void setServerStatus(String message, int consolePort) {
        ServerService.status = message;
        ServerService.consolePort = consolePort;
    }
    public synchronized void selectModel(String path) throws Exception {
        File directory = new File(path).getCanonicalFile();
        if (!directory.toPath().startsWith(models.getCanonicalFile().toPath()) || !new File(directory, "genie_config.json").isFile()) throw new IllegalArgumentException("Invalid NPU model directory");
        if (translator != null) { translator.close(); translator = null; }
        translationDirectory = directory;
    }
    public synchronized String chat(String messages, int maxTokens, float temperature, float topP) throws Exception {
        if (!new File(translationDirectory, "genie_config.json").isFile()) throw new IllegalStateException("Install a Qwen model from the model finder, or enable Samsung language packs");
        if (translator == null) {
            if (anime != null) { anime.close(); anime = null; }
            translator = new Translator(context, translationDirectory);
        }
        String text = translator.generate(messages, maxTokens, temperature, topP);
        evidence.put("translation", new JSONObject().put("runtime", "qairt").put("backend", "QnnHtp").put("compute_unit", "npu"));
        saveEvidence();
        return text;
    }
    public boolean samsungEnabled() { return SamsungTranslator.enabled(context); }
    public String inpaintModel() { return new File(models, "anime/pipeline.json").isFile() ? "anime_pipeline" : "lama_dilated.onnx"; }
    public synchronized void samsungSetEnabled(boolean enabled) throws Exception {
        if (enabled) SamsungSetup.ensure(context);
        if (!context.getSharedPreferences("samsung", 0).edit().putBoolean("enabled", enabled).commit())
            throw new java.io.IOException("Could not save Samsung translation setting");
    }
    public synchronized String samsungTranslate(String text) throws Exception {
        String translated = SamsungTranslator.translate(context, text);
        evidence.put("translation", new JSONObject().put("runtime", "Samsung Interpreter UI bridge").put("compute_unit", "unverified"));
        saveEvidence();
        return translated;
    }
    public synchronized void samsungBeginBatch() { SamsungTranslator.beginBatch(); }
    public synchronized void samsungEndBatch() { SamsungTranslator.endBatch(); }
    public synchronized byte[] run(String name, byte[] image, long[] shape, byte[] mask) throws Exception {
        if (name.equals("anime_pipeline")) {
            if (image.length != 3*512*512*4 || mask == null || mask.length != 512*512*4 || !Arrays.equals(shape, new long[]{1,3,512,512})) throw new IllegalArgumentException("Invalid manga inpainting tensors");
            if (translator != null) { translator.close(); translator = null; }
            JSONObject stats = new JSONObject();
            if (anime == null) anime = new AnimePipeline.Cached(new File(models, "anime"), new File(context.getApplicationInfo().nativeLibraryDir), context.getFilesDir());
            float[] output = anime.run(ByteBuffer.wrap(image).order(ByteOrder.LITTLE_ENDIAN).asFloatBuffer(),
                ByteBuffer.wrap(mask).order(ByteOrder.LITTLE_ENDIAN).asFloatBuffer(), stats);
            evidence.put("anime_lama", stats); saveEvidence();
            ByteBuffer bytes = ByteBuffer.allocate(output.length * 4).order(ByteOrder.LITTLE_ENDIAN); bytes.asFloatBuffer().put(output);
            return bytes.array();
        }
        if (!Set.of("detector.onnx", "ocr_detector.onnx", "lama_dilated.onnx", "ocr/ja.onnx", "ocr/ko.onnx", "ocr/zh.onnx", "ocr/ru.onnx", "ocr/en.onnx").contains(name)) throw new IllegalArgumentException("Unknown NPU model");
        if (!new File(models, name).isFile()) throw new IllegalStateException("Install the " + (name.startsWith("lama_") ? "inpainting" : "OCR") + " model pack in the Android app first");
        long count = 1;
        for (long dimension : shape) { if (dimension <= 0 || dimension > 4096) throw new IllegalArgumentException("Invalid model shape"); count = Math.multiplyExact(count, dimension); }
        if (count * 4 != image.length || count > 16_000_000) throw new IllegalArgumentException("Invalid tensor size");
        try (OnnxTensor input = OnnxTensor.createTensor(OrtEnvironment.getEnvironment(), ByteBuffer.wrap(image).order(ByteOrder.LITTLE_ENDIAN).asFloatBuffer(), shape)) {
            float[] result;
            if (mask != null) {
                if (mask.length != 512*512*4) throw new IllegalArgumentException("Invalid inpaint mask");
                try (OnnxTensor masking = OnnxTensor.createTensor(OrtEnvironment.getEnvironment(), ByteBuffer.wrap(mask).order(ByteOrder.LITTLE_ENDIAN).asFloatBuffer(), new long[]{1,1,512,512})) {
                    result = infer(name, Map.of("image", input, "mask", masking));
                }
            } else result = infer(name, Map.of("image", input));
            ByteBuffer output = ByteBuffer.allocate(result.length * 4).order(ByteOrder.LITTLE_ENDIAN);
            output.asFloatBuffer().put(result);
            saveEvidence();
            return output.array();
        }
    }
    private void saveEvidence() throws Exception { Files.write(new File(context.getFilesDir(), "npu-evidence.json").toPath(), evidence.toString(2).getBytes(StandardCharsets.UTF_8)); }
    private float[] infer(String name, Map<String, OnnxTensor> inputs) throws Exception {
        OrtSession session = sessions.get(name);
        if (session == null) {
            // Graph compilation needs temporary RAM; reload the LLM when OCR has finished.
            if (translator != null) { translator.close(); translator = null; }
            session = NpuRuntime.open(new File(models, name), new File(context.getApplicationInfo().nativeLibraryDir),
                    new File(context.getFilesDir(), name.replace('/', '_') + "-profile"));
            sessions.put(name, session);
        }
        float[] values;
        try (OrtSession.Result result = session.run(inputs)) {
            FloatBuffer buffer = ((OnnxTensor) result.get(0)).getFloatBuffer();
            values = new float[buffer.remaining()];
            buffer.get(values);
            for (float value : values) if (!Float.isFinite(value)) throw new IllegalStateException("Non-finite NPU output: " + name);
        }
        if (verified.add(name)) {
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
            if (qnn == 0 || other != 0) throw new IllegalStateException("NPU profile verification failed: " + name);
            evidence.put(name, new JSONObject().put("qnn_kernel_events", qnn).put("other_kernel_events", other));
        }
        return values;
    }

    @Override public synchronized void close() {
        SamsungTranslator.endBatch();
        if (anime != null) { anime.close(); anime = null; }
        for (OrtSession session : sessions.values()) { try { session.close(); } catch (Exception ignored) { } }
        sessions.clear();
        if (translator != null) translator.close();
    }
}
