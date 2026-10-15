package org.mangaamtl.android;

import android.content.Context;
import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.security.MessageDigest;
import org.json.JSONArray;
import org.json.JSONObject;
import java.util.*;
import java.util.zip.*;

final class Models {
    static void installPack(Context context, InputStream input, String category) throws Exception {
        if (!Set.of("ocr", "inpainting", "translation").contains(category)) throw new IllegalArgumentException("Unknown model category");
        Map<String, JSONObject> expected = new LinkedHashMap<>();
        try (InputStream catalog = context.getAssets().open("model-catalog.json")) {
            JSONArray entries = new JSONArray(new String(catalog.readAllBytes(), StandardCharsets.UTF_8));
            for (int i = 0; i < entries.length(); i++) {
                JSONObject entry = entries.getJSONObject(i);
                if (category.equals(entry.getString("category"))) expected.put(entry.getString("path"), entry);
            }
        }
        if (expected.isEmpty()) throw new IllegalStateException("This build has no compatible pack for " + category);
        long required = 0; for (JSONObject entry : expected.values()) required += entry.getLong("bytes");
        if (context.getFilesDir().getUsableSpace() < required + 256_000_000) throw new IllegalStateException("Not enough space to stage the model pack");
        File staged = new File(context.getCacheDir(), "model-import-" + UUID.randomUUID());
        if (!staged.mkdirs()) throw new IllegalStateException("Cannot stage model pack");
        Set<String> seen = new HashSet<>();
        try (ZipInputStream zip = new ZipInputStream(input)) {
            ZipEntry entry; byte[] buffer = new byte[65536];
            while ((entry = zip.getNextEntry()) != null) {
                if (entry.isDirectory()) continue;
                JSONObject info = expected.get(entry.getName());
                File file = new File(staged, entry.getName()).getCanonicalFile();
                if (info == null || !seen.add(entry.getName()) || !file.toPath().startsWith(staged.getCanonicalFile().toPath())) throw new SecurityException("Unexpected or duplicate model pack file");
                if (!file.getParentFile().isDirectory() && !file.getParentFile().mkdirs()) throw new IllegalStateException("Cannot create staged model folder");
                MessageDigest digest = MessageDigest.getInstance("SHA-256"); long count = 0; int size;
                try (FileOutputStream output = new FileOutputStream(file)) {
                    while ((size = zip.read(buffer)) != -1) {
                        count += size;
                        if (count > info.getLong("bytes")) throw new SecurityException("Model file exceeds expected size");
                        output.write(buffer, 0, size); digest.update(buffer, 0, size);
                    }
                    output.getFD().sync();
                }
                if (count != info.getLong("bytes") || !hex(digest.digest()).equals(info.getString("sha256"))) throw new SecurityException("Model pack integrity check failed");
            }
            if (!seen.equals(expected.keySet())) throw new IllegalStateException("Model pack is incomplete or belongs to a different category/build");
            File root = new File(context.getFilesDir(), "models").getCanonicalFile();
            for (String name : seen) {
                File target = new File(root, name).getCanonicalFile();
                if (!target.toPath().startsWith(root.toPath())) throw new SecurityException("Unsafe destination");
                if (!target.getParentFile().isDirectory() && !target.getParentFile().mkdirs()) throw new IllegalStateException("Cannot create model folder");
                Files.move(new File(staged, name).toPath(), target.toPath(), java.nio.file.StandardCopyOption.REPLACE_EXISTING);
            }
        } finally {
            try (var files = Files.walk(staged.toPath())) {
                for (var file : files.sorted(Comparator.reverseOrder()).toArray(java.nio.file.Path[]::new)) Files.deleteIfExists(file);
            }
        }
    }

    static File install(Context context, java.util.function.Consumer<String> progress) throws Exception {
        File root = new File(context.getFilesDir(), "models");
        if (!root.isDirectory() && !root.mkdirs()) throw new IllegalStateException("Cannot create model folder");
        String manifest;
        try (InputStream input = context.getAssets().open("models/manifest.json")) {
            manifest = new String(input.readAllBytes(), StandardCharsets.UTF_8);
        }
        JSONArray files = new JSONArray(manifest);
        String version = hex(MessageDigest.getInstance("SHA-256").digest(manifest.getBytes(StandardCharsets.UTF_8)));
        File marker = new File(root, ".installed");
        if (marker.isFile() && new String(Files.readAllBytes(marker.toPath()), StandardCharsets.UTF_8).equals(version)) return root;
        long required = 0;
        for (int i = 0; i < files.length(); i++) required += files.getJSONObject(i).getLong("bytes");
        if (context.getFilesDir().getUsableSpace() < required + 256_000_000) {
            throw new IllegalStateException("Free at least " + String.format(java.util.Locale.ROOT, "%.1f", (required + 256_000_000) / 1e9) + " GB to install this build's selected models");
        }
        for (int i = 0; i < files.length(); i++) {
            JSONObject info = files.getJSONObject(i);
            String name = info.getString("path");
            File dest = new File(root, name).getCanonicalFile();
            if (!dest.toPath().startsWith(root.getCanonicalFile().toPath())) throw new SecurityException("Unsafe model path");
            if (!dest.getParentFile().isDirectory() && !dest.getParentFile().mkdirs()) throw new IllegalStateException("Cannot create model folder");
            progress.accept("Installing offline models " + (i + 1) + "/" + files.length());
            File temporary = new File(dest.getPath() + ".part");
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            long bytes = 0;
            try (InputStream input = context.getAssets().open("models/" + name); FileOutputStream output = new FileOutputStream(temporary)) {
                byte[] buffer = new byte[65536];
                int count;
                while ((count = input.read(buffer)) != -1) {
                    output.write(buffer, 0, count);
                    digest.update(buffer, 0, count);
                    bytes += count;
                }
                output.getFD().sync();
            }
            if (bytes != info.getLong("bytes") || !hex(digest.digest()).equals(info.getString("sha256"))) throw new IllegalStateException("Model integrity check failed: " + name);
            Files.move(temporary.toPath(), dest.toPath(), java.nio.file.StandardCopyOption.REPLACE_EXISTING);
        }
        Files.write(marker.toPath(), version.getBytes(StandardCharsets.UTF_8));
        return root;
    }

    private static String hex(byte[] bytes) {
        StringBuilder text = new StringBuilder();
        for (byte value : bytes) text.append(String.format(java.util.Locale.ROOT, "%02x", value & 255));
        return text.toString();
    }
}
