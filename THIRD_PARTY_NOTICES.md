Blur mode adapts background sampling, black/white contrast selection, and cropped
OpenCV Telea erasure from Kuju29's TextPhantomOCR_Overlay:
https://github.com/Kuju29/TextPhantomOCR_Overlay

Source files: `api/backend/render/colors.py` and `api/backend/render/erase.py`,
retrieved October 15, 2026. The reference calls the erasure strategy `inpaint`;
MangaAMTL exposes it as Blur. It uses radius 3, an elliptical one-pixel dilation,
and eight pixels of crop slack. Existing box geometry and rendering are retained.
