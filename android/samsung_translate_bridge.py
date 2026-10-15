"""USB proof of Samsung Interpreter translation via its exported text action.

shortcut: requires ADB and a visible unlocked phone, use an accessibility service
for a standalone APK implementation after validating batch behavior.
"""
import argparse
import json
import shlex
import subprocess
import time
import xml.etree.ElementTree as ET

PACKAGE = "com.samsung.android.app.interpreter"


def translate(adb, serial, source):
    if not source.strip() or len(source) > 4000:
        raise ValueError("Text must contain 1–4000 characters")

    def shell(*args):
        return subprocess.run(
            [adb, "-s", serial, "shell", shlex.join(args)],
            capture_output=True, check=True, timeout=15,
        ).stdout.decode("utf-8", errors="replace")

    result = shell("am", "start", "-a", "android.intent.action.PROCESS_TEXT",
                   "-t", "text/plain", "-n", PACKAGE + "/.translation.view.TranslationActivity",
                   "--es", "android.intent.extra.PROCESS_TEXT", source,
                   "--ez", "android.intent.extra.PROCESS_TEXT_READONLY", "true")
    if "Error:" in result or "Exception" in result:
        raise RuntimeError(result)
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        shell("uiautomator", "dump", "/sdcard/manga-translation-probe.xml")
        root = ET.fromstring(shell("cat", "/sdcard/manga-translation-probe.xml"))
        for parent in root.iter("node"):
            nodes = list(parent)
            for index, node in enumerate(nodes):
                if node.get("package") == PACKAGE and node.get("text") == source:
                    # Samsung renders source, target language, translated text in order.
                    following = nodes[index + 1:]
                    if len(following) >= 2 and following[0].get("text") == "English":
                        text = following[1].get("text", "").strip()
                        if text and text != source:
                            return text
        time.sleep(0.5)
    raise TimeoutError("No English translation found; check Samsung's language selectors")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("text")
    parser.add_argument("--adb", default="adb")
    parser.add_argument("--serial", required=True)
    args = parser.parse_args()
    print(json.dumps({"translation": translate(args.adb, args.serial, args.text)}, ensure_ascii=False))
