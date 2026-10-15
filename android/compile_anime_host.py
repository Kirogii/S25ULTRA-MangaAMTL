"""Compile HTP contexts on Windows x64; never runs inference on the host CPU."""
import argparse
import json
import os
from pathlib import Path
import platform
import sys

platform._wmi_query = lambda *args: (_ for _ in ()).throw(OSError('WMI unavailable'))
ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / 'tools/host-qnn-2.1.1'))
sys.path.insert(0, str(ROOT / 'tools/host-ort-1.24.4'))
import onnxruntime as ort
import onnxruntime_qnn as qnn


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model-dir', type=Path, default=ROOT / 'models/anime-256')
    parser.add_argument('--stage', type=int)
    parser.add_argument('--optimization', type=int, choices=(0, 1, 2, 3), default=1)
    args = parser.parse_args()
    sdk = (ROOT / 'tools/qairt-host-2.45').resolve()
    target = args.model_dir / ('host-contexts' if args.optimization == 1 else f'host-contexts-opt{args.optimization}')
    target.mkdir(exist_ok=True)
    dll_directory = os.add_dll_directory(str(sdk))
    ort.register_execution_provider_library(qnn.EP_NAME, qnn.get_library_path())
    devices = [device for device in ort.get_ep_devices() if device.ep_name == qnn.EP_NAME]
    assert devices, 'QNN compilation provider is unavailable'
    stages = json.loads((args.model_dir / 'anime/pipeline.json').read_text())
    try:
        for index, stage in enumerate(stages):
            if args.stage is not None and index != args.stage:
                continue
            output = (target / f'stage{index}.ctx.onnx').resolve()
            output.unlink(missing_ok=True)
            options = ort.SessionOptions()
            options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_BASIC
            for key, value in {'session.disable_cpu_ep_fallback': '1', 'ep.context_enable': '1',
                               'ep.context_embed_mode': '1', 'ep.context_file_path': str(output)}.items():
                options.add_session_config_entry(key, value)
            provider_options = {
                'backend_path': str(sdk / 'QnnHtp.dll'), 'soc_model': '69',
                'enable_htp_fp16_precision': '1', 'offload_graph_io_quantization': '0',
                'htp_graph_finalization_optimization_mode': str(args.optimization),
            }
            print(f'Compiling stage {index} on host', flush=True)
            options.add_provider_for_devices(devices, provider_options)
            session = ort.InferenceSession(str(args.model_dir / 'anime' / stage['file']), sess_options=options)
            del session
            assert output.is_file() and output.stat().st_size, output
            stage['file'] = output.name
            print(f'Compiled stage {index}: {output.stat().st_size} bytes', flush=True)
        if args.stage is None:
            (target / 'pipeline.json').write_text(json.dumps(stages, indent=2), encoding='utf-8')
    finally:
        ort.unregister_execution_provider_library(qnn.EP_NAME)
        dll_directory.close()


if __name__ == '__main__':
    main()
