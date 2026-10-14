"""Finite loopback checks for voice-health input before shell/JSON buffering."""
import http.server
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]
MAXIMUM = 2 * 1024 * 1024


class VoiceHealth(unittest.TestCase):
    def test_valid_malformed_chunked_and_oversize_bodies(self):
        rows = [
            (b'{"voices":["test_voice"]}', True, 200, True),
            (b'{"voices":["test_voice"]}', False, 200, True),
            (b'{not-json}', True, 200, False),
            (b'{"voices":["test_voice"]}', True, 503, False),
            (b'{"voices":["test_voice"],"padding":"' + b'x' * MAXIMUM + b'"}', True, 200, False),
            (b'{"voices":["test_voice"],"padding":"' + b'x' * MAXIMUM + b'"}', False, 200, False),
            (b'{"voices":["test_voice"]}' + b' ' * (MAXIMUM + 1), False, 200, False),
            (b'{"voices":["test_voice"]}', "chunked", 200, True),
            (b'{"voices":["test_voice"]}' + b' ' * (MAXIMUM + 1), "chunked", 200, False),
        ]
        for body, with_length, status, accept in rows:
            with self.subTest(with_length=with_length, status=status, bytes=len(body)):
                class Handler(http.server.BaseHTTPRequestHandler):
                    def log_message(self, *_):
                        pass

                    def do_GET(self):
                        self.server.calls += 1
                        self.send_response(status)
                        self.send_header("Content-Type", "application/json")
                        if with_length == "chunked":
                            self.send_header("Transfer-Encoding", "chunked")
                        elif with_length:
                            self.send_header("Content-Length", str(len(body)))
                        self.end_headers()
                        try:
                            if with_length == "chunked":
                                self.wfile.write(f"{len(body):x}\r\n".encode() + body + b"\r\n0\r\n\r\n")
                            else:
                                self.wfile.write(body)
                        except (BrokenPipeError, ConnectionResetError):
                            pass

                server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
                server.calls = 0
                worker = threading.Thread(target=server.serve_forever, daemon=True)
                worker.start()
                try:
                    with tempfile.TemporaryDirectory() as temporary:
                        config = Path(temporary) / "config.json"
                        config.write_text("{}")
                        env = {**os.environ, "TTS_PLUGIN_DIR": str(ROOT), "TTS_CONFIG": str(config),
                               "TERATTS_URL": f"http://127.0.0.1:{server.server_port}"}
                        result = subprocess.run([str(ROOT / "providers/teratts"), "--voices"],
                                                env=env, capture_output=True, text=True, timeout=5)
                        self.assertEqual(result.returncode, 0, result.stderr)
                        voices = json.loads(result.stdout)
                        self.assertEqual(any(v["value"] == "test_voice" for v in voices), accept)
                        if not accept:
                            self.assertTrue(any(v["value"] == "ru_f1" for v in voices))
                        self.assertLess(len(result.stdout.encode()), MAXIMUM)
                        self.assertEqual(server.calls, 1, "finite request, no retry")
                finally:
                    server.shutdown()
                    server.server_close()
                    worker.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
