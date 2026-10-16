# S25ULTRA-MangaAMTL

Manga and live screen translation for Samsung Galaxy S25 Ultra (Android 15+, ARM64). Based on [MangaAMTL](https://github.com/Kirogii/MangaAMTL).

## Install

1. Download the APK and extension ZIP from [Releases](https://github.com/Kirogii/S25ULTRA-MangaAMTL/releases/latest). Install the APK.
2. **Shizuku is required for Samsung translation.** [Install Shizuku](https://shizuku.rikka.app/download/), pair and start it through Wireless debugging, then authorize MangaAMTL. Restart Shizuku after reboot.
3. Install the source-language pack in Samsung Interpreter and select English as its target. Enable Samsung translation in MangaAMTL.
4. Tap **Start localhost server**. Install the extension ZIP in an Android browser that supports extensions. Set its server to `http://localhost:7860`, select Google Lens OCR, and open a manga page.
5. For live screen translation, enable the floating button, allow display over other apps, tap **Live**, and approve whole-screen capture. Scroll and tap normally; **Stop** ends capture.

Google Lens uploads detected text crops to Google, with a screen-section fallback when needed. Live mode uses the selected Samsung/Qwen translation method. This release bundles no AI model weights. Download optional OCR, translation and inpainting packs separately; Samsung translation uses installed Samsung language packs. Live background defaults to None; enable Blur for TextPhantom erasure. Translation caching is optional and matches complete text and region context.

On a Galaxy S25 Ultra, the Google Lens plus Samsung Translate cloud-assisted path takes about **1.07 seconds** in the measured warm live benchmark. Actual times vary with network conditions and whether text is cached. **Samsung Translate requires the Samsung Interpreter/Translate app and its installed language packs on the phone; MangaAMTL cannot provide that app.**

The app checks GitHub for updates once daily when opened. **Check for updates** checks immediately and offers the release download when a newer version exists. Install the new APK over the old version.

## Build

Use JDK 21, Python 3.10, and Android SDK 36. Download `build-inputs.zip` from v1.0.0, verify it with `android/build-inputs.sha256`, and extract it into `android/`. It contains the pinned runtime, font, catalog, and OCR assets. Run:

```sh
android/gradlew -p android :app:assembleDebug -PbuildPython=python3.10 -PbundleOcr=false -PbundleInpainting=false -PbundleTranslation=false
```

GitHub Actions builds APK and extension on version tags and publishes them to Releases. The repository signing secret preserves update compatibility. This is a debug-signed sideload build, not a Play Store package.

See [Android details](android/README.md), [third-party notices](THIRD_PARTY_NOTICES.md), and [upstream](https://github.com/Kirogii/MangaAMTL).
