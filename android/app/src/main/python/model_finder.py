"""A small catalog of Qualcomm NPU bundles compiled for this phone's chipset."""
import concurrent.futures
import json
import os
from pathlib import Path
import shutil
import ssl
import stat
import threading
import urllib.request
import zipfile

import certifi

CATALOG = (
    ("qwen3_0_6b", "Qwen3-0.6B", 0.6, 641191280, "Smallest / lowest expected quality", "Optional download; tested on this phone"),
    ("qwen3_1_7b", "Qwen3-1.7B", 1.7, 1536236016, "Middle / balanced", "NPU page translation tested on S25 Ultra"),
    ("qwen3_4b", "Qwen3-4B", 4.0, 2535436903, "Largest / highest expected quality", "NPU page translation tested on S25 Ultra; recommended"),
)


class Finder:
    def __init__(self, module, root, bridge):
        self.module, self.root, self.bridge = module, Path(root), bridge
        self.states = {}
        self.lock = threading.Lock()
        self.stopping = threading.Event()
        self.worker = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="model-download")
        self.settings = self.root / "android-model.json"
        self.active = "qwen3_0_6b"
        if self.settings.is_file():
            try:
                key = json.loads(self.settings.read_text())["active"]
                if self.directory(key).is_dir():
                    self.bridge.selectModel(str(self.directory(key)))
                    self.active = key
            except Exception as error:
                module.logging.warning("Could not restore NPU model: %s", error)
        module._current_qwen_repo_id = "Qualcomm/" + self.record(self.active)[1]
        module._current_qwen_filename = "genie_config.json"
        module._current_qwen_path = self.directory(self.active) / "genie_config.json"

    def record(self, key):
        for row in CATALOG:
            if row[0] == key:
                return row
        raise ValueError("Model is not in the S25 Ultra NPU catalog")

    def directory(self, key):
        self.record(key)
        return self.root / ("models/translation" if key == "qwen3_0_6b" else "models/downloaded/" + key)

    def listing(self):
        with self.lock:
            states = {key: dict(value) for key, value in self.states.items()}
        return [{"id": key, "repo_id": "Qualcomm/" + name, "filename": "genie_config.json", "name": name,
                 "parameters_billion": size, "rank": rank + 1, "quality": quality, "verification": verification,
                 "download_bytes": download_bytes, "size_mb": round(download_bytes / 1e6) if download_bytes else 750,
                 "downloaded": (self.directory(key) / 'genie_config.json').is_file(), "active": self.active == key and (self.directory(key) / 'genie_config.json').is_file(), "vision_capable": False,
                 "runtime": "QAIRT / QnnHtp / NPU", "download": states.get(key, {"status": "idle"})}
                for rank, (key, name, size, download_bytes, quality, verification) in enumerate(CATALOG)]

    def state(self, key, **values):
        with self.lock:
            self.states.setdefault(key, {}).update(values)

    def download(self, key):
        self.record(key)
        if self.directory(key).is_dir():
            return {"status": "downloaded"}
        with self.lock:
            if self.states.get(key, {}).get("status") in {"queued", "downloading", "extracting"}:
                return dict(self.states[key])
            self.states[key] = {"status": "queued", "bytes": 0}
        self.worker.submit(self._download, key)
        return {"status": "queued"}

    def _download(self, key):
        dest = self.directory(key)
        temporary = dest.with_name(key + ".partial")
        archive = dest.with_name(key + ".zip.partial")
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            total = self.record(key)[3]
            if shutil.disk_usage(dest.parent).free < total * 3 + 512_000_000:
                raise OSError("Free at least " + str(round((total * 3 + 512_000_000) / 1e9, 1)) + " GB before downloading this model")
            url = ("https://qaihub-public-assets.s3.us-west-2.amazonaws.com/qai-hub-models/models/" + key
                   + "/releases/v0.64.0/" + key + "-genie-w4a16-qualcomm_snapdragon_8_elite_for_galaxy.zip")
            count = 0
            self.state(key, status="downloading", total=total, error=None)
            with urllib.request.urlopen(url, timeout=60, context=ssl.create_default_context(cafile=certifi.where())) as response, archive.open("wb") as output:
                if int(response.headers.get("Content-Length", total)) != total:
                    raise ValueError("Unexpected model archive size")
                while True:
                    if self.stopping.is_set():
                        raise InterruptedError("Server stopped; retry the model download")
                    data = response.read(1024 * 1024)
                    if not data:
                        break
                    count += len(data)
                    if count > total:
                        raise ValueError("Model download exceeded its expected size")
                    output.write(data)
                    self.state(key, bytes=count)
                output.flush()
                os.fsync(output.fileno())
            if count != total:
                raise ValueError("Incomplete model download; retry")
            self.state(key, status="extracting")
            temporary.mkdir(exist_ok=True)
            with zipfile.ZipFile(archive) as bundle:
                if len(bundle.infolist()) > 128 or sum(item.file_size for item in bundle.infolist()) > 6_000_000_000:
                    raise ValueError("Unexpected model archive contents")
                for item in bundle.infolist():
                    target = (temporary / item.filename).resolve()
                    if not target.is_relative_to(temporary.resolve()) or stat.S_ISLNK(item.external_attr >> 16):
                        raise ValueError("Unsafe model archive path")
                    if not item.is_dir() and target.suffix.lower() not in {".json", ".bin", ".txt"}:
                        raise ValueError("Unexpected model archive file")
                bundle.extractall(temporary)
            configs = list(temporary.rglob("genie_config.json"))
            if len(configs) != 1:
                raise ValueError("Model archive must contain one Genie configuration")
            directory = configs[0].parent
            config = json.loads(configs[0].read_text())
            if config["dialog"]["engine"]["backend"]["type"] != "QnnHtp":
                raise ValueError("Model is not configured for NPU inference")
            for filename in ["tokenizer.json", *config["dialog"]["engine"]["model"]["binary"]["ctx-bins"]]:
                model_file = (directory / filename).resolve()
                if not model_file.is_relative_to(directory.resolve()) or not model_file.is_file() or model_file.stat().st_size == 0:
                    raise ValueError("Missing or unsafe model data")
            directory.rename(dest)
            self.state(key, status="downloaded")
        except Exception as error:
            self.state(key, status="failed", error=str(error))
        finally:
            archive.unlink(missing_ok=True)
            if temporary.exists():
                shutil.rmtree(temporary)

    def close(self):
        self.stopping.set()
        self.worker.shutdown(wait=True, cancel_futures=True)

    def select(self, key):
        directory = self.directory(key)
        if not directory.is_dir():
            raise ValueError("Download the model before selecting it")
        if any(job.get("status") in {"pending", "processing"} or job.get("rendering") for job in self.module._jobs.values()):
            raise ValueError("Wait for the current translation to finish before switching models")
        self.bridge.selectModel(str(directory))
        self.active = key
        temporary = self.settings.with_suffix(".tmp")
        temporary.write_text(json.dumps({"active": key}), encoding="utf-8")
        temporary.replace(self.settings)
        self.module._current_qwen_repo_id = "Qualcomm/" + self.record(key)[1]
        self.module._current_qwen_filename = "genie_config.json"
        self.module._current_qwen_path = directory / "genie_config.json"
        return {"status": "ok", "repo_id": "Qualcomm/" + self.record(key)[1], "filename": "genie_config.json", "model_type": "local"}


