"""Export app.py's manga YOLO detector with a fixed NPU input shape."""
import hashlib
from pathlib import Path
import requests
import torch
from ultralytics import YOLO

ROOT = Path(__file__).parent / 'models'
WEIGHTS = ROOT / 'yolo_manga_textbox.pt'
SHA256 = '70a7013038ff1313d67d9e698c52e952eeb156f7842657fc78a71e5f968aaa87'

if __name__ == '__main__':
    ROOT.mkdir(exist_ok=True)
    if not WEIGHTS.is_file():
        response = requests.get('https://huggingface.co/Kirogii/Yolo-Manga_Textbox-Region_Detect/resolve/main/model.pt', timeout=120)
        response.raise_for_status()
        assert hashlib.sha256(response.content).hexdigest() == SHA256
        WEIGHTS.write_bytes(response.content)
    assert hashlib.sha256(WEIGHTS.read_bytes()).hexdigest() == SHA256
    model = YOLO(str(WEIGHTS)).model.cpu().eval().fuse()
    model.model[-1].export, model.model[-1].format, model.model[-1].dynamic = True, 'onnx', False
    image = torch.zeros(1, 3, 640, 640)
    with torch.no_grad():
        assert tuple(model(image).shape) == (1, 5, 8400)
    torch.onnx.export(model, image, str(ROOT / 'yolo_manga_textbox.onnx'),
                      input_names=['image'], output_names=['boxes'], opset_version=18, dynamo=False)
