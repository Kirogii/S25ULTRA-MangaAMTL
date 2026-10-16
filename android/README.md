# Android localhost server for Galaxy S25 Ultra

## Live screen translation (1.0.0)

Open MangaAMTL and enable **Live screen translation · floating button**. Android opens **Display over other apps**; allow MangaAMTL and return. A draggable **Live** button appears over other apps. Tap it, review the upload disclosure, and approve Android's screen-capture prompt. The requested capture is the whole display. Tap **Stop** to end capture, or use the notification's Stop action to remove the floating controls entirely. Turning the live switch off also removes them.

Live mode reuses the selected OCR and Samsung/Qwen translation method. In Lens mode, local YOLO and general text detection find candidate regions first. Sparse text crops are packed into one Lens request and mapped back to screen coordinates, retaining detected GUI labels outside manga boxes. Dense images or unavailable general detection fall back to the screen-section image. **Live background: Blur (off = None)** defaults to the existing TextPhantom cropped Telea eraser; None draws translated text without erasing the background. No neural inpainting model runs. Changing the switch clears old overlays and screenshot history so the next result uses the new mode. **Live source** selects the source language; Auto requires Google Lens. Samsung language packs currently output English. The localhost server must remain running, and the normal model/language-pack requirements still apply.

**Cache live translations with matching screen context** enables an in-memory, bounded cache. Keys include the complete source text, ordered screen text context, region position in that context, source/target languages and translation model. Extended sentences, changed context and repeated identical words in different regions cannot collide. Disabling caching bypasses and clears this cache on the next processed frame. Samsung's existing page cache is bypassed for live frames. Unchanged frames skip redundant OCR requests; changed frames are processed one at a time, without a growing queue.

In Google Lens mode, captured screen images are sent to Google. Screen capture begins only after Android's consent prompt and stops when the floating Stop button is pressed, Android ends projection, or live mode is disabled. Protected/secure app content may not be capturable. Nothing records screen images to disk.

Recent whole-screen tracking snapshots and translated regions remain in RAM (up to 16 snapshots and approximately 16 MB of image/encoded-overlay data). When you scroll back, feature matches recover each section's position; visible text pixels must also match before an old overlay returns. Offscreen overlays are not drawn. Changed sections require OCR again, with full-width neighboring line context to avoid splitting sentences. This history is discarded when capture ends or resizes. It remembers previously seen content; it cannot capture never-visible content from an arbitrary app.

Android's touch security requires the text overlay to remain translucent (at most the platform's obscuring-opacity limit), so original lettering may faintly show through. The text layer does not consume touches; only the floating control does. Optical flow moves individual translated regions with scrolling, keeps partially visible regions clipped to their panel, and leaves stationary headers and bottom bars independent. Changed or offscreen regions are removed. Newly exposed sections are cropped for OCR while existing translations keep tracking. Captured pixels are reconstructed beneath the translucent overlay so it does not periodically hide for capture. Async OCR results follow their tracked section and are discarded if that section disappears. Google Lens network latency still limits new translations; this is not a 0.20-second or video-rate guarantee.

Checks: `python -m unittest android/test_live_tracking.py android/test_live_translation.py android/test_android_lens.py`, Android `assembleDebug`/`lintDebug`, debug instrumentation `org.mangaamtl.android/.LiveTrackingChecks`, and `python android/check_live.py` for the real phone endpoint using the known Raw sample. Actual capture/scroll/touch validation requires the user to approve Android's overlay and capture permissions.

Install the generated `app-debug.apk`, open **MangaAMTL**, and tap **Start localhost server**. First start copies the bundled models and font into private storage. Keep the foreground service running while using the browser extension.

Set the extension's server URL to **http://localhost:7860**. Open **http://localhost:7860/models** or tap **Find and download NPU models** to search, download, and select a model. Google Lens is available in the OCR selector and the original extension settings.

Use the updated `Extension-updated.zip` at the project root, replace/reload the extension, and reload the manga tab. This extension migrates desktop settings to local NPU translation, LaMa inpainting and no colorizer, and routes backend requests through its worker. Image requests with `Prefer: respond-async` receive HTTP 202 while rendering and a PNG when ready, avoiding a long background-worker request. Existing clients retain the original blocking image endpoint.

Tap **Import overlay font (.ttf, .otf, .ttc)** in the Android app to choose a font file. The app copies it into private storage, validates it with Pillow/FreeType, selects it for the original overlay renderer, and saves the selection across restarts. Imported fonts appear in the extension's existing font picker. The import limit is 320 MB; font preview downloads above 16 MB are skipped to limit browser memory.

