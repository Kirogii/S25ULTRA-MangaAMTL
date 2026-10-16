package org.mangaamtl.android;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Intent;
import android.net.Uri;
import android.widget.Toast;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import org.json.JSONObject;

final class AppUpdates {
    static final String REPOSITORY = "https://github.com/Kirogii/S25ULTRA-MangaAMTL";

    static boolean newer(String tag, String installed) {
        if (!tag.matches("v?[0-9]+\\.[0-9]+\\.[0-9]+") || !installed.matches("[0-9]+\\.[0-9]+\\.[0-9]+")) return false;
        String[] latest = tag.replaceFirst("^v", "").split("\\.");
        String[] current = installed.split("\\.");
        if (latest.length != 3 || current.length != 3) return false;
        try {
            for (int i = 0; i < 3; i++) {
                int comparison = Integer.compare(Integer.parseInt(latest[i]), Integer.parseInt(current[i]));
                if (comparison != 0) return comparison > 0;
            }
        } catch (NumberFormatException ignored) { }
        return false;
    }

    static void check(Activity activity, boolean manual) {
        var preferences = activity.getSharedPreferences("updates", 0);
        long now = System.currentTimeMillis();
        if (!manual && now - preferences.getLong("checked", 0) < 86_400_000) return;
        preferences.edit().putLong("checked", now).apply();
        new Thread(() -> {
            HttpURLConnection connection = null;
            try {
                connection = (HttpURLConnection) new URL("https://api.github.com/repos/Kirogii/S25ULTRA-MangaAMTL/releases/latest").openConnection();
                connection.setConnectTimeout(10_000); connection.setReadTimeout(10_000);
                connection.setRequestProperty("Accept", "application/vnd.github+json");
                connection.setRequestProperty("User-Agent", "S25ULTRA-MangaAMTL/" + BuildConfig.VERSION_NAME);
                JSONObject release;
                try (var input = connection.getInputStream()) {
                    release = new JSONObject(new String(input.readNBytes(1_048_576), StandardCharsets.UTF_8));
                }
                String tag = release.getString("tag_name");
                boolean available = !release.optBoolean("prerelease") && !release.optBoolean("draft") && newer(tag, BuildConfig.VERSION_NAME);
                activity.runOnUiThread(() -> {
                    if (activity.isFinishing() || activity.isDestroyed()) return;
                    if (available) new AlertDialog.Builder(activity).setTitle("Update available")
                        .setMessage("MangaAMTL " + tag + " is available. Open GitHub to download and install the new APK?")
                        .setNegativeButton("Later", null)
                        .setPositiveButton("Open release", (dialog, which) -> activity.startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(REPOSITORY + "/releases/latest")))).show();
                    else if (manual) Toast.makeText(activity, "You have the latest release", Toast.LENGTH_LONG).show();
                });
            } catch (Exception error) {
                if (manual) activity.runOnUiThread(() -> {
                    if (!activity.isFinishing() && !activity.isDestroyed()) Toast.makeText(activity, "Could not check GitHub. Try again later.", Toast.LENGTH_LONG).show();
                });
            } finally { if (connection != null) connection.disconnect(); }
        }, "github-update-check").start();
    }
}
