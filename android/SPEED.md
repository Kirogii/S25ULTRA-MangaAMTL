# S25 Ultra speed checks — October 14, 2026

## October 15: Lens detection overlap

### External Lens latency audit

Direct timing around the Lens client's `post_raw` call measured 0.952, 0.963, 0.955 and 0.970 seconds on four warm requests. Total OCR for those pages was 1.013–1.032 seconds. The existing client already pools HTTP/2 connections and sends JPEG quality 40; these figures separate the external request from local preprocessing, protobuf parsing and grouping. No response contents or credentials are logged.

A private, non-overlapping routing-session reuse experiment preserved the Raw result and recognized two different pages correctly. Warm HTTP times of 0.969, 0.945 and 0.934 seconds did not establish a meaningful improvement over the baseline. Session reuse was removed; original fresh-session behavior is retained. Evidence: `lens-http-breakdown.json`, `lens-session-reuse.json`, and `lens-session-page{1,2}.json`. The direct HTTP timing remains available in the console as `[Lens HTTP]`.

The external request alone exceeds the 0.20-second target in these measurements. Further local changes cannot remove that observed external delay; the fresh-page target remains unverified and unmet.

### Optional status waits

Extension 3.0.5 requests `?wait=0.5` when checking a translation job. The Android server holds that request for at most 500 ms and wakes it as soon as processing finishes. A response header confirms support; the extension retains 100 ms polling for older servers. It does not keep an MV3 worker request open, change OCR, or cache completed pages.

The combined build includes the concurrent blur changes plus both earlier speed optimizations. In the warm Raw sample, status waits used two status requests per job versus seven with legacy polling. Warm waits measured 1.306–1.332 seconds; the adjacent legacy run measured 1.390–1.414 seconds. First runs after restart took longer. Network variability prevents attributing the whole difference to polling. A 0.20-second full pipeline remains unachieved.

All 22 selected Python checks, status-wait and page-queue browser checks, extension worker checks, Android assembly and lint passed. Evidence: `status-wait-enabled.json` and `status-wait-legacy.json`. The server build is installed. The browser optimization requires reloading/installing `MangaAMTL-Extension-status-wait.zip` and reloading the manga tab.

### Bounded width-measurement cache

The next installed build caches identical `draw.textlength` requests within each font-fitting call, with a maximum of 1,024 entries. Each cache is released after that call, so it does not retain chapter images or stale font settings. It wraps the existing fitting function without changing its search, font sizes, or wrapping rules. Google Lens remains the OCR engine.

Host profiling of the seven-region sample found 454 duplicate requests among 1,799 measurements; a page-scoped experimental cache reduced fitting from 86.6 ms to 58.0 ms. The shipped cache is scoped more narrowly to each fitting call. On the phone, warm median HTTP rendering decreased from 297.1 ms to 247.2 ms across the adjacent before/after runs. Total updated warm pipeline latency ranged from 1.025 to 1.171 seconds; its first page after restart took 2.937 seconds. These timings use cached dialogue, background fill, and the Raw sample, and do not establish a network-independent speed guarantee.

All seven layout logs and translation results matched. Pixel differences were at most one RGB level, also observed between unchanged baseline repeat runs; strict pixel equality is not claimed for this pass. The cache regression checks identical layouts, including repeated words, long-word fallback, empty text and vertical text. All 20 selected Python checks, Android assembly and lint passed. Evidence: `android/evidence/speed/text-cache-{before,after}.json` and `text-measure-host.json`.

Concurrent blur development is preserved. This measurement APK predates those new blur edits; the other chat is coordinating the next combined build.

The Android Lens adapter now starts the existing NPU text-box detector while the Google Lens request is in flight. It awaits the same detector result before grouping Lens text. Original text sizing, rendering, model weights and OCR engine remain unchanged. Empty or failed Lens requests clean up their detector future; detector errors still propagate when grouping needs its result.

