"""Keep private sample/config bytes off jq's process argument boundary."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ConfigPrivacy(unittest.TestCase):
    def test_panel_save_and_reload_keep_private_text_out_of_jq_argv(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            tools = base / "bin"
            tools.mkdir()
            trace = base / "jq-argv.jsonl"
            real_jq = shutil.which("jq")
            self.assertIsNotNone(real_jq)
            # Observe actual /proc argv before exec, then run the real parser.
            wrapper = tools / "jq"
            wrapper.write_text(
                "#!/usr/bin/python3\n"
                "import json, os, pathlib, sys\n"
                f"with open({str(trace)!r}, 'a') as log:\n"
                "    log.write(json.dumps(pathlib.Path('/proc/self/cmdline').read_bytes()"
                ".decode().split('\\0')) + '\\n')\n"
                f"os.execv({real_jq!r}, [{real_jq!r}, *sys.argv[1:]])\n"
            )
            wrapper.chmod(0o755)
            for name, code in (("secret-tool", 1), ("notify-send", 0)):
                tool = tools / name
                tool.write_text(f"#!/bin/sh\nexit {code}\n")
                tool.chmod(0o755)
            env = {k: v for k, v in os.environ.items()
                   if not k.startswith(("TTS_", "TERATTS_"))}
            env.update(PATH=str(tools) + os.pathsep + os.environ["PATH"],
                       HOME=str(base), XDG_CONFIG_HOME=str(base / "config"),
                       XDG_DATA_HOME=str(base / "data"), XDG_CACHE_HOME=str(base / "cache"),
                       XDG_STATE_HOME=str(base / "state"), XDG_RUNTIME_DIR=str(base / "run"))
            config = base / "config/omarchy-tts/config.json"

            def speak(*args, text=None):
                result = subprocess.run([str(ROOT / "bin/speak"), *args], input=text,
                                        env=env, capture_output=True, text=True, timeout=15)
                self.assertEqual(result.returncode, 0, result.stderr)
                return result

            speak("--info")
            saved = json.loads(config.read_text())
            extension = "PRIVATE_EXTENSION_11520"
            saved["privateExtension"] = {"note": extension}
            config.write_text(json.dumps(saved))
            sample_marker = "PRIVATE_SAMPLE_11520"
            samples = [sample_marker + ' Привет "quote" \\ path\n$(not-a-command) --option',
                       sample_marker + "x" * (4096 - len(sample_marker)), ""]
            for sample in samples:
                with self.subTest(length=len(sample)):
                    trace.write_text("")
                    speak("--set-stdin-json", ".ui.sampleText", text=json.dumps(sample) + "\n")
                    self.assertEqual(json.loads(config.read_text())["ui"]["sampleText"], sample)
                    save_calls = [json.loads(line) for line in trace.read_text().splitlines()]
                    self.assertTrue(save_calls)
                    trace.write_text("")
                    info = json.loads(speak("--info").stdout)
                    self.assertEqual(info["ui"]["sampleText"], sample)
                    self.assertFalse(info["ui"]["sampleIsDefault"])
                    self.assertEqual(json.loads(config.read_text())["privateExtension"]["note"], extension)
                    self.assertEqual(config.stat().st_mode & 0o777, 0o600)
                    load_calls = [json.loads(line) for line in trace.read_text().splitlines()]
                    self.assertTrue(load_calls)
                    for phase, calls in (("save", save_calls), ("reload", load_calls)):
                        with self.subTest(phase=phase):
                            argv = json.dumps(calls, ensure_ascii=False)
                            self.assertNotIn(sample_marker, argv)
                            self.assertNotIn(extension, argv)


if __name__ == "__main__":
    unittest.main()
