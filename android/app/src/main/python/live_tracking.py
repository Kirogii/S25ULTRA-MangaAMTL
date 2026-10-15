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
                    del self.items[key]; self.clips.pop(key, None); removed.append(key)
            self.serial += 1
            key = str(self.serial)
            self.items[key] = box
            self.clips[key] = anchor['clip']
            added.append(dict(id=key, rect=box, clip=anchor['clip'], overlay=item['overlay']))
        self.coverage.extend(c['current'] for c in pending['cells'] if c['valid'] and visible(c['current']))
        self.coverage = self.coverage[-256:]
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
            distance = ((points[:, 0]-cx)/(width/4))**2 + ((points[:, 1]-cy)/(height/16))**2
            nearest = inside if len(inside) >= 3 else available[np.argsort(distance[available])[:12]]
            nearest = nearest[distance[nearest] < 4]
            if len(nearest) < 3: return (0., 0.)
            median = np.median(motions[nearest], axis=0)
            coherent = np.linalg.norm(motions[nearest]-median, axis=1) < 2.5
            if coherent.sum() < 3: return (0., 0.)
            dx, dy = np.median(motions[nearest][coherent], axis=0)/[width, height]
            return float(dx), float(dy)

        def changed(box, dx, dy, threshold, clip=None):
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
            return float((cv2.absdiff(a, b) > 30).mean()) > threshold

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
            if not visible(destination) or overlap(destination, clip) <= 0 or changed(box, dx, dy, .22, clip):
                del self.items[key]; self.clips.pop(key, None); removed.append(key)
            else:
                self.items[key] = destination
                self.clips[key] = clip
        coverage = []
        for box in self.coverage:
            destination, dx, dy = move(box)
            if visible(destination) and not changed(box, dx, dy, .008): coverage.append(destination)
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
        covered = cv2.dilate(covered, np.ones((3, 3), np.uint8))
        for b in ignored:
            covered[max(0, int(b[1]*height)):min(height, int(b[3]*height)), max(0, int(b[0]*width)):min(width, int(b[2]*width))] = 1
        dirty = None
        if self.pending is None:
            count, _, stats, _ = cv2.connectedComponentsWithStats(1-covered)
            candidates = [s for s in stats[1:] if s[4] >= max(24, width*height*.002)]
            if candidates:
                x, y, w, h, _ = max(candidates, key=lambda s: s[4])
                # Include a little neighboring text context at newly exposed edges.
                dirty = [max(0., (x-4)/width), max(0., (y-6)/height), min(1., (x+w+4)/width), min(1., (y+h+6)/height)]
        return json.dumps(dict(move=[dict(id=k, rect=b, clip=self.clips[k]) for k, b in self.items.items()], remove=removed, dirty=dirty))