On the connected SM-S938U, the seven-region Raw sample measured 1.936–2.398 seconds before updating. After updating and restarting, warm pages measured 1.033–1.237 seconds; the first page took 3.381 seconds. Translations and decoded output pixels matched the before-update sample exactly. These are complete HTTP submit/translate/render measurements with cached dialogue and background fill, not unseen-page or browser-display timings. Network variability, app restart and phone foreground state mean the full difference cannot be attributed to detector overlap alone.

With neural inpainting enabled, the updated build measured 2.039–2.195 seconds warm and 3.194 seconds on its first run. The original `inpaint_mode=none` setting was restored. Google Lens remains selected. A 0.20-second end-to-end target was not achieved; measured Lens OCR alone took 0.640–0.761 seconds in the warm updated runs.

Validation: 19 relevant Python checks, the browser page-queue check, `assembleDebug`, and `lintDebug` passed. Evidence is under `android/evidence/speed/lens-overlap-{before,after,inpaint}*`. The tested APK is installed; the prior installed APK is saved as `android/dist/pre-lens-overlap.apk` for rollback.

## Version 0.4: one-second target attempt

The installed 0.4 build uses the same 27-stage, 256-resolution anime LaMa model compiled with QNN finalization optimization 3. No weights, resolution, mask, crop, blending or reference sizing methods changed. Warm native inpainting improved from approximately 0.25 seconds to 0.154 seconds per crop, with identical measured mean/max reference error (0.000166617 / 0.00674385). The installed provider evidence verifies all 27 stages and zero non-QNN kernel events.

The final installed native check measured 0.1517 and 0.1524 seconds warm. A 15-stage grouped model compiled with optimization 3 passed the same fidelity check but took 0.1675 seconds warm, so the faster 27-stage model is retained. Candidate files were removed from the phone after testing; workspace artifacts remain available.

The Lens detector's blocking Java/NPU call now runs on the existing OCR executor instead of blocking the HTTP event loop. Only that call is transformed in the loaded Lens function; original rendering/sizing functions remain untouched. All 23 Python checks pass, including thread/result/error behavior and the assertion that no other upstream function is transformed.

Extension 3.0.4 overlaps at most two small independent pages with Samsung enabled, context off and Combine Pages 1. Its heartbeat storage mutations are serialized. Queue, heartbeat, upload and settings checks pass. It is in Downloads as `MangaAMTL-Android-Extension-3.0.4.zip`; it requires install/reload and a manga-tab reload to activate. Three workers gave no clear throughput improvement and increased individual latency, so they are not enabled.

On the seven-region Raw sample with warmed translation cache, 12 distinct jobs with NPU inpainting averaged **1.283 seconds per image throughput**, versus **2.817 seconds serial** before these changes. A longer 24-job run averaged 1.443 seconds/image and remained stable at about 1.3 GiB PSS. Each benchmark changes one corner pixel to defeat active duplicate-job coalescing; this represents fresh OCR/inpainting jobs with cached translation text, not entirely unseen dialogue. Earlier `serial-before-pipeline.json` and `overlap-before-pipeline.json` accidentally coalesced duplicate jobs and must not be used as throughput evidence; their `unique-*` replacements assert distinct job IDs.

With the user's original `inpaint_mode=none`, 12 distinct jobs averaged **0.981 seconds/image throughput**. Small sample repeat-page latency was 0.935 seconds (1.jpg) and 0.766 seconds (2.jpg); first translations were 1.961 and 1.414 seconds. The first Raw page after restart took 9.497 seconds, then 2.481 and 2.140 seconds with NPU inpainting. Fresh network/translation latency is variable and the one-second target is not guaranteed end-to-end latency for unseen pages.

