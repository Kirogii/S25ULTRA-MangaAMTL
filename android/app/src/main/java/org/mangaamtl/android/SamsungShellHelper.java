package org.mangaamtl.android;

import android.app.UiAutomation;
import android.os.*;
import android.view.accessibility.*;
import java.io.*;
import java.util.*;
import java.util.concurrent.TimeUnit;

/** Shizuku user service: only reads Samsung on a caller-owned hidden display. */
public final class SamsungShellHelper extends Binder {
    private static final String PACKAGE = "com.samsung.android.app.interpreter";
    private final HandlerThread thread = new HandlerThread("Samsung UI reader");
    private UiAutomation automation;
    public SamsungShellHelper() { thread.start(); }
    @Override protected synchronized boolean onTransact(int code, Parcel data, Parcel reply, int flags) {
        if (code == 16777115) { System.exit(0); return true; }
        if (code != 1) return false;
        int appUid = Binder.getCallingUid();
        long identity = Binder.clearCallingIdentity();
        try {
            data.enforceInterface("org.mangaamtl.android.Samsung");
            int display = data.readInt();
            String source = data.readString();
            if (source == null || source.isBlank() || source.length() > 4000 || display <= 0) throw new IOException("Invalid translation request");
            Object manager = Class.forName("android.hardware.display.DisplayManagerGlobal").getMethod("getInstance").invoke(null);
            Object displayInfo = manager.getClass().getMethod("getDisplayInfo", int.class).invoke(manager, display);
            if (displayInfo == null || displayInfo.getClass().getField("ownerUid").getInt(displayInfo) != appUid
                || !"MangaAMTL Samsung".equals(displayInfo.getClass().getField("name").get(displayInfo)))
                throw new IOException("Translation display does not belong to caller");
            if (automation == null) {
                Object connection = Class.forName("android.app.UiAutomationConnection").getConstructor().newInstance();
                automation = (UiAutomation) UiAutomation.class.getConstructor(Looper.class,
                    Class.forName("android.app.IUiAutomationConnection")).newInstance(thread.getLooper(), connection);
                UiAutomation.class.getMethod("connect", int.class).invoke(automation, UiAutomation.FLAG_DONT_SUPPRESS_ACCESSIBILITY_SERVICES);
                var info = automation.getServiceInfo();
                info.flags |= android.accessibilityservice.AccessibilityServiceInfo.FLAG_RETRIEVE_INTERACTIVE_WINDOWS;
                automation.setServiceInfo(info);
            }
            String translated = translate(display, source);
            reply.writeNoException(); reply.writeString(translated);
        } catch (Exception error) { reply.writeException(new IllegalStateException("Samsung translation failed: " + error)); }
        finally { Binder.restoreCallingIdentity(identity); }
        return true;
    }
    private String translate(int display, String source) throws Exception {
        java.lang.Process process = new ProcessBuilder("/system/bin/am", "start", "--display", Integer.toString(display),
            "-a", "android.intent.action.PROCESS_TEXT", "-t", "text/plain", "-n", PACKAGE + "/.translation.view.TranslationActivity",
            "--es", "android.intent.extra.PROCESS_TEXT", source, "--ez", "android.intent.extra.PROCESS_TEXT_READONLY", "true",
            "--es", "source_language_code", "auto", "--es", "target_language_code", "en",
            "-f", "0x18000000").redirectErrorStream(true).start();
        if (!process.waitFor(10, TimeUnit.SECONDS)) { process.destroyForcibly(); throw new IOException("Samsung launch timed out"); }
        String output = new String(process.getInputStream().readAllBytes(), java.nio.charset.StandardCharsets.UTF_8);
        if (process.exitValue() != 0 || output.contains("Error:") || output.contains("Exception")) throw new IOException(output);
        long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(25);
        long launched = System.nanoTime();
        List<String> lastTexts = new ArrayList<>();
        while (System.nanoTime() < deadline) {
            var windows = automation.getWindowsOnAllDisplays().get(display);
            if (windows != null) for (AccessibilityWindowInfo window : windows) {
                List<String> texts = new ArrayList<>(); collect(window.getRoot(), texts);
                lastTexts = texts;
                if (texts.contains(source) && texts.contains("English detected")
                        && System.nanoTime() - launched > TimeUnit.MILLISECONDS.toNanos(300)) return source;
                for (int i = 0; i + 2 < texts.size(); i++) if (source.equals(texts.get(i))
                        && ("English".equals(texts.get(i + 1)) || texts.get(i + 1).startsWith("English ("))) {
                    String candidate = texts.get(i + 2).trim();
                    if (candidate.equals(source) && texts.contains("English detected")) return source;
                    if (!candidate.isEmpty() && !candidate.equals(source) && !candidate.equals("Copy")) return candidate;
                }
            }
            Thread.sleep(50);
        }
        throw new IOException("Samsung returned no English translation; UI labels: " + lastTexts);
    }
    private static void collect(AccessibilityNodeInfo node, List<String> texts) {
        if (node == null) return;
        if (PACKAGE.contentEquals(node.getPackageName() == null ? "" : node.getPackageName()) && node.getText() != null)
            texts.add(node.getText().toString());
        for (int i = 0; i < node.getChildCount(); i++) collect(node.getChild(i), texts);
    }
}
