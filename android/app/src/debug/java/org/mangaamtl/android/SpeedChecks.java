package org.mangaamtl.android;

import android.app.Instrumentation;
import android.os.Bundle;
import android.os.Debug;
import java.io.File;
import java.nio.*;
import java.nio.file.Files;
import org.json.*;

/** Compare the warm NPU pipeline against the original reduced-resolution reference. */
public final class SpeedChecks extends Instrumentation {
    private String modelFolder = "models";
    @Override public void onCreate(Bundle arguments) {
        super.onCreate(arguments);
        if (arguments != null) modelFolder = arguments.getString("models", "models");
        start();
    }
    @Override public void onStart() {
        Bundle result = new Bundle();
        JSONObject evidence = new JSONObject();
        try {
            File root = getTargetContext().getFilesDir();
            File modelRoot = new File(root, modelFolder).getCanonicalFile();
            if (!modelRoot.toPath().startsWith(root.getCanonicalFile().toPath())) throw new IllegalArgumentException("Test models must be in the app's files directory");
            byte[] image = Files.readAllBytes(new File(root, "anime-image.f32").toPath());
            byte[] mask = Files.readAllBytes(new File(root, "anime-mask.f32").toPath());
            FloatBuffer expected = ByteBuffer.wrap(Files.readAllBytes(new File(root, "anime-expected.f32").toPath())).order(ByteOrder.LITTLE_ENDIAN).asFloatBuffer();
            JSONArray runs = new JSONArray();
            try (PageEngine engine = new PageEngine(getTargetContext(), modelRoot)) {
                for (int i = 0; i < 3; i++) {
                    long started = System.nanoTime();
                    byte[] output = engine.run("anime_pipeline", image, new long[]{1,3,512,512}, mask);
                    double seconds = (System.nanoTime()-started)/1e9;
                    FloatBuffer actual = ByteBuffer.wrap(output).order(ByteOrder.LITTLE_ENDIAN).asFloatBuffer();
                    double sum = 0, maximum = 0;
                    for (int j = 0; j < actual.remaining(); j++) {
                        double error = Math.abs(actual.get(j)-expected.get(j)); sum += error; maximum = Math.max(maximum, error);
                    }
                    if (sum/expected.capacity() > .003 || maximum > .05) throw new AssertionError("NPU fidelity failed");
                    runs.put(new JSONObject().put("seconds", seconds).put("pss_kb", Debug.getPss())
                        .put("mean_error", sum/expected.capacity()).put("max_error", maximum));
                }
            }
            evidence.put("passed", true).put("runs", runs);
            result.putString("result", evidence.toString());
            Files.write(new File(root, "speed-checks.json").toPath(), evidence.toString(2).getBytes(java.nio.charset.StandardCharsets.UTF_8));
            finish(0, result);
        } catch (Exception | AssertionError error) { result.putString("error", error.toString()); finish(1, result); }
    }
}
