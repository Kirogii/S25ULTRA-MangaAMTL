"""Run the original FastAPI app with Android NPU model adapters."""
import ast
import asyncio
import io
import json
import logging
import pathlib
import socket
import types
import time

import cv2
import numpy as np
from PIL import Image
import uvicorn

servers = []


def load_app(root, bridge):
    root = pathlib.Path(root)
    source = (root / "app.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    import android_lens
    android_lens.offload_detector(tree)
    # PyTorch cannot run on Android's HTP; all learned operators go through Java/QNN.
    tree.body = [node for node in tree.body if not (
        isinstance(node, ast.Import) and any(alias.name == "torch" for alias in node.names))]
    module = types.ModuleType("manga_android")
    module.__file__ = str(root / "app.py")
    import sys
    sys.modules[module.__name__] = module
    exec(compile(tree, module.__file__, "exec"), module.__dict__)

    def infer(name, image, mask=None):
        image = np.ascontiguousarray(image, dtype="<f4")
        masking = None if mask is None else np.ascontiguousarray(mask, dtype="<f4").tobytes()
        output = bridge.run(name, image.tobytes(), list(image.shape), masking)
        return np.frombuffer(bytes(output), dtype="<f4").copy()

    class Qwen:
        def create_chat_completion(self, messages, max_tokens=256, temperature=0.2, top_p=0.9, **kwargs):
            text = str(bridge.chat(json.dumps(messages, ensure_ascii=False), max_tokens, temperature, top_p))
            return {"choices": [{"message": {"content": text}}]}

    qwen = Qwen()

    class Lama(module.HighQualityLama):
        def __init__(self):
            self.patch_size, self.stride, self.batch_size = 512, 384, 1

        def _infer_batch(self, images, masks):
            output = []
            for image, mask in zip(images, masks):
                image = image.transpose(2, 0, 1)[None].astype(np.float32) / 255
                mask = (mask[None, None] > 127).astype(np.float32)
                painted = infer(str(bridge.inpaintModel()), image, mask).reshape(3, 512, 512)
                output.append(painted.transpose(1, 2, 0).clip(0, 1) * 255)
            return np.stack(output)

    lama = Lama()

    async def inpaint(image, mask, use_lama=True):
        if module._inpaint_mode == "none":
            return image
        # Retain the original crop, tiling, color correction and blending methods.
        def run():
            result = lama(module.cv2_to_pil(image), Image.fromarray(mask))
            return module.pil_to_cv2(result)
        return await asyncio.get_running_loop().run_in_executor(module._inpaint_executor, run)

    def text_columns(page):
        image = np.asarray(page.convert("RGB"))
        height, width = image.shape[:2]
        tile_height = max(128, min(height, round(width * 608 / 800)))
        step = max(1, tile_height - 64)
        starts = list(range(0, max(1, height - tile_height + 1), step))
        if starts[-1] != height - tile_height:
            starts.append(height - tile_height)
        boxes = []
        for start in starts:
            tile = image[start:start + tile_height]
            scale = min(800 / width, 608 / tile_height)
            tw, th = max(1, round(width * scale)), max(1, round(tile_height * scale))
            px, py = (800 - tw) // 2, (608 - th) // 2
            canvas = np.zeros((608, 800, 3), np.uint8)
            canvas[py:py + th, px:px + tw] = cv2.resize(tile, (tw, th))
            scores = infer("ocr_detector.onnx", canvas.transpose(2, 0, 1)[None] / 255).reshape(304, 400, 2)
            binary = (scores.max(axis=2) >= .4).astype(np.uint8)
            count, labels, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)
            for i in range(1, count):
                x, y, w, h, area = stats[i]
                if area < 10 or scores[:, :, 0][labels == i].max() < .7:
                    continue
                box = [max(0, int((x * 2 - px - 2) / scale)),
                       max(0, int((y * 2 - py - 2) / scale) + start),
                       min(width, int(((x + w) * 2 - px + 2) / scale)),
                       min(height, int(((y + h) * 2 - py + 2) / scale) + start)]
                if min(box[2] - box[0], box[3] - box[1]) > 3:
                    boxes.append(box)
        # Join overlaps and the vertically broken fragments of a CJK column.
        changed = True
        while changed:
            changed = False
            for i, a in enumerate(boxes):
                for j in range(i + 1, len(boxes)):
                    b = boxes[j]
                    narrow = min(a[2] - a[0], b[2] - b[0])
                    overlap_x = min(a[2], b[2]) - max(a[0], b[0])
                    gap_y = max(a[1], b[1]) - min(a[3], b[3])
                    if module._bbox_iou(a, b) > .3 or (overlap_x > narrow * .65 and gap_y < narrow * .8):
                        boxes[i] = [min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])]
                        del boxes[j]
                        changed = True
                        break
                if changed:
                    break
        return sorted(boxes, key=lambda box: (box[1], -box[2]))

    def detector(page):
        image = np.asarray(page.convert("RGB"))
        height, width = image.shape[:2]
        scale = min(640 / width, 640 / height)
        tw, th = max(1, round(width * scale)), max(1, round(height * scale))
        px, py = (640 - tw) // 2, (640 - th) // 2
        padded = np.full((640, 640, 3), 114, np.uint8)
        padded[py:py+th, px:px+tw] = cv2.resize(image, (tw, th))
        predictions = infer("detector.onnx", padded.transpose(2, 0, 1)[None] / 255).reshape(5, 8400).T
        predictions = predictions[predictions[:, 4] >= .4]
        predictions = predictions[np.argsort(-predictions[:, 4])]
        boxes = []
        for x, y, w, h, confidence in predictions:
            box = [max(0, int((x-w/2-px)/scale)), max(0, int((y-h/2-py)/scale)),
                   min(width, int((x+w/2-px)/scale)), min(height, int((y+h/2-py)/scale))]
            if any(module._bbox_iou(box, previous) > .7 for previous in boxes):
                continue
            area = (box[2]-box[0]) * (box[3]-box[1])
            if 100 <= area <= .8 * width * height:
                boxes.append(box)
            if len(boxes) >= 300:
                break
        return boxes

    alphabets = {}

    def ink_spans(projection):
        positions = np.flatnonzero(projection)
        if not len(positions):
            return []
        groups = np.split(positions, np.where(np.diff(positions) > 3)[0] + 1)
        return [(int(group[0]), int(group[-1]) + 1) for group in groups]

    def recognize(page, box, language):
        crop = np.asarray(page.crop(box).convert("L"))
        h, w = crop.shape
        if language in {"ja", "zh"} and h > w * 1.8:
            # EasyOCR reads horizontal lines: preserve upright glyphs and CJK column order.
            # shortcut: short vertical lines can be missegmented; use Lens or a vertical OCR model for better accuracy.
            ink = crop < 160 if np.median(crop) > 127 else crop > 160
            columns = ink_spans(ink.sum(axis=0) > max(1, h * .01))
            if len(columns) > 1:
                return ''.join(recognize(page, [box[0]+left, box[1], box[0]+right, box[3]], language)
                               for left, right in reversed(columns))
            rows = np.flatnonzero(ink.any(axis=1))
            if len(rows) and columns:
                left, right = columns[0]
                crop = crop[rows[0]:rows[-1]+1, left:right]
                h, w = crop.shape
                signal = ink[rows[0]:rows[-1]+1, left:right].sum(axis=1).astype(float)
                signal -= signal.mean()
                low, high = max(4, round(w*.8)), min(h-1, round(w*1.8))
                correlation = np.correlate(signal, signal, mode='full')[h-1:]
                pitch = low + int(np.argmax(correlation[low:high+1] / np.arange(h-low, h-high-1, -1))) if high >= low else h
                count = max(1, round(h / pitch))
                side = max(w, (h+count-1)//count)
                background = 255 if np.median(crop) > 127 else 0
                cells = []
                for i in range(count):
                    top, bottom = h*i//count, h*(i+1)//count
                    cell = np.full((side+4, side+4), background, np.uint8)
                    y, x = (side+4-bottom+top)//2, (side+4-w)//2
                    cell[y:y+bottom-top, x:x+w] = crop[top:bottom]
                    cells.append(cell)
                crop = np.concatenate(cells, axis=1)
        h, w = crop.shape
        scaled_width = max(1, min(640, round(w * 64 / h)))
        input_image = np.full((64, 640), 255, np.uint8)
        input_image[:, :scaled_width] = cv2.resize(crop, (scaled_width, 64))
        # EasyOCR pads with its last image column, rather than unrelated white pixels.
        input_image[:, scaled_width:] = input_image[:, scaled_width - 1:scaled_width]
        if language not in alphabets:
            alphabets[language] = json.loads((root / "models/ocr" / (language + ".json")).read_text(encoding="utf-8"))["characters"]
        chars = alphabets[language]
        prediction = infer("ocr/" + language + ".onnx", input_image[None, None] / 255).reshape(-1, len(chars) + 1).argmax(axis=1)
        text, previous = [], -1
        for label in prediction:
            if label and label != previous:
                text.append(chars[label - 1])
            previous = label
        return "".join(text).strip()

    def ocr(page, language):
        language = {"auto": "ja", "cz": "zh", "id": "en"}.get(language, language)
        if language not in {"ja", "ko", "zh", "ru", "en"}:
            raise ValueError("No bundled NPU OCR model for source language " + language)
        regions = []
        for box in detector(page):
            crop = page.crop(box)
            columns = text_columns(crop)
            if not columns:
                columns = [[0, 0, crop.width, crop.height]]
            vertical = language in {"ja", "zh"} and sum(b[3]-b[1] > b[2]-b[0] for b in columns) > len(columns)/2
            columns.sort(key=(lambda b: (-b[2], b[1])) if vertical else (lambda b: (b[1], b[0])))
            parts = [recognize(crop, column, language) for column in columns]
            text = ("" if vertical else " ").join(part for part in parts if part)
            if text:
                regions.append({"bbox": box, "bboxes": [box], "text": text})
        return regions

    async def get_ocr_results(page, language="ja", mode_override=None):
        started = time.perf_counter()
        # A completely uniform page contains no visible lettering; avoid a cloud round trip.
        if all(low == high for low, high in page.convert("RGB").getextrema()):
            module.logging.info("[Android OCR] Uniform page: no text, %.3fs", time.perf_counter() - started)
            return []
        if (mode_override or module._ocr_mode) == "lens":
            result = await module.google_lens_ocr(page, language)
        else:
            result = await asyncio.get_running_loop().run_in_executor(module._OCR_BOX_EXECUTOR, ocr, page, language)
        module.logging.info("[Android OCR] %s: %d regions, %.3fs", mode_override or module._ocr_mode, len(result), time.perf_counter() - started)
        return result

    module.get_ocr_results = get_ocr_results
    module._detect_yolo_text_boxes = detector
    module.get_qwen = lambda: qwen
    module.get_torch_device = lambda: "npu"
    module.get_yolo = lambda: bridge
    module.get_hayai_ocr = lambda: bridge
    module.load_lama_low = module.load_lama_high = module.load_lama = lambda: lama
    module.ensure_lama_large = lambda: None
    module.inpaint_image_async = inpaint
    module.SimpleLama = Lama
    module._current_qwen_repo_id = "Qualcomm/Qwen3-0.6B"
    module._current_qwen_filename = "Snapdragon-8-Elite-for-Galaxy-w4a16-NPU"
    module._current_qwen_path = root / "models/translation/genie_config.json"
    module.LAMA_LARGE_PATH = root / "models/lama_dilated.onnx"
    module._cloud_mode = False
    module._current_model_type = "local"
    module._inpaint_mode = "none" if module._inpaint_mode == "none" else "high"
    if module._ocr_mode not in {"hayai", "glm", "lens"}:
        module._ocr_mode = "hayai"

    @module.app.middleware("http")
    async def npu_only(request, call_next):
        parts = request.url.path.split("/")
        if request.method == "POST" and request.url.path == "/v1/translate":
            import android_render
            android_render.prune(module)
        if (request.method == "POST" and request.headers.get("prefer") == "respond-async"
                and len(parts) == 5 and parts[1:3] == ["v1", "translate"] and parts[4] == "image"):
            import android_render
            return await android_render.image(module, parts[3])
        if request.method == "GET" and request.url.path == "/GetOcrMode":
            result = await module.get_ocr_mode()
            result.update(available_modes=["hayai", "glm", "lens"], descriptions={
                "hayai": "Local NPU OCR (EasyOCR equivalent + original manga YOLO)",
                "glm": "Local NPU Korean OCR (EasyOCR equivalent + original manga YOLO)",
                "lens": "Original Google Lens OCR (cloud API + NPU manga YOLO)",
            })
            return module.JSONResponse(result)
        if request.url.path == "/v1/colorize":
            return module.JSONResponse({"detail": "Colorization excluded from this Android build"}, status_code=501)
        if request.method == "POST" and request.url.path in {
            "/SetAllSettings", "/SetCloudMode", "/SetModelType", "/setmodel", "/SetOcrMode", "/v1/changemodel"
        }:
            body = await request.body()
            try:
                settings = json.loads(body)
            except (ValueError, TypeError):
                return module.JSONResponse({"detail": "Invalid JSON settings"}, status_code=400)
            unsupported = (settings.get("cloud_mode") or settings.get("enabled") and request.url.path == "/SetCloudMode"
                           or settings.get("model_type", settings.get("type", "local")) != "local"
                           or settings.get("ocr_mode", "hayai") not in {"hayai", "glm", "lens"}
                           or request.url.path == "/SetOcrMode" and settings.get("mode") not in {"hayai", "glm", "lens"})
            if unsupported:
                return module.JSONResponse({"detail": "Select local NPU translation and Hayai, GLM or Google Lens OCR. Find compatible translation models at /models."}, status_code=400)
        response = await call_next(request)
        if request.method == "POST" and len(parts) == 5 and parts[1:3] == ["v1", "translate"] and parts[4] == "image" and response.status_code == 200:
            job = module._jobs.get(parts[3])
            if job is not None: job['android_image_delivered'] = True
        return response

    import model_finder
    module.android_finder = model_finder.install(module, root, bridge)
    import samsung_translation
    samsung_translation.install(module, bridge)
    return module


def serve(root, bridge):
    import android_png
    android_png.install()
    module = load_app(root, bridge)
    async def run():
        import render_fixture
        await render_fixture.check(module, root)
        servers.clear()
        sockets = []
        for port in (8000, 7860):
            listener = socket.socket()
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                listener.bind(("127.0.0.1", port))
            except OSError as error:
                listener.close()
                logging.warning("localhost:%s unavailable: %s", port, error)
                continue
            listener.listen(128)
            listener.setblocking(False)
            sockets.append(listener)
            config = uvicorn.Config(module.app, host="127.0.0.1", port=port, loop="asyncio", http="h11", lifespan="off", log_config=None)
            server = uvicorn.Server(config)
            server.install_signal_handlers = lambda: None
            servers.append(server)
        if not servers:
            raise RuntimeError("Both localhost:8000 and localhost:7860 are already in use")
        ports = [listener.getsockname()[1] for listener in sockets]
        bridge.setServerStatus("Server running · " + ", ".join("localhost:" + str(port) for port in ports)
                               + "\nKeep this service running while using the extension.", 7860 if 7860 in ports else ports[0])
        try:
            await asyncio.gather(*(server.serve(sockets=[listener]) for server, listener in zip(servers, sockets)))
        finally:
            for listener in sockets:
                listener.close()
            module.android_finder.close()
    asyncio.run(run())


def stop():
    for server in servers:
        server.should_exit = True
