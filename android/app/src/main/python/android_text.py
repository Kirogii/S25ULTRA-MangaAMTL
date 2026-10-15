"""Reuse identical width measurements within one unchanged font-fitting call."""
from functools import lru_cache, wraps
from types import SimpleNamespace


def install(module):
    original = module.fit_font_and_wrap

    @wraps(original)
    def fit(draw, *args, **kwargs):
        # Measurements depend on the font and text, not the drawing's pixels.
        # Keep the cache local so it cannot retain pages or stale font settings.
        measured = SimpleNamespace(
            textlength=lru_cache(maxsize=1024)(draw.textlength),
            textbbox=draw.textbbox,
        )
        return original(measured, *args, **kwargs)

    module.fit_font_and_wrap = fit
