package org.mangaamtl.android;

import android.content.*;
import android.os.*;
import java.util.concurrent.*;
import rikka.shizuku.Shizuku;

final class SamsungSetup {
    private static volatile IBinder service;
    private static final ServiceConnection connection = new ServiceConnection() {
        public void onServiceConnected(ComponentName name, IBinder binder) { service = binder; }
        public void onServiceDisconnected(ComponentName name) { service = null; }
    };
    static synchronized IBinder ensure(Context context) throws Exception {
        if (!Shizuku.pingBinder()) throw new IllegalStateException("Open Shizuku and start it using Wireless debugging on this phone. No USB or computer is required.");
        if (Shizuku.checkSelfPermission() != android.content.pm.PackageManager.PERMISSION_GRANTED)
            throw new IllegalStateException("Allow MangaAMTL in Shizuku, then tap Start Samsung helper again.");
        if (service != null && service.pingBinder()) return service;
        Shizuku.bindUserService(new Shizuku.UserServiceArgs(new ComponentName(context, SamsungShellHelper.class))
            .daemon(false).processNameSuffix("samsung").version(9), connection);
        long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(12);
        while (service == null && System.nanoTime() < deadline) Thread.sleep(100);
        if (service == null || !service.pingBinder()) throw new IllegalStateException("Shizuku could not start the Samsung helper. Check Shizuku's status.");
        return service;
    }
}