Shared-memory allocation passed fidelity but did not improve native inference (~0.250 seconds); it was removed. The original fast-preparation contexts are preserved under `models/anime-npu-opt1`. Current evidence filenames begin `optimized3-`, `unique-`, and `fresh-page-`. The 0.4 APK SHA-256 is `21247a1ea4d36b75e968245f09c836e26ab34c0d023c051c1924a8c09bbb3fbd`; extension SHA-256 is `1ae91080afc8f275c57798852656a188436f95ce99e0b88c601398a45501c34a`. Both Downloads copies match.

## Further lossless encoding optimization

The latest installed build defaults PNG compression to level 1 through Pillow's registered PNG encoder. Explicit compression/optimization options remain respected. This changes encoded size, not decoded pixels, and leaves the original renderer and all sizing methods unchanged. The sample output grows from about 774 KB to 935 KB over localhost. Warm async renders now wait up to 0.5 seconds for completion before returning 202, avoiding extra polling when rendering finishes promptly; cold rendering still follows the existing retry path.

Before this change the seven-region sample without inpainting took 1.38–1.43 seconds warm, including 0.42–0.45 seconds rendering. Afterward warm measurements ranged 1.04–1.40 seconds, including 0.25–0.29 seconds rendering. With inpainting enabled, seven warm pages took 2.44–2.68 seconds (first cold page 3.92 seconds), without a crash. Network timings vary, and these samples do not establish a universal device maximum. All 21 Python checks passed, including lossless encoding, explicit option handling, render retry/error handling, and exact upstream rendering source checks. The original inpainting setting was restored to `none` afterward.

The installed APK and Downloads copy SHA-256 is `193cf04628c03358a6039b36cc5bba9caec50fafee33bafd3fdb2b37e570621a`. Version remains 0.3; no extension update is required for this server-side improvement. Earlier benchmark files and `final-validation.json` describe the prior build; current evidence is `before-png.json`, `fast-png.json`, `final-fast-png.json`, and `final-png-inpaint.json`.

The installed 0.3 build reuses the 27 compiled NPU sessions and their native output tensors. QNN profiling verifies each session once, then its temporary profile is deleted. Raw ONNX compilation is not retained in this cache. Local neural inference still forbids CPU fallback.

Samsung translates a page's uncached regions in one request when they fit its 4,000-character limit. Exact numbered paragraph identifiers must survive in order, and every result must pass target-language validation; otherwise the original individual-region path is used. The hidden display is reused within that page and released in `finally`. A 540×960 display at density 160 preserves the previous logical UI dimensions while rendering one quarter as many pixels.

Samsung's installed TranslationActivity requires **both** `source_language_code=auto` and `target_language_code=en`. `en-US` selects its speech-language variant and does not work with this text translator. Samsung-detected English returns unchanged, avoiding the previous 25-second wait and preventing target-language drift on the following page. This is an unofficial integration; Samsung's internal NPU use remains unverified.

Completed delivered jobs retain at most eight recent pages and approximately 128 MB of decoded image history (one larger page may remain). Terminal jobs older than 120 seconds are removed when another job is submitted. Active processing and rendering jobs are preserved. This prevents the former unbounded chapter-image history.

## Measurements

`benchmark_speed.py` measures upload, OCR/translation, and rendering through the phone HTTP server. These are the same 1010×1450 Japanese page, seven translation regions, Google Lens OCR and Samsung translation. Network timing varies.

| Check | Before | Optimized |
|---|---:|---:|
| Japanese page, first translation, no inpainting | 7.49 s | 3.89 s |
| Japanese page, cached translations, no inpainting | 1.48 s | 1.38 s |
| Samsung translation of seven uncached regions | ~5.0 s across seven calls | 0.77 s in one page batch |
| Japanese page, cached translations, inpainting enabled | 9.19 s | 2.71–2.72 s |
| Japanese page, first translation and first inpainting | not captured together | 5.07 s |
| Already-English sentence | 25.18 s, then failure | 0.63–0.95 s, unchanged text |
| Already-English page | not captured | 2.44 s, pixel-identical output |
| Uniform blank page | 0.29 s | 0.26 s |
| NPU inpainting reference, warm | repeated graph loading was the dominant cost | 0.247–0.248 s |

