"""A fixed page exercises app.py's sizing, color, stroke, glow and rotated text."""
import hashlib
import io
import json
import pathlib

import cv2
from PIL import Image, ImageDraw


async def check(module, root):
    page = Image.new("RGB", (600, 320), "white")
    draw = ImageDraw.Draw(page)
    draw.rectangle((0, 160, 599, 319), fill=(25, 35, 55))
    font = module.get_current_font(28)
    draw.text((45, 45), "Original lettering", font=font, fill=(20, 30, 40))
    draw.text((50, 210), "Original lettering", font=font, fill=(235, 225, 215))
    entries = [
        {"text": "子供の頃の夢", "translation": "I dreamed of this as a child.", "bbox": [30, 25, 370, 140]},
        {"text": "自分の城", "translation": "At last, my own castle.", "bbox": [30, 185, 370, 300], "angle": 5, "or_bold": 2, "or_glow": True},
    ]
    job = {"image": page, "result": {"translations": entries}, "target_lang": "en",
           "inpaint": False, "ocr_mode": "hayai", "status": "completed"}
    module._jobs["render-fixture"] = job
    cv2.setRNGSeed(42)
    colors = module.detect_text_colors_batch(module.pil_to_cv2(page), [item["bbox"] for item in entries])
    layouts = []
    for item in entries:
        box = item["bbox"]
        layout = module.fit_font_and_wrap(draw, item["translation"], box[2]-box[0], box[3]-box[1],
                font_path=str(module._current_font_path), max_size=680, min_size=10, inner_padding_ratio=0)
        assert " ".join(layout[1]) == item["translation"]
        layouts.append(layout)
    cv2.setRNGSeed(42)
    response = await module._render_translated_image("render-fixture", job)
    rendered = Image.open(io.BytesIO(response.body)).convert("RGB")
    assert rendered.size == page.size and rendered.tobytes() != page.tobytes()
    root = pathlib.Path(root)
    (root / "render-fixture.png").write_bytes(response.body)
    report = {"passed": True, "layouts": layouts, "colors": colors,
              "pixels_sha256": hashlib.sha256(rendered.tobytes()).hexdigest()}
    (root / "render-fixture.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    del module._jobs["render-fixture"]
    return report
