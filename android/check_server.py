"""Exercise the unmodified extension's HTTP workflow against the phone server."""
import argparse
import json
from pathlib import Path
import time

import requests
from PIL import Image
import io
import re


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:17860")
    parser.add_argument("--image", type=Path, default=Path(__file__).parent.parent / "Images/Raw.png")
    parser.add_argument("--language", default="ja")
    parser.add_argument("--target", default="en")
    parser.add_argument("--ocr-mode", choices=["hayai", "glm", "lens"], default="hayai")
    parser.add_argument("--timeout", type=int, default=600)
    args = parser.parse_args()
    assert 1 <= args.timeout <= 900
    base = args.url.rstrip("/")
    client = requests.Session()
    client.trust_env = False
    def request(method, path, **kwargs):
        response = client.request(method, base + path, timeout=kwargs.pop("timeout", 30), **kwargs)
        response.raise_for_status()
        return response
    assert request("GET", "/health").json()["status"] == "ok"
    metadata = request("GET", "/meta").json()
    model = request("GET", "/getmodel").json()["local"]["repo_id"]
    assert metadata["device"] == "npu" and metadata["model_type"] == "local"
    fonts = request("GET", "/GetFonts").json()
    request("POST", "/SetAllSettings", json={"cloud_mode": False, "model_type": "local", "ocr_mode": args.ocr_mode, "inpaint_mode": "high", "stroke_width": 0})
    cors = request("OPTIONS", "/v1/translate", headers={"Origin": "chrome-extension://manga-test", "Access-Control-Request-Method": "POST"})
    assert cors.headers.get("Access-Control-Allow-Origin") == "chrome-extension://manga-test"
    rejected = client.post(base + "/SetModelType", json={"model_type": "openrouter"}, timeout=10)
    assert rejected.status_code == 400
    with args.image.open("rb") as image:
        submitted = request("POST", "/v1/translate", files={"image": (args.image.name, image, "image/png")},
                            data={"target_lang": args.target, "ocr_lang": args.language, "inpaint": "true"}).json()
    job = submitted["job_id"]
    deadline = time.monotonic() + args.timeout
    previous = None
    while time.monotonic() < deadline:
        request("POST", "/v1/health", json={"job_id": job, "active": True})
        report = request("GET", "/v1/translate/" + job).json()
        if report["status"] != previous:
            print("Job:", report["status"], flush=True)
            previous = report["status"]
        assert report["status"] not in {"failed", "cancelled"}, report
        if report["status"] == "completed":
            break
        time.sleep(2)
    else:
        raise TimeoutError("Phone translation timed out")
    translations = report["result"]["translations"]
    assert translations and any(item["translation"].strip() for item in translations), report
    png = request("POST", "/v1/translate/" + job + "/image", timeout=args.timeout).content
    original = Image.open(args.image).convert("RGB")
    output = Image.open(io.BytesIO(png)).convert("RGB")
    assert original.size == output.size and original.tobytes() != output.tobytes()
    evidence = Path(__file__).parent / "evidence"
    evidence.mkdir(exist_ok=True)
    stem = re.sub(r'[^a-zA-Z0-9_.-]', '_', model) + "-" + args.ocr_mode + "-" + args.language + "-" + args.image.stem
    (evidence / (stem + "-translated.png")).write_bytes(png)
    (evidence / (stem + "-server.json")).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"passed": True, "regions": len(translations), "result": str(evidence / (stem + "-translated.png"))}, indent=2))


if __name__ == "__main__":
    main()
