package org.mangaamtl.android;

import android.app.Instrumentation;
import android.content.*;
import android.os.Bundle;
import java.io.*;
import java.nio.file.Files;
import java.util.*;
import java.util.zip.*;

/** Device checks use an isolated directory, never the user's installed models. */
public final class PackChecks extends Instrumentation {
    @Override public void onCreate(Bundle arguments) { super.onCreate(arguments); start(); }
    @Override public void onStart() {
        Bundle result = new Bundle(); File isolated = null;
        try {
            Context actual = getTargetContext();
            File valid = new File(actual.getFilesDir(), "model-pack-test.zip");
            isolated = new File(actual.getCacheDir(), "pack-check-" + UUID.randomUUID());
            if (!isolated.mkdirs()) throw new IOException("Cannot create check directory");
            File root = isolated;
            Context target = new ContextWrapper(actual) {
                @Override public File getFilesDir() { return root; }
                @Override public File getCacheDir() { File cache = new File(root, "cache"); cache.mkdirs(); return cache; }
            };
            try (InputStream input = new FileInputStream(valid)) { Models.installPack(target, input, "inpainting"); }
            File checked;
            try (var paths = Files.walk(new File(root, "models").toPath())) {
                checked = paths.filter(Files::isRegularFile).findFirst().orElseThrow().toFile();
            }
            byte[] before = Files.readAllBytes(checked.toPath());
            String relative = new File(root, "models").toPath().relativize(checked.toPath()).toString().replace('\\','/');
            for (String name : new String[]{relative, "../escape.onnx"}) {
                ByteArrayOutputStream bytes = new ByteArrayOutputStream();
                try (ZipOutputStream zip = new ZipOutputStream(bytes)) { zip.putNextEntry(new ZipEntry(name)); zip.write(new byte[]{1,2,3}); zip.closeEntry(); }
                boolean rejected = false;
                try { Models.installPack(target, new ByteArrayInputStream(bytes.toByteArray()), "inpainting"); }
                catch (Exception expected) { rejected = true; }
                if (!rejected || !Arrays.equals(before, Files.readAllBytes(checked.toPath()))) throw new AssertionError("Invalid pack was accepted or changed installed models");
            }
            result.putString("result", "passed: valid install, corrupted pack, unsafe path, existing model preserved");
            finish(0, result);
        } catch (Exception | AssertionError error) { result.putString("error", error.toString()); finish(1, result); }
        finally {
            if (isolated != null) try (var paths = Files.walk(isolated.toPath())) {
                for (var path : paths.sorted(Comparator.reverseOrder()).toArray(java.nio.file.Path[]::new)) Files.deleteIfExists(path);
            } catch (IOException ignored) { }
        }
    }
}
