"""Reuse font measurements and completed layouts without retaining page objects."""
from functools import lru_cache, wraps
from types import SimpleNamespace
from collections import OrderedDict
from threading import Lock


def install(module):
    original = module.fit_font_and_wrap
    layouts = OrderedDict()
    lock = Lock()

    @wraps(original)
    def fit(draw, text, box_w, box_h, font_path=None, max_size=96, min_size=17,
            is_vertical=False, inner_padding_ratio=0.0):
        if font_path is None and hasattr(module, '_current_font_path'):
            font_path = str(module._current_font_path)
        key = (text, box_w, box_h, str(font_path) if font_path is not None else None,
               max_size, min_size, is_vertical, inner_padding_ratio, getattr(draw, 'fontmode', None))
        with lock:
            cached = layouts.get(key)
            if cached is not None:
                layouts.move_to_end(key)
        if cached is not None:
            size, lines, heights, width, height = cached
            return size, list(lines), list(heights), width, height
        # Measurements depend on the font and text, not the drawing's pixels.
        # Keep the cache local so it cannot retain pages or stale font settings.
        measured = SimpleNamespace(
            textlength=lru_cache(maxsize=1024)(draw.textlength),
            textbbox=draw.textbbox,
        )
        result = original(measured, text, box_w, box_h, font_path=font_path,
            max_size=max_size, min_size=min_size, is_vertical=is_vertical,
            inner_padding_ratio=inner_padding_ratio)
        size, lines, heights, width, height = result
        with lock:
            layouts[key] = (size, tuple(lines), tuple(heights), width, height)
            layouts.move_to_end(key)
            while len(layouts) > 256:
                layouts.popitem(last=False)
        return result

    module.fit_font_and_wrap = fit
    clear = getattr(module, 'clear_font_cache', None)
    if clear is not None:
        @wraps(clear)
        def clear_all():
            with lock:
                layouts.clear()
            module._android_font_revision = getattr(module, '_android_font_revision', 0)+1
            clear()
        module.clear_font_cache = clear_all
