"""Fresh public profiles stay local until an owner configures a compatible server."""
import http.server
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest

from test_teratts import MockTeraHandler

ROOT = Path(__file__).resolve().parents[1]


class PublicSetup(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        tools = self.base / "bin"
        tools.mkdir()
        self.network = self.base / "network"
        (tools / "curl").write_text('#!/bin/sh\nprintf invoked >> "$NETWORK_CAPTURE"\nexit 99\n')
        (tools / "secret-tool").write_text('#!/bin/sh\nexit 1\n')
        (tools / "notify-send").write_text('#!/bin/sh\nexit 0\n')
        for tool in tools.iterdir():
            tool.chmod(0o755)
        self.env = {k: v for k, v in os.environ.items() if not k.startswith(("TERATTS_", "TTS_"))}
        self.env.update(PATH=str(tools) + os.pathsep + os.environ["PATH"],
                        XDG_CONFIG_HOME=str(self.base / "config"),
                        XDG_DATA_HOME=str(self.base / "data"),
                        XDG_CACHE_HOME=str(self.base / "cache"),
                        XDG_STATE_HOME=str(self.base / "state"),
                        XDG_RUNTIME_DIR=str(self.base / "runtime"),
                        NETWORK_CAPTURE=str(self.network))
        self.config = self.base / "config/omarchy-tts/config.json"

    def speak(self, *args):
        return subprocess.run([str(ROOT / "bin/speak"), *args], env=self.env,
                              text=True, capture_output=True, timeout=8)

    def test_unconfigured_profile_does_not_probe_or_synthesize_to_any_server(self):
        info = self.speak("--info")
        self.assertEqual(info.returncode, 0, info.stderr)
        self.assertEqual(json.loads(info.stdout)["endpoint"], "")
        self.assertEqual(json.loads(self.config.read_text())["teratts"]["endpoint"], "")
        result = self.speak("--raw", "A setup test.")
        self.assertEqual(result.returncode, 65, result.stderr)
        self.assertFalse(self.network.exists(), "No health request before configuration")

    def test_missing_library_endpoint_is_rejected_before_network(self):
        import sys
        sys.path.insert(0, str(ROOT / "lib"))
        from teratts_synthesis import Settings, SynthesisError
        from unittest.mock import patch
        clean = {k: v for k, v in self.env.items() if not k.startswith("TERATTS_")}
        with patch.dict(os.environ, clean, clear=True):
            with self.assertRaises(SynthesisError):
                Settings.from_env()

    def test_user_endpoints_and_export_route_are_preserved_and_independent(self):
        servers = []
        for _ in range(2):
            server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), MockTeraHandler)
            server.requests = []
            server.expected_token = "fixture-user-token"
            server.fail_with_code = None
            threading.Thread(target=server.serve_forever, daemon=True).start()
            self.addCleanup(server.server_close)
            self.addCleanup(server.shutdown)
            servers.append(server)
        self.env["TERATTS_BEARER_TOKEN"] = "fixture-user-token"
        for index, server in enumerate(servers):
            endpoint = f"http://127.0.0.1:{server.server_port}"
            result = self.speak("--set", ".teratts.endpoint", endpoint)
            self.assertEqual(result.returncode, 0, result.stderr)
            info = self.speak("--info")
            self.assertEqual(json.loads(info.stdout)["endpoint"], endpoint)
            self.assertEqual(json.loads(self.config.read_text())["teratts"]["endpoint"], endpoint)
            output = self.speak("--export-wav", "--raw", f"Server {index + 1} test.")
            self.assertEqual(output.returncode, 0, output.stderr)
            self.assertTrue(json.loads(output.stdout)["filename"].endswith(".wav"))
            self.assertEqual(len(server.requests), 1)
            self.assertEqual(server.requests[0]["headers"]["Authorization"], "Bearer fixture-user-token")
            self.assertEqual(len(servers[0].requests), 1)


if __name__ == "__main__":
    unittest.main()
