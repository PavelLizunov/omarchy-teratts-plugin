"""Optional local OCR guard checks; no downloads, desktop or real models."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class LocalOcrGuards(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        (self.base / "lib").mkdir()
        (self.base / "lib/play.sh").write_bytes((ROOT / "lib/play.sh").read_bytes())
        (self.base / "lib/engines").mkdir()
        models = self.base / "models"
        models.mkdir()
        entries = {}
        for name in ("craft_mlt_25k.pth", "english_g2.pth"):
            data = b"inert model fixture"
            (models / name).write_bytes(data)
            entries[name] = {"sha256": hashlib.sha256(data).hexdigest()}
        (self.base / "lib/engines/models.json").write_text(json.dumps({"easyocr": {"models": entries}}))
        tools = self.base / "bin"
        tools.mkdir()
        self.marker = self.base / "reader-started"
        (tools / "notify-send").write_text("#!/bin/sh\nexit 0\n")
        (tools / "notify-send").chmod(0o755)
        (tools / "tesseract").write_text(
            f'#!/bin/sh\nif [ "$1" = "--list-langs" ]; then printf "Languages (1):\\neng\\n"; '
            f'else touch "{self.marker}"; echo "probe 123"; fi\n')
        (tools / "tesseract").chmod(0o755)
        (self.base / "easyocr.py").write_text(
            "from pathlib import Path\nimport os\nclass Reader:\n"
            " def __init__(self, langs, **kwargs):\n"
            "  if langs != ['en']: raise FileNotFoundError('unshipped recognition model')\n"
            " def readtext(self, *args, **kwargs):\n"
            "  return [([[0,0],[1,0],[1,1],[0,1]], 'probe 123', 1)]\n")
        self.env = dict(os.environ, PATH=str(tools) + os.pathsep + os.environ["PATH"],
                        TTS_PLUGIN_DIR=str(self.base), TTS_CONFIG=str(self.base / "config.json"),
                        XDG_RUNTIME_DIR=str(self.base), EASYOCR_PYTHON=sys.executable,
                        EASYOCR_MODELS=str(models), PYTHONPATH=str(self.base),
                        TTS_OCR_MINCONF="0")

    def call(self, engine, language):
        return subprocess.run([str(ROOT / "ocr" / engine)], input=b"inert image",
                              env=dict(self.env, TTS_OCR_LANGS=language),
                              capture_output=True, timeout=5)

    def test_missing_easyocr_model_is_a_language_gap_not_reader_failure(self):
        missing = self.call("easyocr", "rus")
        self.assertEqual(missing.returncode, 78, missing.stderr.decode())
        self.assertEqual(missing.stdout, b"")
        available = self.call("easyocr", "eng")
        self.assertEqual(available.returncode, 0, available.stderr.decode())
        self.assertIn(b"probe 123", available.stdout)

    def test_missing_easyocr_points_to_existing_setup_not_absent_tab(self):
        self.env["EASYOCR_PYTHON"] = str(self.base / "missing-python")
        missing = self.call("easyocr", "eng")
        self.assertEqual(missing.returncode, 127)
        self.assertIn(b"bin/speak-setup start easyocr", missing.stderr)
        self.assertNotIn(b"Screen tab", missing.stderr)
        self.assertFalse(self.marker.exists())

    def test_tesseract_language_names_are_literal_not_regex(self):
        missing = self.call("tesseract", "e.g")
        self.assertEqual(missing.returncode, 78, missing.stderr.decode())
        self.assertFalse(self.marker.exists())
        available = self.call("tesseract", "eng")
        self.assertEqual(available.returncode, 0, available.stderr.decode())
        self.assertTrue(self.marker.exists())


if __name__ == "__main__":
    unittest.main()
