"""Export the original manga LaMa weights using real-valued separable DFTs."""
import argparse
from pathlib import Path
import platform

# This Windows host's WMI query hangs; Python's normal registry fallback works.
platform._wmi_query = lambda *args: (_ for _ in ()).throw(OSError("WMI unavailable"))
import numpy as np
import torch
from torch.onnx import symbolic_helper as helper
SPATIAL = 64


class ReducedResolution(torch.nn.Module):
    """Keep the 512px app interface while reducing the network's working image."""
    def __init__(self, model, size):
        super().__init__()
        self.model, self.size = model, size

    def forward(self, image, mask):
        factor = 512 // self.size
        small_image = torch.nn.functional.avg_pool2d(image, kernel_size=factor, stride=factor)
        small_mask = torch.nn.functional.max_pool2d(mask, kernel_size=factor, stride=factor)
        painted = self.model(small_image, small_mask)
        painted = torch.nn.functional.interpolate(painted, size=(512, 512), mode="bilinear", align_corners=False)
        return image * (1-mask) + painted * mask


def constant(g, value):
    return g.op("Constant", value_t=torch.as_tensor(value))


def part(g, value, index):
    return g.op("Gather", value, constant(g, np.array(index, dtype=np.int64)), axis_i=-1)


def pair(g, real, imag):
    axis = constant(g, np.array([-1], dtype=np.int64))
    return g.op("Concat", g.op("Unsqueeze", real, axis), g.op("Unsqueeze", imag, axis), axis_i=-1)


