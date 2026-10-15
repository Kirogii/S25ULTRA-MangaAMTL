package org.mangaamtl.npucheck;

import ai.onnxruntime.OrtEnvironment;
import ai.onnxruntime.OrtException;
import ai.onnxruntime.OrtSession;
import java.io.File;
import java.util.HashMap;
import java.util.Map;

/** All neural-network operators must be assigned to Qualcomm's HTP backend. */
public final class NpuRuntime {
    public static OrtSession open(File model, File nativeLibraries, File profile) throws OrtException {
        File backend = new File(nativeLibraries, "libQnnHtp.so");
        boolean mangaStage = model.getName().matches("stage[0-9]+\\.onnx");
        File cached = new File(profile.getParentFile(), "qnn-cache/" + (mangaStage ? "prepare1-" : "") + model.getName() + "-" + model.length()
                + "-" + model.lastModified() + "-" + backend.lastModified() + ".onnx");
        if (!cached.getParentFile().isDirectory() && !cached.getParentFile().mkdirs()) throw new IllegalStateException("Cannot create NPU compilation cache");
        Map<String, String> provider = new HashMap<>();
        provider.put("backend_path", new File(nativeLibraries, "libQnnHtp.so").getAbsolutePath());
        provider.put("htp_performance_mode", "burst");
        provider.put("enable_htp_fp16_precision", "1");
        provider.put("offload_graph_io_quantization", "0");
        if (mangaStage) provider.put("htp_graph_finalization_optimization_mode", "1");
        try (OrtSession.SessionOptions options = new OrtSession.SessionOptions()) {
            if (!cached.isFile() && !model.getName().endsWith(".ctx.onnx")) {
                options.addConfigEntry("ep.context_enable", "1");
                options.addConfigEntry("ep.context_embed_mode", "1");
                options.addConfigEntry("ep.context_file_path", cached.getAbsolutePath());
            }
            options.addConfigEntry("session.disable_cpu_ep_fallback", "1");
            options.setOptimizationLevel(OrtSession.SessionOptions.OptLevel.BASIC_OPT);
            options.enableProfiling(profile.getAbsolutePath());
            options.addQnn(provider);
            return OrtEnvironment.getEnvironment().createSession((cached.isFile() ? cached : model).getAbsolutePath(), options);
        }
    }
}
