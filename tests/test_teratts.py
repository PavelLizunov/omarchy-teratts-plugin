#!/usr/bin/env python3
import http.server
import json
import os
import shutil
import struct
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPEAK = str(ROOT / "bin" / "speak")
SETUP = str(ROOT / "bin" / "speak-setup")
TERATTS_PROVIDER = str(ROOT / "providers" / "teratts")

def make_dummy_wav(duration_frames=100, sample_rate=44100):
    # 44-byte standard RIFF/WAVE header followed by 16-bit mono PCM silence
    pcm_bytes = b"\x00\x00" * duration_frames
    data_size = len(pcm_bytes)
    riff_size = data_size + 36
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        riff_size,
        b"WAVE",
        b"fmt ",
        16,  # PCM format chunk size
        1,   # AudioFormat: 1 (PCM)
        1,   # NumChannels: 1 (mono)
        sample_rate,
        sample_rate * 2,  # ByteRate
        2,   # BlockAlign
        16,  # BitsPerSample
        b"data",
        data_size,
    )
    return header + pcm_bytes

class MockTeraHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def do_GET(self):
        if self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            resp = {
                "status": "ready",
                "app_git_sha": "6432ad33a423703e6bf9059b69f8787315decfce",
                "sample_rate": 44100,
                "voices": ["ru_f1", "ru_f2", "ru_m1", "eng_f3"],
                "queue": {"active": 0, "waiting": 0, "capacity": 15}
            }
            self.wfile.write(json.dumps(resp).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path == "/tts":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            payload = json.loads(body.decode("utf-8"))
            self.server.requests.append({
                "headers": dict(self.headers),
                "payload": payload,
            })
            if self.server.fail_with_code:
                self.send_response(self.server.fail_with_code)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": "simulated failure"}).encode("utf-8"))
                return

            auth = self.headers.get("Authorization", "")
            if self.server.expected_token and auth != f"Bearer {self.server.expected_token}":
                self.send_response(401)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": "unauthorized"}).encode("utf-8"))
                return

            self.send_response(200)
            self.send_header("Content-Type", "audio/wav")
            self.end_headers()
            self.wfile.write(make_dummy_wav(duration_frames=200))
        else:
            self.send_response(404)
            self.end_headers()

class TeraTTSProviderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), MockTeraHandler)
        cls.port = cls.server.server_port
        cls.server.requests = []
        cls.server.expected_token = "secret-token-123"
        cls.server.fail_with_code = None
        cls.server_thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.server_thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.config_dir = Path(self.temp_dir.name, "config", "omarchy-tts")
        self.config_dir.mkdir(parents=True)
        self.data_dir = Path(self.temp_dir.name, "data", "omarchy-tts")
        self.data_dir.mkdir(parents=True)
        self.cache_dir = Path(self.temp_dir.name, "cache", "omarchy-tts")
        self.cache_dir.mkdir(parents=True)
        self.run_dir = Path(self.temp_dir.name, "run")
        self.run_dir.mkdir(parents=True)

        self.server.requests.clear()
        self.server.fail_with_code = None
        self.server.expected_token = "secret-token-123"

        self.tools = Path(self.temp_dir.name, "bin")
        self.tools.mkdir(parents=True)
        secret_tool = self.tools / "secret-tool"
        secret_tool.write_text("#!/usr/bin/env bash\ncase ${1:-} in\n  lookup) exit 1 ;;\n  store|clear) cat >/dev/null; exit 0 ;;\nesac\nexit 0\n")
        secret_tool.chmod(0o755)

        (self.tools / "notify-send").write_text("#!/bin/sh\nexit 0\n")
        (self.tools / "notify-send").chmod(0o755)
        self.env = {
            **os.environ,
            "PATH": f"{self.tools}:{os.environ['PATH']}",
            "XDG_CONFIG_HOME": str(Path(self.temp_dir.name, "config")),
            "XDG_DATA_HOME": str(Path(self.temp_dir.name, "data")),
            "XDG_CACHE_HOME": str(Path(self.temp_dir.name, "cache")),
            "XDG_RUNTIME_DIR": str(self.run_dir),
            "TERATTS_URL": f"http://127.0.0.1:{self.port}",
            "TERATTS_BEARER_TOKEN": "secret-token-123",
            "TTS_PLUGIN_DIR": str(ROOT),
            "TTS_CONFIG": str(self.config_dir / "config.json"),
            "TTS_DATA_DIR": str(self.data_dir),
            "TTS_SILENT": "1",
        }

    def test_voices_parses_remote_health_endpoint(self):
        res = subprocess.run([TERATTS_PROVIDER, "--voices"], env=self.env, capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, res.stderr)
        voices = json.loads(res.stdout)
        self.assertIsInstance(voices, list)
        self.assertEqual(len(voices), 4)
        ru_f1 = next(v for v in voices if v["value"] == "ru_f1")
        self.assertEqual(ru_f1["label"], "Russian Female 1")
        self.assertEqual(ru_f1["language"], "ru")
        eng_f3 = next(v for v in voices if v["value"] == "eng_f3")
        self.assertEqual(eng_f3["language"], "en")

    def test_voices_fallback_when_server_offline(self):
        env = {**self.env, "TERATTS_URL": "http://127.0.0.1:1"}  # non-existent port
        res = subprocess.run([TERATTS_PROVIDER, "--voices"], env=env, capture_output=True, text=True)
        self.assertEqual(res.returncode, 0)
        voices = json.loads(res.stdout)
        self.assertTrue(len(voices) >= 10)
        self.assertTrue(any(v["value"] == "ru_f1" for v in voices))

    def test_single_chunk_synthesis_and_payload_structure(self):
        text = "Тестовое предложение для проверки синтеза."
        res = subprocess.run([TERATTS_PROVIDER], input=text, env=self.env, capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(len(self.server.requests), 1)
        req = self.server.requests[0]
        self.assertEqual(req["headers"].get("Authorization"), "Bearer secret-token-123")
        self.assertEqual(req["payload"]["text"], text)
        self.assertEqual(req["payload"]["voice"], "ru_f1")
        self.assertEqual(req["payload"]["language"], "ru")
        self.assertEqual(req["payload"]["duration_scale"], 1.0)
        self.assertEqual(req["payload"]["text_mode"], "russian_only")
        self.assertTrue(req["payload"]["speech_front"])

    def test_rate_duration_scale_inversion(self):
        # Rate 1.5x should yield duration_scale = 1.0 / 1.5 = 0.6667
        env = {**self.env, "TTS_RATE": "1.5"}
        res = subprocess.run([TERATTS_PROVIDER], input="Проверка скорости.", env=env, capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(len(self.server.requests), 1)
        scale = self.server.requests[0]["payload"]["duration_scale"]
        self.assertAlmostEqual(scale, 1.0 / 1.5, places=3)

        # Rate 0.5x should yield duration_scale = 2.0
        self.server.requests.clear()
        env["TTS_RATE"] = "0.5"
        res = subprocess.run([TERATTS_PROVIDER], input="Проверка замедления.", env=env, capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, res.stderr)
        scale = self.server.requests[0]["payload"]["duration_scale"]
        self.assertAlmostEqual(scale, 2.0, places=3)

    def test_chunking_long_text_across_sentence_boundaries(self):
        sentences = [
            f"Предложение номер {i} содержит полезную информацию о работе кластера и сервисов."
            for i in range(40)
        ]
        full_text = " ".join(sentences)
        self.assertGreater(len(full_text), 2500)

        res = subprocess.run([TERATTS_PROVIDER], input=full_text, env=self.env, capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertGreater(len(self.server.requests), 1)

        # Leave room for pronunciation expansion under the audio-duration limit.
        for req in self.server.requests:
            chunk_text = req["payload"]["text"]
            self.assertLessEqual(len(chunk_text), 480)
            self.assertTrue(len(chunk_text.strip()) > 0)

        # Reconstructed text contains all sentences
        all_received = " ".join(r["payload"]["text"] for r in self.server.requests)
        for s in sentences:
            self.assertIn(s, all_received)

    def test_oversized_token_is_rejected_instead_of_severed(self):
        giant_token = "A" * 5000
        res = subprocess.run([TERATTS_PROVIDER], input=giant_token, env=self.env, capture_output=True, text=True)
        self.assertEqual(res.returncode, 65, res.stderr)
        self.assertIn("word exceeds", res.stderr)
        self.assertEqual(len(self.server.requests), 0)

    def test_sentence_longer_than_first_fragment_keeps_words_intact(self):
        text = " ".join(["Это длинное предложение для проверки слова"] * 14) + "."
        result = subprocess.run([TERATTS_PROVIDER], input=text, env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        received = " ".join(request["payload"]["text"] for request in self.server.requests)
        self.assertEqual(received, text)
        self.assertTrue(all(len(request["payload"]["text"]) <= 480 for request in self.server.requests))

    def test_nearby_sentence_boundary_is_preferred_over_mid_sentence_cut(self):
        text = "Это начало " + "очень длинного предложения " * 9 + "конец. Следующее предложение."
        result = subprocess.run([TERATTS_PROVIDER], input=text, env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertGreater(len(self.server.requests), 1)
        self.assertTrue(self.server.requests[0]["payload"]["text"].endswith("конец."))

    def test_single_word_larger_than_first_fragment_stays_whole(self):
        word = "слово" * 80
        result = subprocess.run([TERATTS_PROVIDER], input=word, env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([request["payload"]["text"] for request in self.server.requests], [word])

    def test_long_first_word_in_long_input_preserves_all_text(self):
        text = "A" * 400 + " rest" * 450
        result = subprocess.run([TERATTS_PROVIDER], input=text, env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(" ".join(request["payload"]["text"] for request in self.server.requests), text)

    def test_english_voice_uses_compatible_text_mode(self):
        env = {**self.env, "TTS_VOICE": "eng_f3"}
        res = subprocess.run([TERATTS_PROVIDER], input="Hello world.", env=env, capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(self.server.requests[0]["payload"]["text_mode"], "compatible")
        self.assertEqual(self.server.requests[0]["payload"]["language"], "en")

    def test_mixed_script_advertisement_reaches_server_as_whole_words(self):
        text = ('Приветcтвую. Нa продажу Аррlе MаcВoоk Pro М1, Sрace Gray, '
                'бeз кoмплeкта/без заpядки. Bнeшнe cocтояние хoрoшеe, '
                'нeзнaчитeльныe cколы/пoтёpтoсти, ApplеID и Локaтоp.')
        expected = ('Приветствую. На продажу Apple MacBook Pro М1, Space Gray, '
                    'без комплекта/без зарядки. Внешне состояние хорошее, '
                    'незначительные сколы/потёртости, AppleID и Локатор.')
        result = subprocess.run([TERATTS_PROVIDER], input=text, env=self.env,
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(" ".join(r["payload"]["text"] for r in self.server.requests), expected)

    def test_mixed_script_repair_preserves_explicit_english_and_unconvertible_words(self):
        text = 'Apple MacBook Привет <EN>Аррlе Нa</EN> iPhoneПривет naïvе 16/512.'
        expected = text.replace('<EN>', '<en>').replace('</EN>', '</en>')
        result = subprocess.run([TERATTS_PROVIDER], input=text, env=self.env,
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.server.requests[0]["payload"]["text"], expected)

    def test_english_voice_does_not_repair_mixed_script_words(self):
        text = 'Аррlе Нa Приветcтвую.'
        result = subprocess.run([TERATTS_PROVIDER], input=text,
                                env={**self.env, "TTS_VOICE": "eng_f3"},
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.server.requests[0]["payload"]["text"], text)

    def test_compatible_mode_does_not_repair_mixed_script_words(self):
        (self.config_dir / "config.json").write_text(json.dumps({"teratts": {"text_mode": "compatible"}}))
        text = 'Аррlе Нa Приветcтвую.'
        result = subprocess.run([TERATTS_PROVIDER], input=text, env=self.env,
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.server.requests[0]["payload"]["text"], text)

    def test_html_tags_and_control_chars_are_sanitized(self):
        messy_input = "<br>Привет!\r\nТекст с <hr>тегами <li>списка</li> и \x00нулевым байтом. List<T>."
        res = subprocess.run([TERATTS_PROVIDER], input=messy_input, env=self.env, capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, res.stderr)
        sent_text = self.server.requests[0]["payload"]["text"]
        self.assertNotIn("<br>", sent_text)
        self.assertNotIn("<li>", sent_text)
        self.assertNotIn("\r", sent_text)
        self.assertNotIn("\x00", sent_text)
        self.assertIn("Привет!", sent_text)
        self.assertIn("T", sent_text)

    def test_pure_emoji_or_whitespace_exits_cleanly_without_requests(self):
        res = subprocess.run([TERATTS_PROVIDER], input="🎉🚀🎈   ", env=self.env, capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(len(self.server.requests), 0)

    def test_unauthorized_error_returns_exit_77(self):
        env = {**self.env, "TERATTS_BEARER_TOKEN": "wrong-token"}
        res = subprocess.run([TERATTS_PROVIDER], input="Привет", env=env, capture_output=True, text=True)
        self.assertEqual(res.returncode, 77)
        self.assertIn("HTTP 401", res.stderr)

    def test_server_failure_returns_exit_74(self):
        self.server.fail_with_code = 500
        res = subprocess.run([TERATTS_PROVIDER], input="Привет", env=self.env, capture_output=True, text=True)
        self.assertEqual(res.returncode, 74)
        self.assertIn("HTTP 500", res.stderr)

    def test_server_offline_returns_exit_74(self):
        env = {**self.env, "TERATTS_URL": "http://127.0.0.1:1"}
        res = subprocess.run([TERATTS_PROVIDER], input="Привет", env=env, capture_output=True, text=True)
        self.assertEqual(res.returncode, 74)
        self.assertIn("network error", res.stderr)

    def test_untrusted_endpoint_is_rejected_before_network(self):
        env = {**self.env, "TERATTS_URL": "http://example.com"}
        res = subprocess.run([TERATTS_PROVIDER], input="Привет", env=env, capture_output=True, text=True)
        self.assertEqual(res.returncode, 65)
        self.assertIn("invalid endpoint", res.stderr)
        self.assertEqual(self.server.requests, [])

    def test_raw_preprocessing_in_bin_speak(self):
        tech_text = "Dynamic Resource Allocation работает в Kubernetes 1.35 с UUID 12345678-1234-5678-1234-567812345678."
        cmd = [
            SPEAK,
            "--provider", "teratts",
            tech_text,
        ]
        res = subprocess.run(cmd, env=self.env, capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(len(self.server.requests), 1)
        received_text = self.server.requests[0]["payload"]["text"]
        self.assertIn("12345678-1234-5678-1234-567812345678", received_text)
        self.assertIn("Kubernetes 1.35", received_text)

    def test_speak_info_and_refresh_voices_teratts(self):
        res = subprocess.run([SPEAK, "--set", ".provider", "teratts"], env=self.env, capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, res.stderr)

        res = subprocess.run([SPEAK, "--refresh-voices", "teratts"], env=self.env, capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, res.stderr)
        data = json.loads(res.stdout)
        self.assertEqual(data["provider"], "teratts")
        self.assertEqual(data["count"], 4)

        res = subprocess.run([SPEAK, "--info"], env=self.env, capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, res.stderr)
        info = json.loads(res.stdout)
        self.assertEqual(info["provider"], "teratts")
        self.assertTrue(info["ui"]["sampleIsDefault"])
        self.assertIsNone(info["ocr"]["model"])
        self.assertEqual(info["voice"], "ru_f1")
        self.assertEqual(len(info["voices"]), 4)
        teratts_meta = next(p for p in info["providers"] if p["name"] == "teratts")
        self.assertEqual(teratts_meta["title"], "TeraTTS")
        self.assertTrue(teratts_meta["refreshVoices"])
        self.assertEqual(teratts_meta["keySource"], "env")

        changed = subprocess.run([SPEAK, "--set", ".ui.sampleText", "Custom voice test"],
                                 env=self.env, capture_output=True, text=True)
        self.assertEqual(changed.returncode, 0, changed.stderr)
        custom_info = json.loads(subprocess.run([SPEAK, "--info"], env=self.env,
                                                capture_output=True, text=True, check=True).stdout)
        self.assertFalse(custom_info["ui"]["sampleIsDefault"])
        self.assertEqual(custom_info["ui"]["sampleText"], "Custom voice test")

        switched = subprocess.run([SPEAK, "--set", ".ocr.engine", "openai"],
                                  env=self.env, capture_output=True, text=True)
        self.assertEqual(switched.returncode, 0, switched.stderr)
        cloud_info = json.loads(subprocess.run([SPEAK, "--info"], env=self.env,
                                               capture_output=True, text=True, check=True).stdout)
        self.assertEqual(cloud_info["ocr"]["model"], "gpt-4.1-mini")

    def test_only_teratts_is_selectable_and_settings_persist(self):
        for path, value in ((".teratts.voice", "ru_m1"), (".teratts.endpoint", self.env["TERATTS_URL"])):
            result = subprocess.run([SPEAK, "--set", path, value], env=self.env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
        info = json.loads(subprocess.run([SPEAK, "--info"], env=self.env, capture_output=True, text=True, check=True).stdout)
        self.assertEqual(info["voice"], "ru_m1")
        self.assertEqual(info["endpoint"], self.env["TERATTS_URL"])
        self.assertEqual([provider["name"] for provider in info["providers"]], ["teratts"])
        self.assertNotEqual(subprocess.run([SPEAK, "--set", ".provider", "piper"], env=self.env, capture_output=True).returncode, 0)
        self.assertNotEqual(subprocess.run([SPEAK, "--provider", "openai", "hello"], env=self.env, capture_output=True).returncode, 0)
        self.assertNotEqual(subprocess.run([SPEAK, "--set", ".teratts.endpoint", "http://other-server/tts"], env=self.env, capture_output=True).returncode, 0)


    def test_retired_tts_defaults_are_not_created_and_old_values_survive(self):
        result = subprocess.run([SPEAK, "--set", ".rate", "1"], env=self.env, capture_output=True)
        self.assertEqual(result.returncode, 0)
        path = self.config_dir / "config.json"
        config = json.loads(path.read_text())
        retired = ("piper", "openai", "elevenlabs", "kokoro", "gemini", "google")
        self.assertFalse(set(retired) & config.keys())
        saved = {name: {"voice": "old-custom-value", "privateExtension": [1, 2]} for name in retired}
        config.update(saved)
        path.write_text(json.dumps(config))
        result = subprocess.run([SPEAK, "--set", ".rate", "1.5"], env=self.env, capture_output=True)
        self.assertEqual(result.returncode, 0)
        updated = json.loads(path.read_text())
        self.assertEqual({name: updated[name] for name in retired}, saved)
        self.assertEqual(updated["ocr"]["openai"]["model"], "gpt-4.1-mini")
        self.assertNotEqual(subprocess.run([SPEAK, "--set", ".piper.voice", "new"],
                                          env=self.env, capture_output=True).returncode, 0)

    def test_legacy_ocr_model_is_validated_and_invalidated(self):
        result = subprocess.run([SPEAK,"--set",".ocr.openai.model","gpt-4o"],env=self.env,capture_output=True)
        self.assertEqual(result.returncode,0)
        self.assertEqual(json.loads((self.config_dir / "config.json").read_text())["ocr"]["openai"]["model"],"gpt-4o")
        result = subprocess.run([SPEAK,"--set",".ocr.openai.model","bad model"],env=self.env,capture_output=True)
        self.assertNotEqual(result.returncode,0)

    def test_setup_status_describes_teratts_and_retires_local_tts_targets(self):
        result = subprocess.run([SETUP,"status"],env=self.env,capture_output=True,text=True,check=True)
        info = json.loads(result.stdout)
        self.assertEqual(info["defaultVoice"],"ru_f1")
        self.assertTrue(info["ready"], info)
        self.assertEqual(info["readiness"],"configured")
        for name in ("piper","kokoro","recommended"):
            result = subprocess.run([SETUP,"start",name],env=self.env,capture_output=True,text=True)
            self.assertEqual(json.loads(result.stdout)["code"],"unknown_target")
        result = subprocess.run([SETUP,"start","lang:../bad"],env=self.env,capture_output=True,text=True)
        self.assertEqual(json.loads(result.stdout)["code"],"unknown_target")

    def test_changing_voice_controls_real_requests(self):
        subprocess.run([SPEAK, "--set", ".teratts.voice", "ru_m1"], env=self.env, capture_output=True, check=True)
        result = subprocess.run([SPEAK, "Проверка нового голоса."], env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.server.requests[0]["payload"]["voice"], "ru_m1")

    def test_raw_speech_does_not_rewrite_technical_words(self):
        text = "Kubernetes 1.35 и cluster_node_id работают вместе."
        result = subprocess.run([SPEAK, text], env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.server.requests[0]["payload"]["text"], "Kubernetes 1.35 и cluster node id работают вместе.")

    def test_speak_setup_recognizes_teratts_in_cloud_keys(self):
        # speak-setup key-remove teratts should not reject as unknown provider
        res = subprocess.run([SETUP, "key-remove", "teratts"], env=self.env, capture_output=True, text=True)
        self.assertNotIn("Unknown provider", res.stderr)
        self.assertNotIn("Unknown provider", res.stdout)

    def test_ocr_key_mutation_preserves_retired_speech_settings_without_warning(self):
        config = self.config_dir / "config.json"
        config.write_text(json.dumps({"google": {"voice": "old-user-voice"}}))
        health = self.cache_dir / "health.json"
        health.write_text(json.dumps({"ocr:google": {"status": "ok"},
                                     "teratts": {"status": "ok"}}))
        for action, value in (("key-store", "test-ocr-key\n"), ("key-remove", "")):
            result = subprocess.run([SETUP, action, "google"], input=value,
                                    env=self.env, capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)
            response = json.loads(result.stdout)
            self.assertTrue(response["ok"], response)
            self.assertEqual(response.get("warning", ""), "", response)
            self.assertEqual(json.loads(config.read_text())["google"]["voice"], "old-user-voice")
            self.assertNotIn("ocr:google", json.loads(health.read_text()))
            self.assertIn("teratts", json.loads(health.read_text()))

    def test_cleanup_refuses_to_remove_shared_shortcuts_and_keys(self):
        res = subprocess.run([SETUP, "cleanup", "--yes"], env=self.env,
                             capture_output=True, text=True)
        self.assertEqual(res.returncode, 2, res.stderr)
        self.assertEqual(json.loads(res.stdout)["code"], "shared_state")

if __name__ == "__main__":
    unittest.main()
