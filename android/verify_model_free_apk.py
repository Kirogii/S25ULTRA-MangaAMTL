"""Fail release builds which accidentally package AI model weights."""
import json
import sys
import zipfile


def verify(path):
    with zipfile.ZipFile(path) as apk:
        weights = [name for name in apk.namelist() if
                   name.lower().endswith(('.onnx', '.data', '.bin', '.pt', '.pth', '.safetensors', '.tflite', '.gguf'))
                   or (name.startswith('assets/models/') and name != 'assets/models/manifest.json')]
        if weights:
            raise ValueError('Bundled AI model files: ' + ', '.join(weights))
        if json.loads(apk.read('assets/models/manifest.json')) != []:
            raise ValueError('Bundled model manifest must be empty')
    print('Verified: APK contains no AI model weights')


if __name__ == '__main__':
    verify(sys.argv[1])
