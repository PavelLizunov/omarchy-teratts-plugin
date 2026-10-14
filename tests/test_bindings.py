"""Shortcut manager contracts with Omarchy's numeric Lua dispatcher IDs."""
from pathlib import Path
import json
import os
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "bin" / "speak-bindings"


class BindingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        fake_bin = base / "bin"
        fake_bin.mkdir()
        (fake_bin / "hyprctl").write_text(
            "#!/usr/bin/env python3\n"
            "import os, sys\n"
            "if sys.argv[1:] == ['binds', '-j']:\n"
            "    print(os.environ.get('FAKE_HYPR_BINDS', '[]'))\n"
            "elif sys.argv[1:] == ['reload']:\n"
            "    print('ok')\n"
        )
        (fake_bin / "hyprctl").chmod(0o755)
        self.env = os.environ.copy()
        self.env.update({
            "XDG_CONFIG_HOME": str(base / "config"),
            "HYPRLAND_INSTANCE_SIGNATURE": "test",
            "PATH": str(fake_bin) + os.pathsep + self.env.get("PATH", ""),
            "FAKE_HYPR_BINDS": "[]",
        })

    def call(self, *args):
        return subprocess.run([str(TOOL), *args], env=self.env,
                              capture_output=True, text=True)

    def test_exact_predecessor_managed_bindings_migrate_and_foreign_stays(self):
        self.assertEqual(self.call("install").returncode, 0)
        target = Path(self.env["XDG_CONFIG_HOME"]) / "hypr/bindings.lua"
        target.write_text(target.read_text().replace("io.github.pavellizunov.teratts", "io.github.hikari112.tts"))
        self.env["FAKE_HYPR_BINDS"] = json.dumps([
            {"modmask":72,"key":"E","description":"Читать выделение", "dispatcher":"__lua","arg":"1"}])
        result = self.call("install")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("io.github.hikari112.tts", target.read_text())
        foreign = 'o.bind("SUPER + ALT + E", "Other", "/usr/local/bin/speak --toggle")\n'
        target.write_text(foreign)
        before = target.read_bytes()
        result = self.call("install")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(target.read_bytes(), before)

    def test_managed_lua_bindings_are_not_self_conflicts(self):
        installed = self.call("install")
        self.assertEqual(installed.returncode, 0, installed.stderr)
        bindings_file = Path(self.env["XDG_CONFIG_HOME"]) / "hypr" / "bindings.lua"
        contents = bindings_file.read_text()
        self.assertEqual(contents.count("hl.unbind("), 7)
        self.assertIn("Читать область экрана", contents)
        english = self.call("--locale", "en", "install")
        self.assertEqual(english.returncode, 0, english.stderr)
        self.assertIn("Read screen area", bindings_file.read_text())

        labels = ("Read selection", "Read clipboard", "Stop speaking",
                  "Read screen area", "Read window", "Read monitor")
        active = [
            {"modmask": 72, "key": key, "description": label,
             "dispatcher": "__lua", "arg": str(i)}
            for i, (key, label) in enumerate(zip(("E", "A", "X", "R", "W"), labels), 1)
        ] + [{"modmask": 73, "key": "R", "description": labels[5],
              "dispatcher": "__lua", "arg": "6"}]
        self.env["FAKE_HYPR_BINDS"] = json.dumps(active)
        status = self.call("status")
        self.assertEqual(status.returncode, 0, status.stderr)
        self.assertEqual(json.loads(status.stdout)["conflicts"], [])

        self.env["FAKE_HYPR_BINDS"] = json.dumps(active + [active[0]])
        duplicate = self.call("status")
        self.assertEqual(duplicate.returncode, 0, duplicate.stderr)
        self.assertIn("SUPER + ALT + E", json.loads(duplicate.stdout)["conflicts"])

        foreign = [dict(active[0], description="Another action")] + active[1:]
        self.env["FAKE_HYPR_BINDS"] = json.dumps(foreign)
        wrong_label = self.call("status")
        self.assertIn("SUPER + ALT + E", json.loads(wrong_label.stdout)["conflicts"])

        self.env["FAKE_HYPR_BINDS"] = json.dumps(active)
        changed = self.call("set", "selection", "SUPER + ALT + Q")
        self.assertEqual(changed.returncode, 0, changed.stderr)
        self.assertIn('hl.unbind("SUPER + ALT + Q")', bindings_file.read_text())

    def test_old_choices_survive_new_actions_and_audio_conflict_is_refused(self):
        self.assertEqual(self.call("install").returncode, 0)
        self.assertEqual(self.call("set", "selection", "SUPER + ALT + Q").returncode, 0)
        config = Path(self.env["XDG_CONFIG_HOME"]) / "omarchy-tts/bindings.json"
        old = json.loads(config.read_text())
        old.pop("audio", None); old.pop("export", None); old.pop("pause", None)
        config.write_text(json.dumps(old))
        self.env["FAKE_HYPR_BINDS"] = json.dumps([
            {"modmask": 65, "key": "L", "description": "Another action", "dispatcher": "exec", "arg": "foreign"}])
        refused = self.call("install")
        self.assertNotEqual(refused.returncode, 0)
        self.assertEqual(json.loads(config.read_text()), old)
        self.env["FAKE_HYPR_BINDS"] = "[]"
        self.assertEqual(self.call("install").returncode, 0)
        current = json.loads(self.call("status").stdout)["bindings"]
        for key in old:
            self.assertEqual(current[key]["chord"], old[key]["chord"])
        self.assertEqual(current["export"]["chord"], "")
        self.assertEqual(current["pause"]["chord"], "")
        self.assertEqual(self.call("set", "audio", "").returncode, 0)
        self.assertEqual(json.loads(self.call("status").stdout)["bindings"]["audio"]["chord"], "")

    def test_manual_legacy_lua_adoption_and_duplicate_conflict(self):
        target = Path(self.env["XDG_CONFIG_HOME"]) / "hypr/bindings.lua"
        target.parent.mkdir(parents=True)
        self.env["HOME"] = str(Path(self.temp.name) / "nonstandard-home")
        executable = self.env["HOME"] + "/.local/bin/speak"
        for command in ("speak --toggle", executable + " --toggle"):
            with self.subTest(command=command):
                original = f'o.bind("SUPER + ALT + E", "Speak selection", "{command}")\n'
                target.write_text(original)
                live = {"modmask":72,"key":"E","description":"Speak selection", "dispatcher":"__lua","arg":"17"}
                self.env["FAKE_HYPR_BINDS"] = json.dumps([live, dict(live, arg="18")])
                refused = self.call("install")
                self.assertNotEqual(refused.returncode, 0)
                self.assertEqual(target.read_text(), original)
                self.env["FAKE_HYPR_BINDS"] = json.dumps([live])
                state = json.loads(self.call("status").stdout)
                self.assertEqual(state["adoptable"], ["SUPER + ALT + E"])
                self.assertTrue(state["canInstall"], state)
                installed = self.call("install")
                self.assertEqual(installed.returncode, 0, installed.stderr)
                self.assertNotIn(original.strip(), target.read_text())
                self.assertIn("omarchy-tts bindings", target.read_text())

    def test_unverified_live_bindings_remain_foreign(self):
        for binding in (
            {"modmask":72, "key":"E", "dispatcher":"__lua", "arg":"17"},
            {"modmask":72, "key":"E", "dispatcher":"exec", "arg":"speak --toggle"},
        ):
            with self.subTest(binding=binding):
                self.env["FAKE_HYPR_BINDS"] = json.dumps([binding])
                state = json.loads(self.call("status").stdout)
                self.assertIn("SUPER + ALT + E", state["conflicts"])
                self.assertFalse(state["canInstall"])


if __name__ == "__main__":
    unittest.main()
