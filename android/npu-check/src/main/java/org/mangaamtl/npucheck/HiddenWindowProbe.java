package org.mangaamtl.npucheck;

import android.app.UiAutomation;
import android.os.HandlerThread;
import android.view.accessibility.AccessibilityNodeInfo;
import android.view.accessibility.AccessibilityWindowInfo;

/** Shell-only check that hidden-display translations remain readable. */
public final class HiddenWindowProbe {
    public static void main(String[] args) throws Exception {
        HandlerThread thread = new HandlerThread("hidden-window-probe"); thread.start();
        UiAutomation automation = null;
        try {
            Class<?> connection = Class.forName("android.app.UiAutomationConnection");
            Object binder = connection.getConstructor().newInstance();
            automation = (UiAutomation) UiAutomation.class.getConstructor(android.os.Looper.class,
                Class.forName("android.app.IUiAutomationConnection")).newInstance(thread.getLooper(), binder);
            UiAutomation.class.getMethod("connect", int.class).invoke(automation, UiAutomation.FLAG_DONT_SUPPRESS_ACCESSIBILITY_SERVICES);
            android.accessibilityservice.AccessibilityServiceInfo info = automation.getServiceInfo();
            info.flags |= android.accessibilityservice.AccessibilityServiceInfo.FLAG_RETRIEVE_INTERACTIVE_WINDOWS;
            automation.setServiceInfo(info);
            Thread.sleep(1500);
            var windows = automation.getWindowsOnAllDisplays();
            for (int i = 0; i < windows.size(); i++) {
                System.out.println("DISPLAY " + windows.keyAt(i));
                for (AccessibilityWindowInfo window : windows.valueAt(i)) read(window.getRoot());
            }
        } finally {
            if (automation != null) UiAutomation.class.getMethod("disconnect").invoke(automation);
            thread.quitSafely();
        }
    }
    private static void read(AccessibilityNodeInfo node) {
        if (node == null) return;
        if ("com.samsung.android.app.interpreter".contentEquals(node.getPackageName() == null ? "" : node.getPackageName()) && node.getText() != null)
            System.out.println(node.getText());
        for (int i = 0; i < node.getChildCount(); i++) read(node.getChild(i));
    }
}
