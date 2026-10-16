"""Send detected text crops together in one Lens request; restore screen coordinates."""
from PIL import Image
from collections import OrderedDict
import copy
import hashlib
import json


class OcrCache:
    """Exact pixels only; never retain source images or reuse partial text matches."""
    def __init__(self):
        self.values = OrderedDict()
        self.bytes = 0

    @staticmethod
    def key(image, language, profile):
        pixels = image if image.mode == 'RGB' else image.convert('RGB')
        return profile, language, pixels.size, hashlib.blake2b(pixels.tobytes(), digest_size=16).digest()

    def get(self, key):
        entry = self.values.get(key)
        if entry is None: return None
        self.values.move_to_end(key)
        return copy.deepcopy(entry[0])

    def put(self, key, regions):
        if not regions: return  # Do not turn an empty/failed cloud response into a cached blank screen.
        size = len(json.dumps(regions, ensure_ascii=False).encode('utf-8'))
        if size > 8_000_000: return
        old = self.values.pop(key, None)
        if old is not None: self.bytes -= old[1]
        self.values[key] = (copy.deepcopy(regions), size); self.bytes += size
        while len(self.values) > 32 or self.bytes > 8_000_000:
            _, (_, removed) = self.values.popitem(last=False); self.bytes -= removed

    def clear(self):
        self.values.clear(); self.bytes = 0


def pack(page, boxes):
    crops = []
    for box in boxes:
        x1, y1, x2, y2 = [int(v) for v in box]
        padding = max(8, min(24, (y2-y1)//4))
        box = [max(0, x1-padding), max(0, y1-padding), min(page.width, x2+padding), min(page.height, y2+padding)]
        if box[2] > box[0] and box[3] > box[1]: crops.append(box)
    # Merge intersecting detections: YOLO bubbles often contain several CRAFT lines.
    merged = []
    while crops:
        box = crops.pop(0)
        while True:
            index = next((i for i, old in enumerate(crops) if min(box[2], old[2]) > max(box[0], old[0])
                          and min(box[3], old[3]) > max(box[1], old[1])), None)
            if index is None: break
            old = crops.pop(index)
            box = [min(box[0], old[0]), min(box[1], old[1]), max(box[2], old[2]), max(box[3], old[3])]
        merged.append(box)
    if not merged or len(merged) > 64:
        return page, None
    merged.sort(key=lambda box: (box[1], box[0]))
    width = max(b[2]-b[0] for b in merged)+24
    height = sum(b[3]-b[1]+24 for b in merged)
    if height > 4096 or width*height >= page.width*page.height*.85:
        return page, None
    image = Image.new('RGB', (width, height), 'white')
    slots, top = [], 12
    for box in merged:
        crop = page.crop(box)
        image.paste(crop, (12, top))
        slots.append((box, [12, top, 12+crop.width, top+crop.height]))
        top += crop.height+24
    return image, slots


def unpack(regions, slots):
    if slots is None: return regions
    result = []
    for region in regions:
        x1, y1, x2, y2 = region['bbox']
        for source, packed in slots:
            if not (packed[0] <= (x1+x2)/2 <= packed[2] and packed[1] <= (y1+y2)/2 <= packed[3]):
                continue
            def mapped(box):
                a, b, c, d = box
                return [max(a, packed[0])-packed[0]+source[0], max(b, packed[1])-packed[1]+source[1],
                        min(c, packed[2])-packed[0]+source[0], min(d, packed[3])-packed[1]+source[1]]
            box = mapped(region['bbox'])
            if box[2] > box[0] and box[3] > box[1]:
                item = dict(region, bbox=box)
                item['bboxes'] = [mapped(b) for b in region.get('bboxes', [region['bbox']])
                                  if min(b[2], packed[2]) > max(b[0], packed[0]) and min(b[3], packed[3]) > max(b[1], packed[1])]
                result.append(item)
            break
    return result
