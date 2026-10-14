"""Contract tests for the dedicated multipart OCR endpoint."""
from email import policy
from email.parser import BytesParser
import http.server
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEAK = ROOT / "bin/speak"
OCR = ROOT / "ocr/remote"
PROBE = (ROOT / "lib/ocr-probe.png").read_bytes()


class OcrHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def reply(self, status, payload):
        raw = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path == "/healthz":
            self.server.health_reads += 1
            self.reply(200, {"status": "ok", "ocr": "ready" if self.server.health_ready else "down"})
        else:
            self.reply(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/v1/ocr":
            self.reply(404, {"error": "not found"})
            return
        body = self.rfile.read(int(self.headers["Content-Length"]))
        message = BytesParser(policy=policy.default).parsebytes(
            b"MIME-Version: 1.0\r\nContent-Type: "
            + self.headers["Content-Type"].encode() + b"\r\n\r\n" + body
        )
        self.server.requests.append([
            (part.get_param("name", header="content-disposition"),
             part.get_content_type(), part.get_payload(decode=True))
            for part in message.iter_parts()
        ])
        failure = self.server.failure
        if failure == "http":
            self.reply(503, {"error": "unavailable"})
        elif failure == "missing":
            self.reply(200, {"lines": ["Probe 123"], "latency_ms": 53.6})
        elif failure == "wrong_type":
            self.reply(200, {"text": ["Probe 123"]})
        elif failure == "malformed":
            raw = b"{broken"
            self.send_response(200)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
        else:
            self.reply(200, {"text": "Probe 123", "lines": ["Probe 123"], "latency_ms": 53.6})


class RemoteOcrTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), OcrHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        runtime = base / "runtime"
        runtime.mkdir()
        self.config = base / "config/omarchy-tts/config.json"
        self.env = {
            **os.environ,
            "XDG_CONFIG_HOME": str(base / "config"),
            "XDG_CACHE_HOME": str(base / "cache"),
            "XDG_DATA_HOME": str(base / "data"),
            "XDG_RUNTIME_DIR": str(runtime),
            "TTS_PLUGIN_DIR": str(ROOT),
            "TTS_CONFIG": str(self.config),
            "TTS_DATA_DIR": str(base / "data/omarchy-tts"),
        }
        self.server.requests = []
        self.server.health_reads = 0
        self.server.health_ready = True
        self.server.failure = ""

    def speak(self, *args):
        return subprocess.run([SPEAK, *args], env=self.env, capture_output=True, text=True)

    def remote(self, *args, image=PROBE, env=None):
        return subprocess.run([OCR, *args], input=image, env=env or self.env, capture_output=True)

    def configure(self):
        self.assertEqual(self.speak("--info").returncode, 0)
        address = f"http://127.0.0.1:{self.server.server_port}"
        result = self.speak("--set", ".ocr.remote.endpoint", address)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_multipart_recognition_without_model_selection(self):
        self.configure()
        info = json.loads(self.speak("--info").stdout)
        self.assertEqual(info["endpoint"], "")
        self.assertEqual(info["ocr"]["remoteEndpoint"], f"http://127.0.0.1:{self.server.server_port}")
        self.assertIsNone(info["ocr"]["model"])
        self.assertNotIn("models", info["ocr"])
        self.assertNotIn("model", json.loads(self.config.read_text())["ocr"]["remote"])

        result = self.remote()
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        self.assertEqual(result.stdout.decode().strip(), "Probe 123")
        self.assertEqual(self.server.requests, [[("file", "image/png", PROBE)]])
        self.assertEqual(self.server.health_reads, 0)

        self.assertEqual(self.speak("--set", ".ocr.engine", "remote").returncode, 0)
        verified = self.speak("--verify-ocr", "remote")
        self.assertEqual(verified.returncode, 0, verified.stderr)
        status = json.loads(self.speak("--info").stdout)
        engine = next(item for item in status["ocr"]["engines"] if item["name"] == "remote")
        self.assertEqual(engine["status"], "ready")

    def test_health_endpoint_and_config_migration(self):
        self.configure()
        config = json.loads(self.config.read_text())
        config["ocr"]["remote"]["model"] = "/old/chat-model.gguf"
        self.config.write_text(json.dumps(config))
        self.speak("--info")
        self.assertNotIn("model", json.loads(self.config.read_text())["ocr"]["remote"])

        healthy = self.remote("--health")
        self.assertEqual(healthy.returncode, 0)
        self.assertEqual(healthy.stdout, b"ready\n")
        self.assertEqual(self.server.requests, [])
        self.server.health_ready = False
        self.assertNotEqual(self.remote("--health").returncode, 0)

        changed = self.speak("--set", ".ocr.remote.endpoint", "http://127.0.0.1:1")
        self.assertEqual(changed.returncode, 0, changed.stderr)
        self.assertNotEqual(self.remote("--health").returncode, 0)
        bad = self.speak("--set", ".ocr.remote.endpoint", "http://example.com")
        self.assertNotEqual(bad.returncode, 0)

    def test_http_and_invalid_json_responses_fail_without_text(self):
        self.configure()
        for failure in ("http", "missing", "wrong_type", "malformed"):
            with self.subTest(failure=failure):
                self.server.failure = failure
                result = self.remote()
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, b"")

    def test_unsupported_image_and_old_model_command_are_rejected(self):
        self.configure()
        image_env = {**self.env, "TTS_OCR_IMAGE_MIME": "image/webp"}
        self.assertNotEqual(self.remote(env=image_env).returncode, 0)
        self.assertNotEqual(self.remote("--models").returncode, 0)
        self.assertNotEqual(self.speak("--set", ".ocr.remote.model", "unused").returncode, 0)
        self.assertEqual(self.server.requests, [])


if __name__ == "__main__":
    unittest.main()
