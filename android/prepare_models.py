"""Assemble the offline Android model assets; no colorizer or desktop models."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import argparse
import zipfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--anime-lama', action='store_true')
    args = parser.parse_args()
    root = Path(__file__).parent / "models"
    bundle = root / "app-bundle/models"
    sources = {
        "detector.onnx": root / "yolo_manga_textbox.onnx",
        "ocr_detector.onnx": root / "easyocr-onnx-float/detector.onnx",
        "detector.data": root / "easyocr-onnx-float/detector.data",
        "lama_dilated.onnx": root / "lama_dilated-onnx-float/lama_dilated.onnx",
        "lama_dilated.data": root / "lama_dilated-onnx-float/lama_dilated.data",
    }
    if args.anime_lama:
        sources.pop('lama_dilated.onnx'); sources.pop('lama_dilated.data')
        verified = json.loads((root / 'anime-npu/verified.json').read_text(encoding='utf-8'))
        assert verified.get('passed') and verified['other_kernel_events'] == 0
        stages = json.loads((root / 'anime-npu/pipeline.json').read_text(encoding='utf-8'))
        for filename in ('pipeline.json', *(stage['file'] for stage in stages)):
            sources['anime/' + filename] = root / 'anime-npu' / filename
    for language in ("ja", "ko", "zh", "ru", "en"):
        for extension in ("onnx", "json"):
            name = language + "." + extension
            sources["ocr/" + name] = root / "ocr" / name
    translation = root / "qwen3_0_6b-genie-w4a16-qualcomm_snapdragon_8_elite_for_galaxy"
    for source in translation.iterdir():
        if source.is_file():
            sources["translation/" + source.name] = source
    assert "translation/genie_config.json" in sources and "translation/part2_of_2.bin" in sources
    manifest = []
    for name, source in sources.items():
        if not source.is_file() or source.stat().st_size == 0:
            raise FileNotFoundError(source)
        dest = bundle / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists() and not os.path.samefile(source, dest):
            dest.unlink()
        if not dest.exists():
            try:
                os.link(source, dest)
            except OSError:
                shutil.copyfile(source, dest)
        with dest.open("rb") as data:
            digest = hashlib.file_digest(data, "sha256").hexdigest()
        category = 'translation' if name.startswith('translation/') else 'inpainting' if name.startswith(('lama_', 'anime/')) else 'ocr'
        manifest.append({"path": name, "bytes": dest.stat().st_size, "sha256": digest, "category": category})
    for previous in bundle.rglob("*"):
        if previous.is_file() and previous.relative_to(bundle).as_posix() not in sources and previous.name != "manifest.json":
            previous.unlink()
    (bundle / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (bundle.parent / 'model-catalog.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    packs = Path(__file__).parent / 'dist'
    packs.mkdir(exist_ok=True)
    for category in ('ocr', 'inpainting', 'translation'):
        with zipfile.ZipFile(packs / ('MangaAMTL-' + category + '-models.zip'), 'w', zipfile.ZIP_DEFLATED) as archive:
            for item in manifest:
                if item['category'] == category: archive.write(bundle / item['path'], item['path'])
    print(f"Prepared {len(manifest)} model files, {sum(f['bytes'] for f in manifest):,} bytes")


if __name__ == "__main__":
    main()
