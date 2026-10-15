"""Qualcomm Genie C API: QnnHtp only, with the bundle's compiled weights."""
import ctypes as c
import json
import os
from pathlib import Path
import re

P = c.c_void_p
OUT = c.POINTER(P)
TEXT = c.CFUNCTYPE(None, c.c_char_p, c.c_int, P)
ALLOC = c.CFUNCTYPE(None, c.c_size_t, c.POINTER(P))


class Translator:
    def __init__(self, directory, libraries):
        self.directory = Path(directory)
        os.environ['ADSP_LIBRARY_PATH'] = str(libraries) + ';/vendor/lib/rfsa/adsp;/vendor/dsp/cdsp'
        self.api = c.CDLL(str(Path(libraries) / 'libGenie.so'))
        signatures = {
            'DialogConfig_createFromJson': [c.c_char_p, OUT], 'DialogConfig_free': [P],
            'DialogConfig_bindProfiler': [P, P], 'Dialog_create': [P, OUT], 'Dialog_free': [P],
            'Dialog_reset': [P], 'Dialog_setMaxNumTokens': [P, c.c_uint32],
            'Dialog_query': [P, c.c_char_p, c.c_int, TEXT, P], 'Dialog_getSampler': [P, OUT],
            'SamplerConfig_createFromJson': [c.c_char_p, OUT], 'SamplerConfig_free': [P],
            'Sampler_applyConfig': [P, P],
            'Profile_create': [P, OUT], 'Profile_getJsonData': [P, ALLOC, c.POINTER(P)],
            'Profile_free': [P],
        }
        for name, arguments in signatures.items():
            function = getattr(self.api, 'Genie' + name)
            function.argtypes, function.restype = arguments, c.c_int
        self.dialog, self.profile = P(), P()
        config = json.loads((self.directory / 'genie_config.json').read_text())
        engine = config['dialog']['engine']
        if engine['backend']['type'] != 'QnnHtp':
            raise ValueError('Translation requires the Qualcomm NPU backend')
        engine['backend']['QnnHtp']['enable-graph-switching'] = True
        engine['backend']['extensions'] = str(self.directory / engine['backend']['extensions'])
        engine['model']['binary']['ctx-bins'] = [str(self.directory / name) for name in engine['model']['binary']['ctx-bins']]
        config['dialog']['tokenizer']['path'] = str(self.directory / 'tokenizer.json')
        handle = P()
        try:
            self.call('DialogConfig_createFromJson', json.dumps(config).encode(), c.byref(handle))
            self.call('Profile_create', None, c.byref(self.profile))
            self.call('DialogConfig_bindProfiler', handle, self.profile)
            self.call('Dialog_create', handle, c.byref(self.dialog))
        except Exception:
            self.close()
            raise
        finally:
            if handle:
                self.call('DialogConfig_free', handle)

    def call(self, name, *arguments):
        status = getattr(self.api, 'Genie' + name)(*arguments)
        if status != 0:
            raise RuntimeError('Qualcomm Genie ' + name + ' failed: ' + str(status))

    def generate(self, messages_json, max_tokens, temperature, top_p):
        self.call('Dialog_reset', self.dialog)
        self.call('Dialog_setMaxNumTokens', self.dialog, min(2048, max(1, max_tokens)))
        sampler, config = P(), P()
        try:
            self.call('Dialog_getSampler', self.dialog, c.byref(sampler))
            values = {'version': 1, 'seed': 42, 'temp': temperature, 'top-k': 40, 'top-p': top_p}
            self.call('SamplerConfig_createFromJson', json.dumps({'sampler': values}).encode(), c.byref(config))
            self.call('Sampler_applyConfig', sampler, config)
        finally:
            if config:
                self.call('SamplerConfig_free', config)
            # The sampler is borrowed from the dialog, which owns its lifetime.
        prompt = ''.join('<|im_start|>' + item['role'] + '\n' + item['content'] + '<|im_end|>\n'
                         for item in json.loads(messages_json))
        prompt += '<|im_start|>assistant\n<think>\n\n</think>\n\n'
        chunks = []
        @TEXT
        def receive(text, code, user):
            if text:
                chunks.append(text)
        self.call('Dialog_query', self.dialog, prompt.encode('utf-8'), 0, receive, None)
        output = re.sub(r'(?s)<think>.*?</think>', '', b''.join(chunks).decode('utf-8')).strip()
        if not output:
            raise RuntimeError('NPU returned no translation')
        buffers = []
        @ALLOC
        def allocate(size, result):
            buffer = c.create_string_buffer(size)
            buffers.append(buffer)
            result[0] = c.cast(buffer, P)
        profile = P()
        self.call('Profile_getJsonData', self.profile, allocate, c.byref(profile))
        (self.directory / 'genie-profile.json').write_bytes(c.string_at(profile))
        return output

    def close(self):
        if self.dialog:
            self.call('Dialog_free', self.dialog)
            self.dialog = P()
        if self.profile:
            self.call('Profile_free', self.profile)
            self.profile = P()