The full server measured approximately 745 MB PSS with OCR and warm inpainting sessions loaded. Inpainting alone measured approximately 300–333 MB. All 27 stages passed the original reduced-resolution reference comparison: mean absolute error 0.000166617, maximum 0.00674385. No CPU provider events were observed.

A single combined graph failed QNN finalization (1002). A 15-stage grouped candidate passed fidelity but ran slower, approximately 0.40 seconds warm. The faster 27-stage model is retained. Evidence is under `android/evidence/speed/`.

The final 12-page repeated inpainting check completed without a crash. Times ranged from 2.57 to 3.63 seconds, including its first model load; the complete server measured approximately 763 MiB PSS afterward. The user's original `inpaint_mode=none` setting was restored after testing. Version 0.3 is installed and the server is running. The APK and extension ZIP in Downloads were verified against the workspace SHA-256 hashes.

## Exact original text sizing

The APK's embedded `app.py` is byte-identical to Kirogii/MangaAMTL commit `a3da2588068f20c744d796ecdf79add1a09299e1`, SHA-256 `d6954a25a9bd0a1ffbe3504511476ee7e67e808d4a0aa06e2227d46fa0ded746`. `test_upstream_rendering.py` pins the exact sizing, wrapping, font lookup, color detection and render caller source. The Android adapter does not replace those methods. Selected fonts and OCR geometry still determine the resulting layout.

Extension 3.0.3 uploads validated PNG/JPEG bytes directly, keeps PNG conversion for other formats, and polls job/render state every 100 ms. Its ZIP is in the phone's Downloads. Reload/install that extension and reload the manga tab to apply its changes; updating the APK does not update a browser extension.


## Live and manga optimization � 2026-10-16

Automated saved-image benchmarks on the connected S25 Ultra use the same Japanese page, selected Samsung translation, Google Lens OCR, and Blur. Six warm paired iterations alternate pipeline order. These measure HTTP upload through decoded overlay/page response; they exclude screen capture and first model initialization.

| Workload | Live median | Manga median |
|---|---:|---:|
| Exact original file repeated | 0.155 s | 0.227 s |
| Changed pixels, fresh OCR, translations already cached | 1.037 s | 1.031 s |

Fresh unseen text also requires translation: a separate one-region uncached request took 1.606 s, including 0.891 s OCR and 0.630 s Samsung. Cloud Lens latency prevents a dependable 0.20-second fresh-text pipeline. Cached results meet that target for live responses; these figures do not claim equivalent live user-app latency.

Native synthetic ImageReader checks require no tapping or capture consent. Hoisting image dimensions/strides out of pixel loops and bulk reading the capture plane reduced grayscale preparation from approximately 323 ms to 2.5 ms. Full 738�1600 crop preparation took 18.6 ms; 738�300 took 3.7 ms. PNG encoding remains approximately 204/36 ms respectively. Platform lossless WebP was faster but the bundled Pillow cannot decode it, so PNG is retained. Native tracking measured 13.8 ms.

Overlay reconstruction now composites overlapping patches before reversing window opacity, and reads only the last drawn overlay state. Synthetic reconstruction errors were at most 2 grayscale levels / 4 RGB levels; ten stationary frames caused no repeated OCR. Native checks passed partial clipping, fixed bottom bars, and offscreen restoration without OCR. Actual app scrolling was not manually tested.

Exact RGB OCR caches are bounded to 32 entries and 8 MB serialized results; they retain no source images and exclude empty failures. Packed crop cache hits still remap coordinates. Live caching disabled bypasses and clears these caches. Translation keys retain complete ordered context, language, and engine; whitespace is canonicalized and spatial order prevents confidence-order changes from retriggering translation. Completed font layouts retain at most 256 immutable entries; deterministic manga PNG results retain at most eight entries / 16 MB and invalidate on translation or rendering settings changes.

