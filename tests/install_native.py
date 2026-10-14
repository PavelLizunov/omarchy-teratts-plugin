"""Public package contract and native installer boundaries in a disposable HOME."""
from pathlib import Path
import importlib.util
import json
import os
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class Package(unittest.TestCase):
    def test_public_files_and_detector_controls(self):
        path = ROOT / "tools/check-publication.py"
        spec = importlib.util.spec_from_file_location("publication", path)
        check = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(check)
        check.selftest()
        self.assertEqual(check.main(), 0)

    @unittest.skipUnless(Path("/usr/share/omarchy/bin/omarchy-plugin-add").is_file(),
                         "Native Omarchy installer is not present")
    def test_native_add_remove_preserves_settings_and_exports(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            source = home / "source"
            source.mkdir()
            tracked = subprocess.check_output(["git", "-C", str(ROOT), "ls-files"], text=True).splitlines()
            self.assertTrue(tracked, "Run against a prepared/staged source checkout")
            for name in tracked:
                target = source / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(ROOT / name, target)
            subprocess.run(["git", "-C", str(source), "init", "-q", "-b", "main"], check=True)
            subprocess.run(["git", "-C", str(source), "add", "--", *tracked], check=True)
            subprocess.run(["git", "-C", str(source), "-c", "user.name=Fixture", "-c",
                            "user.email=fixture@example.test", "commit", "-qm", "Fixture package"], check=True)
            tools = home / "bin"
            tools.mkdir()
            scripts = {
                "omarchy-shell": '#!/bin/sh\nif [ "$2" = listPlugins ]; then printf "[]\\n"; else printf "%s\\n" "$*" >> "$IPC_LOG"; fi\n',
                "omarchy-plugin-catalog": '#!/bin/sh\nprintf "[]\\n"\n',
            }
            for name, content in scripts.items():
                (tools / name).write_text(content)
                (tools / name).chmod(0o755)
            env = {**os.environ, "HOME":str(home), "PATH":str(tools)+os.pathsep+
                   "/usr/share/omarchy/bin"+os.pathsep+os.environ["PATH"], "IPC_LOG":str(home/"ipc")}
            config = home / ".config/omarchy-tts/config.json"
            recording = home / ".local/share/omarchy-teratts/exports/keep.wav"
            config.parent.mkdir(parents=True)
            recording.parent.mkdir(parents=True)
            config.write_bytes(b'{"teratts":{"endpoint":"https://user.example.test"}}')
            recording.write_bytes(b"fixture recording")
            binding = home / ".config/hypr/bindings.lua"
            binding.parent.mkdir(parents=True)
            binding.write_bytes(b"-- user bindings stay\n")
            before = [p.read_bytes() for p in [config, recording, binding]]
            add = subprocess.run(["/usr/share/omarchy/bin/omarchy-plugin-add", str(source), "--yes"],
                                 env=env, text=True, capture_output=True, timeout=15)
            self.assertEqual(add.returncode, 0, add.stdout + add.stderr)
            installed = home / ".config/omarchy/plugins/io.github.pavellizunov.teratts"
            self.assertTrue((installed / "manifest.json").is_file())
            self.assertEqual(json.loads((installed / "manifest.json").read_text())["version"], "0.3.17")
            self.assertEqual([p.read_bytes() for p in [config, recording, binding]], before)
            remove = subprocess.run(["/usr/share/omarchy/bin/omarchy-plugin-remove",
                                     "io.github.pavellizunov.teratts", "--yes"], env=env,
                                    text=True, capture_output=True, timeout=10)
            self.assertEqual(remove.returncode, 0, remove.stdout + remove.stderr)
            self.assertFalse(installed.exists())
            self.assertEqual([p.read_bytes() for p in [config, recording, binding]], before)


if __name__ == "__main__":
    unittest.main()