The server also listens on localhost:8000 if that port is available. On the test phone PdaNet already occupies port 8000, so use 7860. Requests stay on the phone's loopback interface. An extension running on another computer needs an ADB forward; that computer's localhost normally refers to itself.

## Models and behavior

| Task | Android implementation |
|---|---|
| Text regions | Original manga YOLOv8l weights, fixed 640×640 ONNX, QNN HTP |
| Local OCR | EasyOCR equivalents for Japanese, Korean, Chinese, Russian and English, QNN HTP; CRAFT plus unrolled recognizers |
| Google Lens OCR | The original `app.py` Google Lens function, including grouping, angles and NPU YOLO regions |
| Translation | Qualcomm Qwen3 W4A16 bundles compiled for Snapdragon 8 Elite for Galaxy; Genie with QnnHtp backend |
| Neural inpainting | LaMa Dilated on QNN HTP, retaining original crop, tiling, flat fill, color correction and blending methods |
| Font sizing, wrapping, text color, strokes, glow and drawing | Unmodified Python functions from `app.py`, with the original NotoCJK font |
| Colorizer | Excluded |

All local neural model operations require the NPU. Unsupported operators fail; CPU/GPU inference fallback is disabled. HTTP serving, tokenization, image preprocessing, file operations and Pillow/OpenCV rendering run on the CPU. Google Lens is optional cloud OCR and uploads the page to Google; it is not an NPU model.

The finder lists the following models in increasing expected quality. This ordering reflects model size, not a measured manga benchmark or an exhaustive list of every possible S25 model.

| Model | Download | Use |
|---|---:|---|
| Qwen3-0.6B | Included in APK | Smallest, lower translation quality |
| Qwen3-1.7B | 1.54 GB | Middle option |
| Qwen3-4B | 2.54 GB | Recommended; best translations in our sample |

All three use on-device NPU inference. Larger models require additional private storage and memory. The finder checks free space before downloading, validates archive paths, sizes, CRCs and NPU configuration, and shows progress/errors. Interrupted downloads restart when retried. Selection persists across app restarts; switching is rejected while a translation/render job is active.

Local OCR uses replacement models, so its text and resulting overlay boxes can differ from desktop Hayai/GLM. Vertical Japanese recognition needs particular care; Google Lens currently gives better recognition on the sample page. The `hayai` and `glm` API identifiers are retained for extension compatibility, but select the NPU equivalents on Android.

The original rendering methods and font are preserved. Calibration matched font sizes, line breaks, line heights and layout dimensions. Android and Windows imaging libraries produced a one-level RGB difference in one sampled color and different raster hashes, so pixel-identical rendering is not claimed. Replacement OCR, translation and inpainting models also change their outputs.

QNN compiles each local model the first time it is used; Japanese OCR can take several minutes initially. Compiled NPU graphs are cached for subsequent starts. Keep the service running and leave enough free storage for the compilation cache. The original extension's upload, polling, heartbeat and image endpoints are retained.

## Build and checks

### Optional models and build profiles

Offline model weights are optional. The Android app has separate **Install OCR / inpainting / translation model pack** buttons using Android's file picker. Stop the server before importing a pack. Install only the ZIP for the component you want; files are validated against the build's catalog before any installed model is replaced. Custom exported OCR/inpainting packs are provided in Downloads because these exact NPU conversions are not hosted publicly. Qwen models can instead be downloaded directly from the model finder, including the optional 0.6B model.

Build defaults exclude all model weights. Include components explicitly:

```text
gradlew.bat :app:assembleDebug -PbundleOcr=true -PbundleInpainting=true -PbundleTranslation=false
```

The APK provided for this request uses that OCR-plus-inpainting profile. `bundleTranslation=true` optionally includes Qwen3-0.6B; leave all three flags false for the smallest build. Fonts, Python/runtime libraries and the small compatibility catalog remain included. `prepare_models.py --anime-lama` prepares verified converted manga-inpainting stages and optional ZIP packs. See ANIME_LAMA.md for conversion details and device limits.

Samsung translation now caches repeated text, leaves Samsung-detected English lettering unchanged, and skips non-letter text. Completely uniform images skip OCR. The extension checks jobs and asynchronous rendering every 350 ms instead of waiting five/two seconds. Nonuniform no-text pages still require OCR; Google Lens network latency remains outside the Samsung translator.

### Optional Samsung language packs

