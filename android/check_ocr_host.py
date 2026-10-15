"""Host-only CPU calibration of the preprocessing used by Android's NPU OCR."""
import ast
import json
from pathlib import Path
import types
import cv2
import numpy as np
import onnxruntime as ort
from PIL import Image

project = Path(__file__).resolve().parent.parent
root = project / 'android/models/app-bundle'
source = (project / 'android/app/src/main/python/android_server.py').read_text(encoding='utf-8')
tree = ast.parse(source)
load = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'load_app')
names = {'text_columns','detector','recognize','ocr','ink_spans'}
definitions = [n for n in load.body if isinstance(n, ast.FunctionDef) and n.name in names]
sessions = {}
def infer(name, image, mask=None):
    if name not in sessions:
        sessions[name] = ort.InferenceSession(str(root / 'models' / name), providers=['CPUExecutionProvider'])
    return sessions[name].run(None, {'image': np.ascontiguousarray(image,dtype=np.float32)})[0].flatten()
def iou(a,b):
    intersection=max(0,min(a[2],b[2])-max(a[0],b[0]))*max(0,min(a[3],b[3])-max(a[1],b[1]))
    return intersection/max(1,(a[2]-a[0])*(a[3]-a[1])+(b[2]-b[0])*(b[3]-b[1])-intersection)
module=types.SimpleNamespace(_bbox_iou=iou)
scope=dict(np=np,cv2=cv2,json=json,root=root,module=module,infer=infer,alphabets={})
exec(compile(ast.Module(body=definitions,type_ignores=[]),'ocr calibration','exec'),scope)
page=Image.open(project / 'Images/Raw.png').convert('RGB')
original=scope['recognize']
out=project / 'android/evidence/crops';out.mkdir(parents=True,exist_ok=True)
recognized = []
for i,box in enumerate(scope['detector'](page)):
    crop=page.crop(box)
    columns=scope['text_columns'](crop)
    print(i,box,columns,flush=True)
    for j,column in enumerate(columns):
        tile=crop.crop(column)
        tile.save(out/f'{i}-{j}.png')
        text = original(crop,column,'ja')
        recognized.append(text)
        print(' ',j,text,flush=True)
assert any('建築に' in text for text in recognized)
assert any('小さい頃からの' in text for text in recognized)
