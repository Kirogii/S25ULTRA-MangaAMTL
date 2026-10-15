# Android extension

Replace the old extension with `Extension-updated.zip`, or reload this folder as an unpacked extension. Reload the manga tab afterward. Use an Android browser which supports Manifest V3 extensions. The replacement ZIP is also copied to the test phone's Downloads as `MangaAMTL-Android-Extension-3.0.4.zip`.

With Samsung translation enabled, Combine Pages set to 1, context off, and all discovered page dimensions at most 4 megapixels, two independent pages can overlap. Larger pages, combined strips, context-dependent runs and Qwen remain serial. Local neural inference remains serialized by the server; only two pages can be in flight. Heartbeat updates are serialized so concurrent jobs cannot overwrite each other's registration.

**Translation engine** in the popup and options reads the Android server's active choice and switches between Samsung language packs and the selected Qwen NPU model. Samsung mode locks the target to English. Start Shizuku and authorize MangaAMTL on the phone first; no USB is needed during use. Google Lens/local OCR and overlay fonts remain separate settings. Samsung's NPU use is unverified. Changing engines is rejected while a page is processing; a stopped server or missing Shizuku permission is shown as an error. This control requires the updated Android APK with `/v1/samsung/settings`.

Version 3.0.3 polls processing/rendering every 100 ms and uploads original PNG/JPEG bytes without re-encoding them on a canvas. Install optional OCR and manga-inpainting packs from Downloads using the app's install buttons, or use a build that bundles those components. Qwen is an optional model-finder download. Samsung-detected English regions remain unchanged instead of waiting for a different translation.

This build migrates saved desktop settings once: localhost:7860, local NPU translation, LaMa NPU inpainting, no colorization/cloud translation, and low text context. A previously chosen compatible OCR mode is retained; otherwise Google Lens is selected. Source/target languages and a custom backend URL are retained. Google Lens uploads the page to Google; local OCR stays on the phone.

Find translation models in Advanced Settings → **Find and download S25 Ultra NPU models**, or visit `http://localhost:7860/models`. Import TTF, OTF or TTC fonts through the Android app's **Import overlay font** button, then choose them in the extension's font picker if needed. The imported font is selected immediately on the server and persists after restart. Large fonts remain usable for overlays; preview downloads above 16 MB are skipped to limit browser memory.

Image download and backend polling run in the extension worker, using its host permissions. HTTP image bytes do not depend on the page's canvas being readable. Downloads retain cookies and use a temporary Referer rule limited to this extension and the requested image URL. Relative URLs, responsive images, inline images and blob URLs are supported. PNG/JPEG files are uploaded directly; other formats and combined strips are converted to PNG before sending to Android. Groups fail without replacing any pages when a page cannot be downloaded.

Limits: 32 MB per downloaded/uploaded image and 40 megapixels per page or combined strip. Lower **Combine Pages** for large chapters. Authentication challenges, revoked blob URLs and restrictive page image policies can still prevent collection or replacement; the extension reports the error and keeps the original page.

Checks: `node tests/extension.test.cjs` from the project root; add `--phone` after forwarding host tcp:17860 to phone tcp:7860 to exercise upload, heartbeat, polling and rendered PNG handoff against Android. The browser UI itself still needs a manual check in the chosen Android browser.
