# Samsung language pack access check

Tested on the connected Galaxy S25 Ultra (SM-S938U, Android API 36), 2026-10-13. Production MangaAMTL was not modified.

Installed primary-user packs: English–Japanese (`enja`), English–Korean (`enko`), English–Spanish (`enesus`), Korean–Japanese (`koja`), under `com.samsung.android.nmt.apps.t2t.languagepack.*`. The English–Japanese pack is version 2.2.05.2.

The pack's TransformerEngineService requires `com.samsung.sr.nmt.core.t2t.languagepack.permission.USE_NMT_SERVICE`, a signature|privileged permission. An ordinary sideloaded APK cannot obtain that permission merely by requesting it.

Android's public TranslationManager resolves to Samsung's `com.samsung.android.smartsuggestions.extservice.services.CustomTranslationService`. The ordinary-app TranslationProbeActivity in npu-check tested Japanese→English with no Samsung permissions: capabilities were empty, translator creation succeeded, but translating `自分の手で作りたい` returned status 1 (unknown error), no values, and no usable translation. See evidence/samsung-translation-api.json.

Conclusion: the packs exist, but neither direct service access nor the tested public plain-text API provides usable translation to this APK on this firmware. This does not establish that every Samsung partner interface or UI translation path is unavailable. No proprietary model extraction, privileged access, production integration, or NPU execution verification was attempted.

References: https://developer.android.com/reference/android/view/translation/TranslationManager and https://developer.android.com/reference/android/view/translation/TranslationResponse and https://www.samsung.com/sa_en/support/mobile-devices/galaxy-ai-languages-usage-guide/

## Unofficial UI bridge: successful

Samsung Interpreter exposes `android.intent.action.PROCESS_TEXT` (text/plain) on `.translation.view.TranslationActivity`. Launching it with `android.intent.extra.PROCESS_TEXT` displays translated text readable from the UI hierarchy. Actual results:

- `自分の手で作りたい` → `I want to make it with my own hands.`
- `今日はいい天気ですね。` → `It's a beautiful day today, isn't it?`

The initial executable proof is samsung_translate_bridge.py; it requires USB ADB, an unlocked phone, and English selected as target in Interpreter. It validates source matching before returning the adjacent translated result, limits input, and times out on missing output.

The APK now includes an optional Samsung mode using a Shizuku user service and hidden virtual displays. It passed repeated translation, main-screen focus/scrolling, hidden-display cleanup and a full seven-region page test. Shizuku supports phone-only startup through wireless debugging; USB is not a runtime requirement. This session started Shizuku with the user's ADB command because Wi-Fi was disconnected. See README.md and DEVICE_TESTS.md for setup and verification limits. Offline operation, wireless startup and Samsung's NPU delegation were not verified.
