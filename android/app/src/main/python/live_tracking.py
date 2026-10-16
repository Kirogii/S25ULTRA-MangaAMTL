"""Track independently moving screen regions; OCR only uncovered/changed areas."""
import json
import cv2
import numpy as np


def visible(box):
    return box[2] > 0 and box[3] > 0 and box[0] < 1 and box[1] < 1


def overlap(a, b):
    return max(0, min(a[2], b[2])-max(a[0], b[0])) * max(0, min(a[3], b[3])-max(a[1], b[1]))


class Tracker:
    def __init__(self):
        self.previous = None
        self.items = {}
        self.clips = {}
        self.coverage = []
        self.pending = None
        self.serial = 0
        self.last_ignore = []
        self.overlays = {}
        self.history = []
        self.orb = cv2.ORB_create(nfeatures=400, edgeThreshold=12, fastThreshold=12)

    def remember(self, cells):
        if self.previous is None:
            return
        points, descriptors = self.orb.detectAndCompute(self.previous, None)
        self.history.append(dict(image=self.previous.copy(), cells=cells, points=points, descriptors=descriptors,
            items=[dict(id=k, rect=list(b), clip=list(self.clips[k]), overlay=self.overlays[k])
                   for k, b in self.items.items() if k in self.overlays]))
        # Keep screenshots in RAM only, bounded independently of session length.
        while len(self.history) > 16 or sum(frame['image'].nbytes + sum(len(i['overlay']) for i in frame['items'])
                                           for frame in self.history) > 16_000_000:
            self.history.pop(0)

    def restore(self, current, covered, ignored):
        height, width = current.shape
        added = []
        current_points, current_descriptors = self.orb.detectAndCompute(current, None)
        matcher = cv2.BFMatcher(cv2.NORM_HAMMING)
        for frame in reversed(self.history):
            if frame['image'].shape != current.shape:
                continue
            offsets = [(0, 0)]
            if frame['descriptors'] is not None and current_descriptors is not None:
                pairs = matcher.knnMatch(frame['descriptors'], current_descriptors, k=2)
                shifts = [np.array(current_points[a.trainIdx].pt)-np.array(frame['points'][a.queryIdx].pt)
                          for pair in pairs if len(pair) == 2 for a, b in [pair] if a.distance < .7*b.distance]
                if shifts:
                    shifts = np.array(shifts)
                    while len(shifts) >= 4 and len(offsets) < 4:
                        buckets = np.round(shifts/4).astype(int)
                        groups, counts = np.unique(buckets, axis=0, return_counts=True)
                        center = groups[counts.argmax()]*4
                        coherent = np.linalg.norm(shifts-center, axis=1) < 5
                        if coherent.sum() < 4:
                            break
                        offset = tuple(np.round(np.median(shifts[coherent], axis=0)).astype(int))
                        if all(np.linalg.norm(np.array(offset)-old) > 3 for old in offsets):
                            offsets.append(offset)
                        shifts = shifts[~coherent]
            for cell, (sx, sy) in [(cell, offset) for offset in offsets for cell in frame['cells']]:
                x1, y1, x2, y2 = [int(v*s) for v, s in zip(cell, [width, height, width, height])]
                x1, y1, x2, y2 = max(0, x1), max(0, y1), min(width, x2), min(height, y2)
                patch = frame['image'][y1:y2, x1:x2]
                if min(patch.shape, default=0) < 8:
                    continue
                px, py = x1+sx, y1+sy
                if px < 0 or py < 0 or px+patch.shape[1] > width or py+patch.shape[0] > height:
                    continue
                if (cv2.absdiff(patch, current[py:py+patch.shape[0], px:px+patch.shape[1]]) > 20).mean() > .025:
                    continue
                destination = [px/width, py/height, (px+patch.shape[1])/width, (py+patch.shape[0])/height]
                if any(overlap(destination, b) > 0 for b in ignored):
                    continue
                if covered[py:py+patch.shape[0], px:px+patch.shape[1]].mean() > .98:
                    continue
                dx, dy = (px-x1)/width, (py-y1)/height
                self.coverage.append(destination)
                covered[py:py+patch.shape[0], px:px+patch.shape[1]] = 1
                for item in frame['items']:
                    key, source = item['id'], item['rect']
                    if key in self.items or overlap(source, cell) <= 0:
                        continue
                    box = [source[0]+dx, source[1]+dy, source[2]+dx, source[3]+dy]
                    clip = item['clip']
                    if not visible(box) or overlap(box, clip) <= 0:
                        continue
                    # Verify every visible pixel of the text region, not merely
                    # its anchor tile, before resurrecting a cached translation.
                    sx, sy = px-x1, py-y1
                    a, b, c, d = [int(v*s) for v, s in zip(source, [width, height, width, height])]
                    a, b = max(a, 0, -sx), max(b, 0, -sy, int(clip[1]*height)-sy)
                    c, d = min(c, width, width-sx), min(d, height, height-sy, int(clip[3]*height)-sy)
                    if c-a < 3 or d-b < 3:
                        continue
                    if (cv2.absdiff(frame['image'][b:d, a:c], current[b+sy:d+sy, a+sx:c+sx]) > 20).mean() > .05:
                        continue
                    self.items[key], self.clips[key], self.overlays[key] = box, clip, item['overlay']
                    added.append(dict(id=key, rect=box, clip=clip, overlay=item['overlay']))
        self.coverage = self.coverage[-256:]
        return added

    @staticmethod
    def cells(box):
        for row in range(12):
            for col in range(2):
                cell = [col/2, row/12, (col+1)/2, (row+1)/12]
                clipped = [max(cell[0], box[0]), max(cell[1], box[1]), min(cell[2], box[2]), min(cell[3], box[3])]
                if overlap(cell, box) > 0:
                    yield clipped

    def begin(self, box_json):
        box = json.loads(box_json)
        self.serial += 1
        self.pending = dict(id=self.serial, box=box, cells=[dict(original=list(c), current=list(c), clip=[0, 0, 1, 1], valid=True) for c in self.cells(box)])
        return self.serial

    def abort(self, serial):
        if self.pending is not None and self.pending['id'] == serial:
            self.pending = None

    def finish(self, serial, response_json):
        if self.pending is None or self.pending['id'] != serial:
            return json.dumps(dict(add=[], remove=[]))
        pending, self.pending = self.pending, None
        response = json.loads(response_json)
        x, y, right, bottom = pending['box']
        added, removed = [], []
        for item in response.get('items', []):
            b = item['bbox']
            source = [x+b[0]/response['width']*(right-x), y+b[1]/response['height']*(bottom-y),
                      x+b[2]/response['width']*(right-x), y+b[3]/response['height']*(bottom-y)]
            center = [(source[0]+source[2])/2, (source[1]+source[3])/2]
            anchor = next((c for c in pending['cells'] if c['original'][0] <= center[0] <= c['original'][2]
                           and c['original'][1] <= center[1] <= c['original'][3]), None)
            if anchor is None or not anchor['valid']:
                continue
            dx = anchor['current'][0]-anchor['original'][0]
            dy = anchor['current'][1]-anchor['original'][1]
            box = [source[0]+dx, source[1]+dy, source[2]+dx, source[3]+dy]
            if not visible(box) or overlap(box, anchor['clip']) <= 0:
                continue
            for key, old in list(self.items.items()):
                area = max(1e-8, (min(1, old[2])-max(0, old[0]))*(min(1, old[3])-max(0, old[1])))
                if overlap(old, box)/area > .6:
                    del self.items[key]; self.clips.pop(key, None); self.overlays.pop(key, None); removed.append(key)
            self.serial += 1
            key = str(self.serial)
            self.items[key] = box
            self.clips[key] = anchor['clip']
            self.overlays[key] = item['overlay']
            added.append(dict(id=key, rect=box, clip=anchor['clip'], overlay=item['overlay']))
        self.coverage.extend(c['current'] for c in pending['cells'] if c['valid'] and visible(c['current']))
        self.coverage = self.coverage[-256:]
        self.remember([c['current'] for c in pending['cells'] if c['valid'] and visible(c['current'])])
        return json.dumps(dict(add=added, remove=removed))

    def track(self, pixels, width, height, ignore_json='[]'):
        current = np.frombuffer(bytes(pixels), np.uint8).reshape(height, width).copy()
        ignored = json.loads(ignore_json)
        previous = self.previous
        points = np.empty((0, 2), np.float32)
        motions = np.empty((0, 2), np.float32)
        if previous is not None and previous.shape == current.shape:
            mask = np.full(current.shape, 255, np.uint8)
            for b in self.last_ignore:
                mask[max(0, int(b[1]*height)):min(height, int(b[3]*height)), max(0, int(b[0]*width)):min(width, int(b[2]*width))] = 0
            corners = cv2.goodFeaturesToTrack(previous, 600, .02, 3, mask=mask)
            if corners is not None:
                target, ok, error = cv2.calcOpticalFlowPyrLK(previous, current, corners, None, winSize=(21, 21), maxLevel=3)
                back, back_ok, _ = cv2.calcOpticalFlowPyrLK(current, previous, target, None, winSize=(21, 21), maxLevel=3)
                old, new = corners.reshape(-1, 2), target.reshape(-1, 2)
                valid = ok.ravel().astype(bool) & back_ok.ravel().astype(bool) & (error.ravel() < 35)
                valid &= np.linalg.norm(back.reshape(-1, 2)-old, axis=1) < 1.25
                for b in ignored:
                    valid &= ~((new[:, 0] >= b[0]*width) & (new[:, 0] <= b[2]*width)
                               & (new[:, 1] >= b[1]*height) & (new[:, 1] <= b[3]*height))
                points, motions = old[valid], new[valid]-old[valid]

        def movement(box, clip=None):
            if previous is not None and previous.shape == current.shape:
                x1, y1, x2, y2 = [int(v*s) for v, s in zip(box, [width, height, width, height])]
                x1, y1, x2, y2 = max(0, x1), max(0, y1), min(width, x2), min(height, y2)
                if clip is not None:
                    x1, y1 = max(x1, int(clip[0]*width)), max(y1, int(clip[1]*height))
                    x2, y2 = min(x2, int(clip[2]*width)), min(y2, int(clip[3]*height))
                if x2 > x1 and y2 > y1 and float((cv2.absdiff(previous[y1:y2, x1:x2], current[y1:y2, x1:x2]) > 15).mean()) < .025:
                    return (0., 0.)
            if not len(points): return (0., 0.)
            available = np.arange(len(points))
            if clip is not None:
                available = available[(points[:, 0] >= clip[0]*width) & (points[:, 0] <= clip[2]*width)
                    & (points[:, 1] >= clip[1]*height) & (points[:, 1] <= clip[3]*height)]
            inside = available[(points[available, 0] >= box[0]*width) & (points[available, 0] <= box[2]*width)
                & (points[available, 1] >= box[1]*height) & (points[available, 1] <= box[3]*height)]
            cx, cy = np.clip([(box[0]+box[2])/2, (box[1]+box[3])/2], 0, 1)*[width, height]
            if clip is not None:
                cx = np.clip(cx, clip[0]*width, clip[2]*width)
                cy = np.clip(cy, clip[1]*height, clip[3]*height)
            distance = ((points[:, 0]-cx)/(width/4))**2 + ((points[:, 1]-cy)/(height/16))**2
            nearest = inside if len(inside) >= 3 else available[np.argsort(distance[available])[:12]]
            nearest = nearest[distance[nearest] < 4]
            if len(nearest) < 3: return (0., 0.)
            median = np.median(motions[nearest], axis=0)
            coherent = np.linalg.norm(motions[nearest]-median, axis=1) < 2.5
            if coherent.sum() < 3: return (0., 0.)
            dx, dy = np.median(motions[nearest][coherent], axis=0)/[width, height]
            return float(dx), float(dy)

        stable_regions = []

        def changed(box, dx, dy, threshold, clip=None, ignore_stable=False):
            if previous is None or previous.shape != current.shape: return False
            x1, y1, x2, y2 = [int(v*s) for v, s in zip(box, [width, height, width, height])]
            sx, sy = int(round(dx*width)), int(round(dy*height))
            x1, y1 = max(0, x1, -sx), max(0, y1, -sy)
            x2, y2 = min(width, x2, width-sx), min(height, y2, height-sy)
            if clip is not None:
                x1, y1 = max(x1, int(clip[0]*width)-sx), max(y1, int(clip[1]*height)-sy)
                x2, y2 = min(x2, int(clip[2]*width)-sx), min(y2, int(clip[3]*height)-sy)
            if x2-x1 < 3 or y2-y1 < 3: return False
            a, b = previous[y1:y2, x1:x2], current[y1+sy:y2+sy, x1+sx:x2+sx]
            # Slight reconstruction/compositor quantization is not a menu change.
            difference = cv2.absdiff(a, b) > 30
            if ignore_stable:
                for region in stable_regions:
                    left, top, right, bottom = [int(v*s) for v, s in zip(region, [width, height, width, height])]
                    left, top, right, bottom = max(left, x1), max(top, y1), min(right, x2), min(bottom, y2)
                    if right > left and bottom > top:
                        difference[top-y1:bottom-y1, left-x1:right-x1] = False
            return float(difference.mean()) > threshold

        def move(box, clip=None):
            dx, dy = movement(box, clip)
            return [box[0]+dx, box[1]+dy, box[2]+dx, box[3]+dy], dx, dy

        def panel_clip(box, dx, dy):
            if abs(dy)*height < 1.5: return None
            col = min(1, max(0, int((box[0]+box[2]))))
            row = min(11, max(0, int((box[1]+box[3])*6)))
            start, end = row, row
            for step in (-1, 1):
                r = row+step
                while 0 <= r < 12:
                    _, nearby = movement([col/2, r/12, (col+1)/2, (r+1)/12])
                    if abs(nearby-dy)*height > 3: break
                    if step < 0: start = r
                    else: end = r
                    r += step
            top, bottom = start/12, (end+1)/12
            if previous is not None:
                sx, sy = int(round(dx*width)), int(round(dy*height))
                warped = cv2.warpAffine(previous, np.float32([[1, 0, sx], [0, 1, sy]]), (width, height))
                difference = (cv2.absdiff(warped, current)[:, col*width//2:(col+1)*width//2] > 30).mean(axis=1)
                center = int(np.clip(((box[1]+box[3])/2+dy)*height, 0, height-1))
                candidates = np.arange(max(0, int((box[1]+dy)*height)), min(height, int((box[3]+dy)*height)))
                candidates = candidates[difference[candidates] < .35]
                if len(candidates): center = int(candidates[np.argmin(abs(candidates-center))])
                for step in (-1, 1):
                    boundary = max(0, int(top*height)-height//12) if step < 0 else min(height-1, int(bottom*height)+height//12)
                    row, bad = center, 0
                    while 0 <= row < height and (row >= boundary if step < 0 else row <= boundary):
                        bad = bad+1 if difference[row] > .35 else 0
                        if bad >= 2:
                            if step < 0: top = (row+2)/height
                            else: bottom = (row-1)/height
                            break
                        row += step
            return [0, top, 1, bottom]

        removed = []
        for key, box in list(self.items.items()):
            destination, dx, dy = move(box, self.clips.get(key))
            clip = panel_clip(box, dx, dy) or self.clips.get(key, [0, 0, 1, 1])
            shown_width = min(destination[2], clip[2], 1)-max(destination[0], clip[0], 0)
            shown_height = min(destination[3], clip[3], 1)-max(destination[1], clip[1], 0)
            if shown_width*width < 1 or shown_height*height < 1 or changed(box, dx, dy, .22, clip):
                del self.items[key]; self.clips.pop(key, None); self.overlays.pop(key, None); removed.append(key)
            else:
                stable_regions.append(box)
                self.items[key] = destination
                self.clips[key] = clip
        coverage = []
        for box in self.coverage:
            destination, dx, dy = move(box)
            if visible(destination) and not changed(box, dx, dy, .008, ignore_stable=True): coverage.append(destination)
        self.coverage = coverage
        if self.pending is not None:
            for cell in self.pending['cells']:
                box = cell['current']
                destination, dx, dy = move(box)
                cell['clip'] = panel_clip(box, dx, dy) or cell['clip']
                cell['valid'] &= visible(destination) and overlap(destination, cell['clip']) > 0 and not changed(box, dx, dy, .10)
                cell['current'] = destination
        self.previous, self.last_ignore = current, ignored
        covered = np.zeros(current.shape, np.uint8)
        for b in self.coverage:
            covered[max(0, int(b[1]*height)):min(height, int(b[3]*height)), max(0, int(b[0]*width)):min(width, int(b[2]*width))] = 1
        added = self.restore(current, covered, ignored) if self.history and covered.mean() < .998 else []
        removed = [key for key in removed if key not in self.items]
        covered = cv2.dilate(covered, np.ones((3, 3), np.uint8))
        for b in ignored:
            covered[max(0, int(b[1]*height)):min(height, int(b[3]*height)), max(0, int(b[0]*width)):min(width, int(b[2]*width))] = 1
        dirty = None
        if self.pending is None:
            count, _, stats, _ = cv2.connectedComponentsWithStats(1-covered)
            candidates = [s for s in stats[1:] if s[4] >= max(24, width*height*.002)]
            if candidates:
                x, y, w, h, _ = max(candidates, key=lambda s: s[4])
                # Keep complete horizontal text lines and neighboring context;
                # a thin newly exposed strip can otherwise split a sentence.
                padding = max(6, height//24)
                dirty = [0., max(0., (y-padding)/height), 1., min(1., (y+h+padding)/height)]
        return json.dumps(dict(move=[dict(id=k, rect=b, clip=self.clips[k]) for k, b in self.items.items()], add=added, remove=removed, dirty=dirty))
