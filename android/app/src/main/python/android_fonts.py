"""Validate imported fonts with the same FreeType renderer as app.py."""
import json
from pathlib import Path
import sys

from PIL import ImageFont


def import_font(root, incoming, name):
    root = Path(root).resolve()
    incoming = Path(incoming).resolve()
    fonts = root / "fonts"
    name = Path(name).name
    if (incoming.parent != fonts or incoming.suffix != ".part"
            or Path(name).suffix.lower() not in {".ttf", ".otf", ".ttc"}
            or not 0 < incoming.stat().st_size <= 320_000_000):
        raise ValueError("Choose a TTF, OTF or TTC font up to 320 MB")
    ImageFont.truetype(str(incoming), 24).getmask("Font preview")
    destination = fonts / name
    if destination.exists():
        raise ValueError("This imported font already exists")
    incoming.rename(destination)
    previous = None
    module = sys.modules.get("manga_android")
    try:
        if module is not None and Path(module.__file__).resolve().parent == root:
            with module._font_config_lock:
                previous = module._current_font_path
                module._current_font_path = destination
                module.clear_font_cache()
                module._save_settings()
                saved = json.loads((root / "settings.json").read_text(encoding="utf-8"))
                if saved.get("font_path") != str(destination):
                    raise OSError("Could not save the imported font selection")
        else:
            settings_file = root / "settings.json"
            settings = json.loads(settings_file.read_text(encoding="utf-8")) if settings_file.exists() else {}
            settings["font_path"] = str(destination)
            temporary = settings_file.with_suffix(".font-import.tmp")
            temporary.write_text(json.dumps(settings, ensure_ascii=False), encoding="utf-8")
            temporary.replace(settings_file)
    except Exception:
        if previous is not None:
            with module._font_config_lock:
                module._current_font_path = previous
                module.clear_font_cache()
        destination.unlink(missing_ok=True)
        raise
    return destination.name
