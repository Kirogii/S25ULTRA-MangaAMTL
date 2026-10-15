"""Partition the verified graph without changing weights or tensor arithmetic."""
import json
import argparse
import platform
platform._wmi_query = lambda *args: (_ for _ in ()).throw(OSError("WMI unavailable"))
from pathlib import Path
import numpy as np
import onnx
from onnx import helper, TensorProto
import onnxruntime as ort

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model-dir', type=Path, default=Path(__file__).parent / 'models')
    parser.add_argument('--size', type=int, choices=(256, 512), default=512)
    parser.add_argument('--group-size', type=int, choices=(1, 2, 3, 6), default=1)
    args = parser.parse_args()
    root = args.model_dir
    model = onnx.load(root / 'anime_lama.onnx')
    all_outputs = [name for node in model.graph.node for name in node.output]
    cuts = []
    def add_cut(suffixes, shapes):
        names = []
        for suffix, shape in zip(suffixes, shapes):
            matches = [name for name in all_outputs if name.endswith(suffix)]
            assert len(matches) == 1, (suffix, matches)
            name = matches[0]
            names.append(name)
            model.graph.value_info.append(helper.make_tensor_value_info(name, TensorProto.FLOAT, shape))
        cuts.append(names)

    for block, channels in ((1, 64), (2, 128), (3, 256)):
        add_cut([f'/generator/model/{block}/act_l/Relu_output_0'],
                [[1, channels, args.size//(2**(block-1)), args.size//(2**(block-1))]])
    for block in range(4, 23):
        if block != 4 and (block-4) % args.group_size:
            continue
        suffixes = ([f'/generator/model/4/act_{branch}/Relu_output_0' for branch in ('l', 'g')] if block == 4
                 else [f'/generator/model/{block}/Add{suffix}_output_0' for suffix in ('', '_1')])
        add_cut(suffixes, [[1, channels, args.size//8, args.size//8] for channels in (128, 384)])
    for suffix, channels, divisor in (('26/Relu_output_0', 256, 4), ('Relu_output_0', 128, 2),
                                      ('Relu_1_output_0', 64, 1), ('35/Sigmoid_output_0', 3, 1)):
        add_cut(['/generator/model/' + suffix], [[1, channels, args.size//divisor, args.size//divisor]])
    extractor = onnx.utils.Extractor(model)
    stages = []
    folder = root / 'anime'
    folder.mkdir(exist_ok=True)
    for index in range(len(cuts) + 1):
        inputs = ['image', 'mask'] if index == 0 else cuts[index-1].copy()
        if index == len(cuts): inputs += ['image', 'mask']
        outputs = cuts[index] if index < len(cuts) else ['output']
        stage = extractor.extract_model(inputs, outputs)
        onnx.checker.check_model(stage)
        filename = f'stage{index}.onnx'
        onnx.save(stage, folder / filename)
        stages.append(dict(file=filename, inputs=inputs, outputs=outputs))
    (folder / 'pipeline.json').write_text(json.dumps(stages, indent=2), encoding='utf-8')
    values = {'image': np.fromfile(root / 'anime-image.f32', dtype='<f4').reshape(1,3,512,512),
              'mask': np.fromfile(root / 'anime-mask.f32', dtype='<f4').reshape(1,1,512,512)}
    for index, stage in enumerate(stages):
        session = ort.InferenceSession(str(folder / stage['file']), providers=['CPUExecutionProvider'])
        output = session.run(stage['outputs'], {name: values[name] for name in stage['inputs']})
        for number, array in enumerate(output): array.astype('<f4').tofile(root / f'anime-reference-stage{index}-{number}.f32')
        values.update(zip(stage['outputs'], output))
        needed = {'output'} | {name for future in stages[index+1:] for name in future['inputs']}
        values = {name: value for name, value in values.items() if name in needed}
        del session
    expected = np.fromfile(root / 'anime-expected.f32', dtype='<f4').reshape(1,3,512,512)
    np.testing.assert_allclose(values['output'], expected, atol=.003, rtol=.003)
    print('Partitioned original model verified:', float(np.abs(values['output']-expected).max()))

if __name__ == '__main__': main()
