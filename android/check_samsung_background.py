"""Device regression: run Samsung requests while scrolling Android Settings."""
import concurrent.futures
import json
from pathlib import Path
import re
import subprocess
import time
import requests

ADB = [r"C:\Users\Admin\AppData\Local\Programs\SideQuest\resources\platform-tools\adb.exe", "-s", "R5CY53N3X1D", "shell"]

def shell(*args):
    return subprocess.check_output(ADB + list(args), timeout=15).decode("utf-8", errors="replace")

def focus():
    return re.search(r"topResumedActivity=([^\r\n]+)", shell("dumpsys", "activity", "activities")).group(1)

def translate(text):
    response = requests.post("http://127.0.0.1:17860/v1/samsung/check", json={"text": text}, timeout=45)
    response.raise_for_status()
    return response.json()["text"]

if __name__ == "__main__":
    shell("am", "start", "-a", "android.settings.SETTINGS")
    before = focus()
    sources = ["自分の手で作りたい", "今日はいい天気ですね。", "自分の手で作りたい"]
    with concurrent.futures.ThreadPoolExecutor(1) as worker:
        future = worker.submit(lambda: [translate(text) for text in sources])
        time.sleep(.3)
        shell("input", "swipe", "720", "2300", "720", "900", "500")
        during = focus()
        results = future.result()
    after = focus()
    assert all(results), results
    assert results[0] == results[2], "Repeated source produced stale or inconsistent output"
    assert all("com.android.settings" in state for state in (before, during, after)), (before, during, after)
    assert "MangaAMTL Samsung" not in shell("dumpsys", "display"), "Hidden display leaked"
    report = dict(sources=sources, results=results, before=before, during_scroll=during, after=after, hidden_display_cleanup=True)
    output = Path(__file__).parent / "evidence/samsung-background-check.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report))
