# Galaxy S25 Ultra device checks

Tested 2026-10-12 and 2026-10-13 on the connected Samsung SM-S938U, SM8750, Android API 36. This is a debug-signed ARM64 test build.

APK: `dist/MangaAMTL-S25-Ultra.apk` (1,676,261,950 bytes).

SHA-256: `e61244781a5cb4a3f3ce6ab7d853fc6515badb3d1aeb3476a2c33a88cb2a9db8`.

Updated extension: `../Extension-updated.zip`, SHA-256 `ed4892363e1da1d15456f6f1746bbf9223f82897f3919ef85e84404ff05db76c`.

## Passed

- Gradle `:app:assembleDebug`, `:app:lintDebug`, and `:npu-check:assembleDebug`. Lint has warnings, no errors.
- Python syntax checks and all four model-finder tests: valid installation/restoration, busy model switching, archive traversal, incomplete downloads, and refusal of a CPU model configuration.
- APK inspection: bundled `app.py` is byte-for-byte identical to the root source. No QNN CPU/GPU backend or GenieX/llama inference libraries are packaged.
- Known-output NPU arithmetic returned `[50, 60]`; an unsupported operator was rejected with CPU fallback disabled. Both use the same QAIRT 2.45 runtime as the server.
- Complete sample-page upload, heartbeat, polling, translation and PNG rendering with Qwen3-0.6B, Qwen3-1.7B and Qwen3-4B using the original Google Lens OCR. Qwen3-4B also completed the page with local Japanese NPU OCR. Repeated requests succeeded in one server process.
- Extension API checks: health, metadata, font listing, settings, CORS, original upload/poll/heartbeat/image routes, and rejection of cloud translation settings.
- QNN profiles for manga detection, CRAFT text detection, Japanese recognition and LaMa each recorded QNN kernel events with **zero other-provider kernel events**. Translation used the Genie `QnnHtp` backend.
- Synthetic recognition checks also passed for English, Korean, Chinese and Russian with the server's QAIRT runtime: finite outputs, one QNN kernel event and zero other-provider events for every model. These checks establish NPU compatibility, not reading accuracy.
- The 1.7B model downloaded and installed through the phone's finder API. The 4B official archive was downloaded on the host and copied into private app storage for testing.
- Browser verification: all three ranked models appeared, searching `4B` filtered the list correctly, and the Google Lens selector reflected the saved setting.
- App process restart preserved Qwen3-4B selection and Google Lens OCR. The foreground server resumed on localhost:7860; port 8000 was left with its existing PdaNet owner.
- Compiled detection, Japanese OCR and inpainting graphs were reused after restarting the app. This avoids repeating the several-minute initial OCR compilation.

## 2026-10-13 extension and font updates

- Ten Python checks passed, covering model download validation, live/stopped-server font imports, preservation of settings, invalid-font rejection, rollback after a failed font-selection save, and asynchronous rendering success/failure cleanup.
- All extension JavaScript passed syntax checks. Worker regression checks passed with no worker `FileReader`: signed image URL handling, original byte collection without a readable page canvas, oversized-image rejection, temporary rule cleanup, configured-backend restriction, settings migration, and multipart upload with colorization disabled.
- The extension worker's real upload, polling, heartbeat and async PNG handoff completed against the phone's NPU server using Qwen3-4B and Google Lens. The CDN response was supplied by the host test fixture; this is not a real website or browser-permissions test.
- A complete page also passed using local Japanese NPU OCR and the original blocking image endpoint. QNN profiles showed zero other-provider kernel events for detection, CRAFT, Japanese OCR and inpainting; translation used QnnHtp.
- The earlier unexplained shutdown was subsequently confirmed by the user to have been an accidental stop. No spontaneous shutdown was established.
- The APK includes the standard Android file picker and an **Import overlay font** button. Font validation/selection/persistence were tested on the host; the phone file-picker interaction still needs a manual check.

Raw reports, translated PNGs, original rendering calibration and Genie profiles are saved under `android/evidence/` (generated files, excluded from source control).

## 2026-10-13 Samsung background translation

- Ordinary-app virtual-display launch was rejected (`allowed=false`). A shell-privileged launch and UI text extraction succeeded on a separate display without changing the main display's focus.
- Installed official Shizuku 13.6.0 and added Shizuku API/provider 13.1.5. Samsung mode uses a permission-controlled Shizuku user service over Binder; no localhost helper port or USB runtime connection is required.
- Samsung mode was enabled in the installed APK. Three requests, including a repeated Japanese sentence, returned the correct corresponding English text while Android Settings remained the main resumed activity and received an injected scroll gesture. Each request's hidden display was removed. Evidence: `evidence/samsung-background-check.json`.
- A full seven-region page passed the existing HTTP upload, heartbeat, polling and PNG rendering workflow with Google Lens OCR and Samsung translation. The private runtime evidence identifies Samsung translation as `compute_unit: unverified`, while detector and LaMa profiles show QNN delegation only. The existing check script names its output using the selected Qwen catalog entry even when Samsung mode overrides translation.
- Eleven Python checks passed. Shizuku was started with the user's requested ADB starter for this test. Wireless-debugging startup on the phone was not tested because Wi-Fi was disconnected; the app links to installed Shizuku and documents its phone-only wireless setup. No reboot or long-session test was performed.

## Rendering and runtime limits

The original font-sizing, wrapping, color detection, stroke, glow, rotation and drawing functions remain unchanged. The fixed calibration matched font size, line breaks, line height and layout dimensions. One sampled text color differed by one RGB level between Windows and Android, and raster hashes differ. Pixel-identical rendering is therefore **not** established.

Local OCR uses NPU replacements rather than the desktop Hayai/GLM models. Short vertical Japanese lines can be misrecognized; Google Lens was more accurate on this sample. Replacement translation and LaMa weights also produce different outputs from the desktop models. The catalog's size-based order is expected quality, not a comprehensive translation benchmark.

Google Lens uploads the page to Google and needs network access. All local neural inference requires the NPU; serving, tokenization, preprocessing and drawing use the CPU. Colorization is excluded.

The actual browser-extension interface on the phone, all-language OCR accuracy, long reading sessions, thermal throttling and release/store packaging have not been tested. The compatible HTTP workflow was tested directly.
