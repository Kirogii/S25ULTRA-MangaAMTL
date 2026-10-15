"""Trade a little localhost bandwidth for faster lossless page encoding."""
from PIL import Image, PngImagePlugin


def save(image, fp, filename):
    image.encoderinfo.setdefault("compress_level", 1)
    return PngImagePlugin._save(image, fp, filename)


def install():
    Image.register_save("PNG", save)