def along_height(g, value, matrix):
    transposed = g.op("Transpose", value, perm_i=[0, 1, 3, 2])
    flat = g.op("Reshape", transposed, constant(g, np.array([-1, SPATIAL], np.int64)))
    result = g.op("MatMul", flat, constant(g, matrix.T.copy()))
    restored = g.op("Reshape", result, constant(g, np.array([1, 192, SPATIAL//2+1, SPATIAL], np.int64)))
    return g.op("Transpose", restored, perm_i=[0, 1, 3, 2])


def along_width(g, value, matrix):
    flat = g.op("Reshape", value, constant(g, np.array([-1, matrix.shape[0]], np.int64)))
    result = g.op("MatMul", flat, constant(g, matrix))
    return g.op("Reshape", result, constant(g, np.array([1, 192, SPATIAL, matrix.shape[1]], np.int64)))


def matrices(height, width):
    h = np.arange(height, dtype=np.float64)
    w = np.arange(width, dtype=np.float64)
    k = np.arange(width // 2 + 1, dtype=np.float64)
    ah = 2 * np.pi * h[:, None] * h[None, :] / height
    aw = 2 * np.pi * w[:, None] * k[None, :] / width
    return [array.astype(np.float32) for array in (np.cos(ah), np.sin(ah), np.cos(aw), np.sin(aw))]


def rfft(g, value, size, dims, norm):
    shape = helper._get_tensor_sizes(value)
    # This checkpoint's 36 Fourier units all run after three stride-2 convolutions.
    height, width = shape[-2:] if shape and all(v is not None for v in shape[-2:]) else (SPATIAL, SPATIAL)
    assert (height, width) == (SPATIAL, SPATIAL)
    assert helper._parse_arg(norm, "s") == "ortho"
    ch, sh, cw, sw = matrices(height, width)
    ch /= np.float32(np.sqrt(height)); sh /= np.float32(np.sqrt(height))
    cw /= np.float32(np.sqrt(width)); sw /= np.float32(np.sqrt(width))
    real = along_width(g, value, cw)
    imag = along_width(g, value, -sw)
    out_real = g.op("Add", along_height(g, real, ch), along_height(g, imag, sh))
    out_imag = g.op("Sub", along_height(g, imag, ch), along_height(g, real, sh))
    return pair(g, out_real, out_imag)


def irfft(g, value, size, dims, norm):
    height, width = SPATIAL, SPATIAL
    assert helper._parse_arg(norm, "s") == "ortho"
    ch, sh, cw, sw = matrices(height, width)
    ch /= np.float32(np.sqrt(height)); sh /= np.float32(np.sqrt(height))
    real, imag = part(g, value, 0), part(g, value, 1)
    hr = g.op("Sub", along_height(g, real, ch), along_height(g, imag, sh))
    hi = g.op("Add", along_height(g, real, sh), along_height(g, imag, ch))
    weights = np.full(width // 2 + 1, 2, np.float32); weights[0] = 1
    if width % 2 == 0: weights[-1] = 1
    scale = (weights / np.sqrt(width)).astype(np.float32)
    return g.op("Sub", along_width(g, hr, (cw * scale).T.copy()), along_width(g, hi, (sw * scale).T.copy()))


def register():
    for name, function in {"fft_rfftn": rfft, "fft_irfftn": irfft,
        "real": lambda g, x: part(g, x, 0), "imag": lambda g, x: part(g, x, 1),
        "complex": pair, "pad": pad}.items():
        torch.onnx.register_custom_op_symbolic("aten::" + name, function, 17)


def pad(g, value, padding, mode, fill):
    if helper._parse_arg(mode, 's') != 'reflect':
        from torch.onnx import symbolic_opset11
        return symbolic_opset11.pad(g, value, padding, mode, fill)
    pads = helper._parse_arg(padding, 'is')
    for index in range(len(pads)//2):
        left, right = pads[index*2:index*2+2]
        axis = 3-index
        pieces = []
        if left: pieces.append(g.op('Gather', value, constant(g, np.arange(left,0,-1,dtype=np.int64)), axis_i=axis))
        pieces.append(value)
        if right: pieces.append(g.op('Gather', value, constant(g, -np.arange(2,right+2,dtype=np.int64)), axis_i=axis))
        value = g.op('Concat', *pieces, axis_i=axis) if len(pieces)>1 else value
    return value


def positive_gathers(path):
    import onnx
    from onnx import numpy_helper
    model = onnx.shape_inference.infer_shapes(onnx.load(path))
    shapes = {value.name: [dimension.dim_value for dimension in value.type.tensor_type.shape.dim]
              for value in [*model.graph.input, *model.graph.value_info]}
    constants = {node.output[0]: numpy_helper.to_array(node.attribute[0].t) for node in model.graph.node if node.op_type == 'Constant' and node.attribute[0].name == 'value'}
    for node in model.graph.node:
        if node.op_type != 'Gather' or node.input[1] not in constants: continue
        indices = constants[node.input[1]]
        if not np.any(indices < 0): continue
        axis = next((attribute.i for attribute in node.attribute if attribute.name == 'axis'), 0)
        dimension = shapes[node.input[0]][axis]
        assert dimension > 0, node.name
        fixed = np.where(indices < 0, indices + dimension, indices).astype(np.int64)
        name = node.name + '_positive_indices'
        model.graph.initializer.append(numpy_helper.from_array(fixed, name)); node.input[1] = name
    onnx.checker.check_model(model)
    onnx.save(model, path)


def main():
    global SPATIAL
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--size", type=int, default=512)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    assert args.size in (256, 512), "Supported network sizes: 256 or 512"
    SPATIAL = args.size // 8
    root = Path(__file__).parent / "models"
    model = torch.jit.load(str(root / "anime-manga-big-lama.pt"), map_location="cpu").eval()
    fourier = [unit for _, unit in model.named_modules() if unit.original_name == 'FourierUnit']
    assert len(fourier) == 36 and all(tuple(unit.conv_layer.weight.shape) == (384,384,1,1) for unit in fourier)
    if args.size != 512:
        model = torch.jit.script(ReducedResolution(model, args.size).eval())
    destination = args.output_dir or root
    destination.mkdir(parents=True, exist_ok=True)
    register()
    torch.manual_seed(7)
    image = torch.rand(1, 3, 512, 512)
    mask = torch.zeros(1, 1, 512, 512); mask[:, :, 128:256, 128:256] = 1
    output = destination / "anime_lama.onnx"
    torch.onnx.export(model, (image, mask), str(output), input_names=["image", "mask"],
        output_names=["output"], opset_version=17, dynamo=False)
    positive_gathers(output)
    import onnxruntime as ort
    with torch.no_grad(): expected = model(image, mask).numpy()
    for name, value in (("image", image.numpy()), ("mask", mask.numpy()), ("expected", expected)):
        value.astype("<f4").tofile(destination / ("anime-" + name + ".f32"))
    session = ort.InferenceSession(str(output), providers=["CPUExecutionProvider"])
    actual = session.run(None, {"image": image.numpy(), "mask": mask.numpy()})[0]
    np.testing.assert_allclose(actual, expected, atol=0.003, rtol=0.003)
    np.testing.assert_array_equal(actual * (1-mask.numpy()), image.numpy() * (1-mask.numpy()))
    print("Original weights / ONNX DFT comparison passed; max error", float(np.abs(actual - expected).max()), flush=True)


if __name__ == "__main__": main()