def install(module, root, bridge):
    finder = Finder(module, root, bridge)
    # Keep the extension's existing model-list and switch endpoints.
    module.list_local_gguf_models = finder.listing
    def switch(repo_id, filename=None):
        for row in CATALOG:
            if repo_id in {row[0], row[1], "Qualcomm/" + row[1]}:
                return finder.select(row[0])
        raise ValueError("Open /models to find and download compatible S25 Ultra NPU models")
    module.switch_qwen_model = switch

    @module.app.get("/models")
    async def page():
        return module.HTMLResponse(PAGE)

    @module.app.post("/v1/models/{key}/download")
    async def download(key: str):
        try:
            return finder.download(key)
        except ValueError as error:
            raise module.HTTPException(400, str(error))

    @module.app.post("/v1/models/{key}/select")
    async def select(key: str):
        try:
            async with module._job_lock:
                return await module.asyncio.get_running_loop().run_in_executor(module._llm_executor, finder.select, key)
        except Exception as error:
            raise module.HTTPException(400, str(error))
    return finder


PAGE = """<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>MangaAMTL model finder</title><style>
body{font:17px system-ui;margin:24px auto;padding:0 20px;max-width:800px;background:#f4f6f8;color:#18202b}h1{font-size:28px}input,button,select{font:inherit;padding:12px;border:1px solid #64748b;border-radius:8px}input{width:100%;box-sizing:border-box}article{background:white;padding:20px;margin:18px 0;border-radius:12px}button{cursor:pointer;margin-right:10px;background:#e5eefc}button:disabled{opacity:.6}p{line-height:1.5}progress{width:100%}#status{white-space:pre-wrap}small{display:block;margin:12px 0;color:#475569}</style>
<h1>S25 Ultra NPU model finder</h1><p>Smaller → larger, from lowest to highest expected translation quality. This order reflects model size, not a manga accuracy benchmark. All use Qualcomm NPU inference; larger models use more storage and memory.</p>
<label for="filter">Find a model</label><input id="filter" type="search" placeholder="Search name, size or quality"><p id="status" role="status" aria-live="polite"></p><div id="models"></div>
<h2>OCR and inpainting</h2><p>Install optional OCR or manga-inpainting ZIP packs using the Android app's install buttons. Packs generated for this build are in the phone's Downloads. Builds can bundle either component; Qwen translation is an optional download. Samsung translation requires Shizuku and its internal NPU use is unverified.</p><label for="ocr">Recognition method</label> <select id="ocr"><option value="hayai">Local NPU OCR</option><option value="glm">Local NPU OCR — Korean</option><option value="lens">Google Lens — cloud OCR</option></select> <button id="apply">Apply OCR</button><p>Google Lens sends the page image to Google. The browser extension can also change this setting.</p><p><a href="/console">Server console</a></p>
<script>
let records=[];const box=document.querySelector('#models'),status=document.querySelector('#status');
async function api(path,body){const r=await fetch(path,body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{});const j=await r.json();if(!r.ok)throw Error(j.detail||'Request failed');return j}
async function act(path){try{status.textContent='Working…';await api(path,{});status.textContent='Done.';await refresh()}catch(e){status.textContent=e.message}}
function render(){box.replaceChildren();const query=document.querySelector('#filter').value.toLowerCase();for(const m of records){if(![m.name,m.parameters_billion,m.quality].join(' ').toLowerCase().includes(query))continue;const card=document.createElement('article'),h=document.createElement('h2'),p=document.createElement('p'),note=document.createElement('small');h.textContent=m.rank+'. '+m.name+(m.active?' · Active':'');p.textContent=m.quality+' · '+(m.download_bytes?(m.download_bytes/1e9).toFixed(2)+' GB download':'Included in APK');note.textContent=m.verification;card.append(h,p,note);const d=m.download;if(['queued','downloading','extracting'].includes(d.status)){const progress=document.createElement('progress');progress.max=d.total||1;progress.value=d.bytes||0;card.append(progress);const t=document.createElement('p');t.textContent=d.status+' '+(d.total?Math.floor(100*(d.bytes||0)/d.total)+'%':'');card.append(t)}if(d.error){const error=document.createElement('p');error.textContent=d.error;card.append(error)}const button=document.createElement('button');button.textContent=m.downloaded?(m.active?'Selected':'Use model'):'Download';button.disabled=m.active||['queued','downloading','extracting'].includes(d.status);button.onclick=()=>act('/v1/models/'+m.id+(m.downloaded?'/select':'/download'));card.append(button);box.append(card)}}
async function refresh(){try{records=(await api('/v1/listmodels')).models;render()}catch(e){status.textContent=e.message}}
document.querySelector('#filter').oninput=render;
document.querySelector('#apply').onclick=async()=>{try{await api('/SetOcrMode',{mode:document.querySelector('#ocr').value});status.textContent='OCR setting saved.'}catch(e){status.textContent=e.message}};
api('/GetOcrMode').then(j=>document.querySelector('#ocr').value=j.ocr_mode);refresh();setInterval(refresh,2500);
</script></html>"""
