package org.mangaamtl.npucheck;

import android.app.Activity;
import android.icu.util.ULocale;
import android.os.Bundle;
import android.view.translation.*;
import android.widget.TextView;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.io.File;
import java.util.List;
import java.util.concurrent.*;
import org.json.*;

/** Ordinary-app probe of the public translation API; no Samsung permissions. */
public final class TranslationProbeActivity extends Activity {
    private TextView status;
    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        status = new TextView(this); status.setText("Checking Samsung's public translation provider…");
        status.setTextSize(18); status.setPadding(24, 48, 24, 24); setContentView(status);
        new Thread(this::check, "translation-api-check").start();
    }
    private void check() {
        JSONObject report = new JSONObject();
        ExecutorService callbacks = Executors.newSingleThreadExecutor();
        Translator translator = null;
        try {
            TranslationManager manager = getSystemService(TranslationManager.class);
            if (manager == null) throw new IllegalStateException("No platform translation manager");
            JSONArray capabilities = new JSONArray();
            for (TranslationCapability capability : manager.getOnDeviceTranslationCapabilities(TranslationSpec.DATA_FORMAT_TEXT, TranslationSpec.DATA_FORMAT_TEXT)) {
                capabilities.put(new JSONObject().put("source", capability.getSourceSpec().getLocale().toLanguageTag())
                    .put("target", capability.getTargetSpec().getLocale().toLanguageTag()).put("state", capability.getState()));
            }
            report.put("capabilities", capabilities);
            CompletableFuture<Translator> created = new CompletableFuture<>();
            TranslationContext context = new TranslationContext.Builder(
                new TranslationSpec(ULocale.JAPANESE, TranslationSpec.DATA_FORMAT_TEXT),
                new TranslationSpec(ULocale.ENGLISH, TranslationSpec.DATA_FORMAT_TEXT)).build();
            manager.createOnDeviceTranslator(context, callbacks, created::complete);
            translator = created.get(25, TimeUnit.SECONDS);
            report.put("translator_created", translator != null);
            if (translator != null) {
                CompletableFuture<TranslationResponse> translated = new CompletableFuture<>();
                String source = "自分の手で作りたい";
                TranslationRequest request = new TranslationRequest.Builder().setTranslationRequestValues(List.of(TranslationRequestValue.forText(source))).build();
                translator.translate(request, null, callbacks, translated::complete);
                TranslationResponse response = translated.get(25, TimeUnit.SECONDS);
                report.put("response_status", response.getTranslationStatus()).put("source", source);
                JSONArray values = new JSONArray();
                for (int i = 0; i < response.getTranslationResponseValues().size(); i++) {
                    TranslationResponseValue value = response.getTranslationResponseValues().valueAt(i);
                    values.put(new JSONObject().put("status", value.getStatusCode()).put("text", String.valueOf(value.getText())));
                }
                report.put("values", values);
                report.put("usable", response.getTranslationStatus() == TranslationResponse.TRANSLATION_STATUS_SUCCESS
                    && values.length() > 0 && values.getJSONObject(0).getInt("status") == TranslationResponseValue.STATUS_SUCCESS
                    && !values.getJSONObject(0).getString("text").isBlank() && !values.getJSONObject(0).getString("text").equals(source));
            } else report.put("usable", false);
        } catch (Exception error) {
            try { report.put("usable", false).put("error", error.toString()); } catch (JSONException ignored) { }
        } finally {
            if (translator != null) translator.destroy();
            callbacks.shutdownNow();
        }
        try {
            String result = report.toString(2);
            Files.write(new File(getFilesDir(), "translation-api-report.json").toPath(), result.getBytes(StandardCharsets.UTF_8));
            android.util.Log.i("SamsungTranslationProbe", result);
            runOnUiThread(() -> status.setText(result));
        } catch (Exception error) { android.util.Log.e("SamsungTranslationProbe", "Could not save report", error); }
    }
}