The app's **Samsung language packs (English output)** switch routes translation through Samsung Interpreter on a hidden virtual display. Original OCR, inpainting and overlay rendering remain in place. The normal extension's local translation setting still applies. Switch it off to use the selected Qwen model.

Install Shizuku, open it using the app's **Open Shizuku / phone-only setup** button, and follow its Wireless debugging pairing/start instructions. Then enable Samsung mode, allow MangaAMTL's Shizuku permission, and enable the switch again. No USB or computer is required. Shizuku needs restarting on the phone after reboot or if Android kills it; unavailable-helper errors do not silently switch translation engines. English must be selected as the target in Interpreter, and suitable Samsung language packs must already be installed. This mode translates text regions independently rather than using the Qwen batch prompt or its context/name hints.

The APK alone cannot launch Samsung on an untrusted offscreen display: the phone rejected that launch. A Shizuku user service performs the privileged launch and reads only Samsung's translated UI text from the requested caller-owned display. Requests use Binder, not an exposed network server. No touchscreen input is injected into the main display. Display destruction removes its contents instead of moving the translation window onto the main screen. Samsung's internal CPU/NPU delegation is unverified; the Qwen NPU guarantees above apply to Qwen mode. Shizuku setup: https://shizuku.rikka.app/guide/setup/

`python -m unittest android/test_samsung_translation.py` checks selection, ordering, blank text and validation. `/v1/samsung/status` reports mode; `/v1/samsung/check` accepts `{"text":"…"}` for an explicit device test independently of mode selection.

Use JDK 17+, Android SDK platform/build-tools 36, and the Gradle wrapper. `android/local.properties` sets `sdk.dir`. The Python build interpreter in `app/build.gradle` points to the local Python 3.10 runtime under `.android-tools/python`; adjust that path on another computer. Chaquopy downloads Android Python wheels during the first online build.

Generated models, SDK libraries, build outputs and device evidence are excluded by `.gitignore`. This workspace already contains the prepared assets. To regenerate them:

1. Run `python android/fetch_runtime.py` to fetch the required QAIRT 2.45 Android/HTP V79 libraries from Qualcomm's official SDK archive. Python `requests` is required.
2. Run `android/export_detector.py` with PyTorch, ONNX and Ultralytics 8.3.190. It verifies the original YOLO checkpoint hash before exporting.
3. Run `android/export_ocr.py --language all` with EasyOCR 1.7.2, PyTorch and ONNX. Its assertions compare each unrolled recognizer to the original Torch output.
4. Place the AI Hub EasyOCR detector, LaMa Dilated ONNX models and the Qwen3-0.6B Genie bundle under the paths listed in `prepare_models.py`. The compiled translation bundle targets **Samsung Galaxy S25 Ultra**, precision **W4A16**, runtime **Genie**, AI Hub Models release **0.64.0**. Place the original `NotoCJK.ttc` in `android/models/app-bundle/fonts/`.
5. Run `python android/prepare_models.py`, then `android/gradlew.bat -p android :app:assembleDebug :app:lintDebug`. The build copies the current root `app.py` and `jinja.txt` into the APK without editing them.

Install the APK with `adb -s SERIAL install -r APK`. For host testing, forward `tcp:17860` to `tcp:7860`, then run:

```text
python -m unittest android/test_model_finder.py -v
python -m unittest android/test_android_helpers.py -v
node tests/extension.test.cjs
node tests/extension.test.cjs --phone
python android/check_server.py --url http://127.0.0.1:17860 --ocr-mode lens
python android/check_server.py --url http://127.0.0.1:17860 --ocr-mode hayai --timeout 900
```

`check_server.py` exercises health, settings, font listing, extension CORS, prohibited cloud translation, upload, heartbeat, polling and PNG rendering. `render_fixture.py` checks the original font/layout/color methods at server startup. `npu-evidence.json` in the app's private files records QNN kernel delegation; each selected translation bundle contains `genie-profile.json` with measured generation timings. `npu-check` is a separate diagnostic APK with known-output arithmetic and an unsupported-operator negative test.

Model/runtime references and their license terms: [Qualcomm AI Hub Models](https://github.com/qualcomm/ai-hub-models), [QAIRT](https://developer.qualcomm.com/software/qualcomm-ai-engine-direct-sdk), [original manga detector](https://huggingface.co/Kirogii/Yolo-Manga_Textbox-Region_Detect), [EasyOCR](https://github.com/JaidedAI/EasyOCR), [Qwen3](https://huggingface.co/Qwen), and [Google Lens client](https://pypi.org/project/chrome-lens-py/). This is a debug-signed test APK, not a store release.
