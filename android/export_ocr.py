"""Export EasyOCR recognizers with LSTMs expanded into NPU-supported operations."""
import argparse
import json
from pathlib import Path

import easyocr
import torch
from torch import nn
from torch.nn import functional as F

LANGUAGES = {"ja": ["ja", "en"], "ko": ["ko", "en"], "zh": ["ch_sim", "en"],
             "ru": ["ru", "en"], "en": ["en"]}


class UnrolledLSTM(nn.Module):
    def __init__(self, original):
        super().__init__()
        if original.num_layers != 1 or not original.batch_first or not original.bidirectional:
            raise ValueError("Expected EasyOCR's single-layer, bidirectional, batch-first LSTM")
        self.original = original

    def forward(self, x):
        outputs = []
        for reverse in (False, True):
            suffix = "_reverse" if reverse else ""
            ih = getattr(self.original, "weight_ih_l0" + suffix)
            hh = getattr(self.original, "weight_hh_l0" + suffix)
            bi = getattr(self.original, "bias_ih_l0" + suffix)
            bh = getattr(self.original, "bias_hh_l0" + suffix)
            h = x.new_zeros((x.shape[0], self.original.hidden_size))
            c = torch.zeros_like(h)
            sequence = []
            for i in (range(x.shape[1] - 1, -1, -1) if reverse else range(x.shape[1])):
                gates = F.linear(x[:, i], ih, bi) + F.linear(h, hh, bh)
                ingate, forget, candidate, outgate = gates.chunk(4, dim=1)
                c = forget.sigmoid() * c + ingate.sigmoid() * candidate.tanh()
                h = outgate.sigmoid() * c.tanh()
                sequence.append(h)
            outputs.append(torch.stack(sequence[::-1] if reverse else sequence, dim=1))
        return torch.cat(outputs, dim=2), None


class Recognizer(nn.Module):
    def __init__(self, model):
        super().__init__()
        self.model = model

    def forward(self, image):
        return self.model((image - 0.5) / 0.5, None)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--language", choices=[*LANGUAGES, "all"], default="ja")
    args = parser.parse_args()
    root = Path(__file__).parent / "models/ocr"
    root.mkdir(parents=True, exist_ok=True)
    torch.set_num_threads(4)
    for language in (LANGUAGES if args.language == "all" else [args.language]):
        reader = easyocr.Reader(LANGUAGES[language], gpu=False, detector=False,
                                quantize=False, verbose=False)
        model = reader.recognizer.eval()
        sample = torch.rand(1, 1, 64, 640)
        with torch.inference_mode():
            reference = Recognizer(model)(sample)
        for layer in model.SequenceModeling:
            layer.rnn = UnrolledLSTM(layer.rnn)
        wrapper = Recognizer(model).eval()
        with torch.inference_mode():
            torch.testing.assert_close(wrapper(sample), reference, atol=1e-3, rtol=1e-3)
        dest = root / (language + ".onnx")
        torch.onnx.export(wrapper, sample, str(dest), input_names=["image"],
                          output_names=["predictions"], opset_version=18, dynamo=False)
        # CTC class zero is blank; EasyOCR's character string starts at class one.
        (root / (language + ".json")).write_text(json.dumps({"characters": reader.character,
            "shape": [1, 1, 64, 640], "source": "EasyOCR 1.7.2", "languages": LANGUAGES[language]},
            ensure_ascii=False), encoding="utf-8")
        print(language, dest.stat().st_size, "bytes; unrolled output matches original", flush=True)


if __name__ == "__main__":
    main()
