"""Check model download validation without network access or native inference."""
import io
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).parent / "app/src/main/python"))
import model_finder


class DownloadTests(unittest.TestCase):
    def test_unbundled_small_model_is_downloadable(self):
        row = self.finder.listing()[0]
        self.assertFalse(row['downloaded'])
        self.assertFalse(row['active'])
        self.assertEqual(row['download_bytes'], 641191280)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.module = types.SimpleNamespace(_jobs={}, logging=types.SimpleNamespace(warning=lambda *args: None))
        self.selected = []
        self.bridge = types.SimpleNamespace(selectModel=self.selected.append)
        self.finder = model_finder.Finder(self.module, self.root, self.bridge)

    def tearDown(self):
        self.finder.worker.shutdown(wait=True)
        self.temp.cleanup()

    def archive(self, extra=None, backend="QnnHtp"):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as bundle:
            config = {"dialog": {"engine": {"backend": {"type": backend}, "model": {"binary": {"ctx-bins": ["part.bin"]}}}}}
            for name, content in {"genie_config.json": json.dumps(config), "part.bin": "weights", "tokenizer.json": "{}", **(extra or {})}.items():
                bundle.writestr("bundle/" + name, content)
        return buffer.getvalue()

    def run_download(self, data, expected=None):
        response = io.BytesIO(data)
        response.headers = {"Content-Length": str(len(data) if expected is None else expected)}
        row = ("qwen3_1_7b", "Test", 1.7, int(response.headers["Content-Length"]), "Test", "Test")
        with patch.object(model_finder, "CATALOG", (model_finder.CATALOG[0], row)), patch.object(model_finder.urllib.request, "urlopen", return_value=response):
            self.finder._download("qwen3_1_7b")
        return self.finder.states["qwen3_1_7b"]

    def test_valid_archive_and_selection(self):
        self.assertEqual(self.run_download(self.archive())["status"], "downloaded")
        self.finder.select("qwen3_1_7b")
        self.assertEqual(self.finder.active, "qwen3_1_7b")
        self.assertEqual(len(self.selected), 1)
        self.assertEqual(json.loads(self.finder.settings.read_text())["active"], self.finder.active)
        restored = model_finder.Finder(self.module, self.root, self.bridge)
        self.assertEqual(restored.active, "qwen3_1_7b")
        self.assertEqual(self.module._current_qwen_repo_id, "Qualcomm/Qwen3-1.7B")
        restored.worker.shutdown(wait=True)

    def test_traversal_rejected_and_partial_files_removed(self):
        self.assertEqual(self.run_download(self.archive({"../../escape.json": "bad"}))["status"], "failed")
        self.assertFalse((self.root / "models/escape.json").exists())
        self.assertFalse(self.finder.directory("qwen3_1_7b").exists())
        self.assertFalse(list((self.root / "models/downloaded").glob("*.partial")))

    def test_incomplete_download_and_cpu_model_rejected(self):
        data = self.archive()
        self.assertEqual(self.run_download(data, len(data) + 1)["status"], "failed")
        self.assertEqual(self.run_download(self.archive(backend="CPU"))["status"], "failed")

    def test_switch_during_translation_rejected(self):
        self.run_download(self.archive())
        self.module._jobs["busy"] = {"status": "processing"}
        with self.assertRaises(ValueError):
            self.finder.select("qwen3_1_7b")
        self.assertEqual(self.finder.active, "qwen3_0_6b")
        self.assertFalse(self.selected)


if __name__ == "__main__":
    unittest.main()