Live requests can return only region patches. Transparent backgrounds no longer encode hidden full-screen RGB, reducing the reference background payload from 1.81 MB to 161 KB. The original renderer and Blur method remain preserved.

Validation: 43 focused Python tests, Android build/lint, and native capture/composition/tracking checks passed. Evidence: `final-repeat-original-file.json`, `final-fresh-stable-context.json`, and `single-region-plain-samsung.json` under the local ignored `android/evidence/speed/` directory. Benchmark runner: `android/benchmark_live_vs_manga.py`.


Live follow-up: geometry changes now invalidate stale overlays and pending OCR. Unique exact strip matches correct repeated-line optical-flow aliasing; destination clipping preserves partial text at large scroll steps. Native checks pass 15/40/80/120-pixel repeated-line scrolls. Translation now overlaps Blur/color preparation using existing separate executors, verified by a synchronization test. Phone saved-image checks passed: cold Blur 3.042 s, cached Blur 0.148 s, uncached None 1.431 s. These are not a controlled before/after comparison. Broader real-layout validation remains ongoing.

Delayed OCR follow-up: pending cells and coverage now use the same unique strip motion refinement as visible overlays. Matching can inspect neighboring rows when a section is blank but text crosses its boundary. Pending change detection respects the visible panel clip, avoiding false invalidation behind a fixed header. Phone instrumentation passes delayed OCR at 15/40/80/120 pixels per frame, with less than 2 pixels position error. Stable tracking measured 13.98 ms.

Selective-label follow-up: connected glyph changes now invalidate sparse changed words inside padded OCR boxes without invalidating unrelated overlays or isolated reconstruction speckles. Pixel comparison compensates residual fractional motion before testing change. Host and native checks passed Account-to-Settings replacement and 0.25/0.5/1.5/2.5-pixel scrolls, with less than 0.5-pixel position error. Stable native tracking measured 13.93 ms; compositor checks still pass with no stationary repeat OCR.

Real manga replay: six reference text boxes on Images/Raw.png, resized to tracking resolution with fixed header/footer and unique tail content, now pass scrolling 10/30/60/90/130/180/240 pixels away and back within 2 pixels of expected coordinates. This exposed overly narrow inferred panel clipping, skipped motion refinement on narrow/zero-flow regions, and restoration waiting for full anchor tiles. Bounds now follow full pixel comparisons, narrow regions can recover motion even when optical flow fails, and visible returning text is independently verified before restoration. Host split-panel tests also pass opposing independent motion. Native real manga replay and composition checks pass; stable tracking 14.17 ms.

Overlay cadence follow-up: exact unchanged tracking frames skip optical flow, historical feature restoration, and repeated change comparisons while preserving untranslated dirty work. Native stable tracking dropped from 14.17 ms to 0.54 ms. A 32-frame motion/reversal benchmark measured 30.57 ms/frame. Capture throttle is now 40 ms (maximum 25 Hz), up from 80 ms (12.5 Hz), leaving margin for approximately 2.5 ms grayscale preparation. This is a configured maximum, not measured end-to-end presentation FPS. Full native tracking invariants passed; 50 host tests and Android build/lint passed.

Profile-guided motion follow-up: full strip searches accounted for 0.168 s of a 16-frame profile. Precise motion now verifies the integer pixel position predicted by optical flow first (maximum pixel difference 8); verified matches use pixel-aligned offsets, avoiding fractional coverage accumulation. Mismatches retain the full unique-strip search. A candidate history-offset shortcut was measured and removed. Native moving tracking is now 21.56 ms/frame, compared with 30.80 ms before, while stationary tracking is 0.535 ms. Capture throttle is now 33.33 ms, maximum 30 Hz; actual screen presentation FPS remains unmeasured. All native scrolling and reconstruction checks, 50 host tests, and build/lint passed.

