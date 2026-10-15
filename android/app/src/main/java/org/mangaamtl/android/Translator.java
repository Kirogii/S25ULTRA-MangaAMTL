package org.mangaamtl.android;

import android.content.Context;
import com.chaquo.python.PyObject;
import com.chaquo.python.Python;
import java.io.File;

final class Translator implements AutoCloseable {
    private final PyObject model;

    Translator(Context context, File bundle) {
        model = Python.getInstance().getModule("genie_translation").callAttr("Translator",
                bundle.getAbsolutePath(), context.getApplicationInfo().nativeLibraryDir);
    }

    String generate(String messagesJson, int maxTokens, float temperature, float topP) {
        return model.callAttr("generate", messagesJson, maxTokens, temperature, topP).toString();
    }

    @Override public void close() {
        model.callAttr("close");
        model.close();
    }
}
