package org.mangaamtl.npucheck;
import android.app.Activity;
import android.os.Bundle;
import android.widget.TextView;
import java.io.File;
import java.nio.*;
import java.nio.file.Files;
import java.nio.charset.StandardCharsets;
import org.json.JSONObject;

public final class AnimeLamaProbe extends Activity {
    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        TextView status = new TextView(this); status.setText("Checking partitioned manga LaMa on QNN…"); setContentView(status);
        new Thread(() -> {
            JSONObject report = new JSONObject();
            try {
                File root = getFilesDir();
                // Compile sequentially through AnimePipeline: concurrent QNN compilation exhausted phone memory.
                float[] actual = AnimePipeline.run(new File(root, "anime"), new File(getApplicationInfo().nativeLibraryDir), root,
                    floats(new File(root, "anime-image.f32")), floats(new File(root, "anime-mask.f32")), report, (name, output) -> {
                        ByteBuffer bytes = ByteBuffer.allocate(output.length*4).order(ByteOrder.LITTLE_ENDIAN); bytes.asFloatBuffer().put(output);
                        try { Files.write(new File(root, name + ".f32").toPath(), bytes.array()); }
                        catch (Exception error) { throw new IllegalStateException(error); }
                    });
                FloatBuffer expected = floats(new File(root, "anime-expected.f32"));
                double sum = 0, maximum = 0;
                for (float value : actual) { double error = Math.abs(value-expected.get()); sum += error; maximum = Math.max(maximum,error); }
                report.put("mean_error", sum/actual.length).put("max_error", maximum);
                if (sum/actual.length > .003 || maximum > .05) throw new IllegalStateException("NPU output differs from original checkpoint");
                report.put("passed", true);
            } catch (Exception error) { try { report.put("passed", false).put("error", error.toString()); } catch (Exception ignored) { } }
            try { Files.write(new File(getFilesDir(), "anime-report.json").toPath(), report.toString(2).getBytes(StandardCharsets.UTF_8)); }
            catch (Exception error) { android.util.Log.e("AnimeProbe", "Save failed", error); }
            runOnUiThread(() -> status.setText(report.toString()));
        }, "anime-lama-probe").start();
    }
    private static FloatBuffer floats(File file) throws Exception { return ByteBuffer.wrap(Files.readAllBytes(file.toPath())).order(ByteOrder.LITTLE_ENDIAN).asFloatBuffer(); }
}