Horizontal clipping follow-up: fixed sidebars previously caused partially visible sideways-scrolled text to be removed. Dominant horizontal motion now reuses vertical boundary detection by transposing axes. Host and native tests verify the old region moves from x=22 to x=2 while clipping at x=20. All prior native tracking invariants passed, moving tracking 21.44 ms, stationary 0.55 ms. Android build/lint and 51 host tests passed.

Cross-section delayed-result follow-up: pending OCR keeps one bounded tracking-resolution source frame. Before accepting a result, the complete visible text box is compared with its captured pixels at the tracked displacement, compensating fractional motion and applying the current panel clip. This rejects boxes whose center cell survived but whose other visible section changed. Rejected boxes invalidate all intersected coverage cells so the complete sentence is rescanned. Host tests preserve valid delayed fractional/fast-scroll results. Native cross-section rejection and all prior scrolling checks passed; moving tracking 21.71 ms and stationary 0.536 ms. Build/lint and 52 host tests passed.

Long-session replay: native 320-frame back-and-forth scrolling with fixed bars passed, maximum position error below 0.001 pixels, peak coverage 24 regions, and cycle means 21.65-21.87 ms/frame. No growing coverage state or slowdown was observed in this replay. The host 19-test tracking suite and Android build/lint passed. Evidence: local ignored scroll-soak-320.json. This is synthetic tracking evidence, not actual app presentation FPS or an unlimited-session guarantee.

Capture lifecycle follow-up: resize now invalidates pending work, disconnects active HTTP requests, resets OCR readiness/retry delay, and recycles old overlay bitmaps. Callbacks from obsolete generations no longer clear the new generation busy flag; sending checks capture generation after assigning its active connection. Native invalidation checks verify cancellation/readiness reset, composition checks pass, and the 320-frame tracking replay remains bounded with no drift. Build/lint passed. Actual MediaProjection rotation remains unverified end to end.

Controlled end-to-end replay harness: debug-only LiveReplayActivity displays three copies of the project sample with fixed header/footer and accepts scroll_y/smooth commands. It can request ordinary Android MediaProjection consent and keeps the sample activity visible. Build/lint passed for the initial harness and it was installed/launched. Full capture was not approved: automatic review rejected consent automation pending explicit authorization for full-screen capture and Google Lens egress. The prompt was dismissed and dumpsys media_projection confirmed null. No MediaProjection session or sample upload was started.

Native overlay drawing proof: LiveCompositionChecks now invokes the actual Overlay.onDraw with partial top/bottom/left/right bounds and independent clip rectangles, checking all interior/exterior Canvas pixels. All four cases passed on the phone, alongside reconstruction/invalidation checks. This uses synthetic Canvas images without MediaProjection or upload; dumpsys confirmed capture null. End-to-end capture authorization remains pending. Build/lint passed.

Stationary flicker fix: a single inconsistent reconstructed frame previously removed a visible overlay and the following good frame restored it. Stationary text changes now require three observations against the last validated source rather than consecutive-frame differences. Shared source snapshots exist only during confirmation; good frames clear suspicion. Broad scrolling motion and offscreen clipping retain immediate tracking/removal. Confirmed changes invalidate their OCR coverage so replacement text is requested. Native replay passed eight repeated transient bad-frame cycles with no removal/re-add, persistent menu changes, all previous tracking cases and the 320-frame soak. Moving tracking 21.59 ms; 55 host tests and build/lint passed. This reproduces and fixes transient-frame flicker; actual live app capture remains unverified pending authorization.

Live background preference update: None is now the default in the API and Android live controls; it performs no inpainting and draws a white textbox with alpha 51/255 (80 percent transparent), leaving translated text opaque before the existing touch-through window alpha. Existing Blur preferences are switched to None once on MainActivity launch; users can enable Blur afterward. Focused live tests and build/lint passed. Installation could not run because the phone was absent from ADB.
