"""Consumer checks for WAV export and real mpv control, isolated from desktop."""
import http.server
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import struct
import sys
import tempfile
import threading
import time
import unittest
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
from audio_runtime import owner_live, player_command, read_json
from audio_runtime import snapshot
from unittest.mock import patch
from test_teratts import MockTeraHandler, make_dummy_wav

ROOT = Path(__file__).resolve().parents[1]


class AudioHandler(MockTeraHandler):
    def do_POST(self):
        if self.server.fail_after is not None and len(self.server.requests) >= self.server.fail_after:
            self.send_error(500)
            return
        if self.path == "/tts" and not self.server.fail_with_code:
            n = int(self.headers["Content-Length"])
            payload = json.loads(self.rfile.read(n))
            self.server.requests.append({"payload": payload})
            self.server.entered.set()
            time.sleep(self.server.delay)
            self.send_response(200)
            self.send_header("Content-Type", "audio/wav")
            self.end_headers()
            try:
                self.wfile.write(self.server.audio_data or make_dummy_wav(self.server.frames))
            except (BrokenPipeError, ConnectionResetError):
                pass
        else:
            super().do_POST()


class AudioJobs(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        tools = self.base / "bin"
        tools.mkdir()
        (tools / "secret-tool").write_text("#!/bin/sh\nexit 1\n")
        (tools / "secret-tool").chmod(0o755)
        (tools / "wl-copy").write_text("#!/bin/sh\ncat > \"$COPY_CAPTURE\"\n")
        (tools / "wl-copy").chmod(0o755)
        (tools / "notify-send").write_text("#!/usr/bin/env python3\nimport json,os,sys\nopen(os.environ['NOTIFY_CAPTURE'],'w').write(json.dumps(sys.argv[1:]))\n")
        (tools / "notify-send").chmod(0o755)
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), AudioHandler)
        self.server.requests = []
        self.server.expected_token = ""
        self.server.fail_with_code = None
        self.server.fail_after = None
        self.server.delay = 0
        self.server.frames = 200
        self.server.audio_data = None
        self.server.entered = threading.Event()
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.env = dict(os.environ, PATH=str(tools) + os.pathsep + os.environ["PATH"],
                        XDG_CONFIG_HOME=str(self.base / "config"), XDG_DATA_HOME=str(self.base / "data"),
                        XDG_STATE_HOME=str(self.base / "state"), XDG_CACHE_HOME=str(self.base / "cache"),
                        XDG_RUNTIME_DIR=str(self.base / "runtime"),
                        TERATTS_URL=f"http://127.0.0.1:{self.server.server_port}",
                        TERATTS_BEARER_TOKEN="test-token", TTS_TEST_AUDIO_NULL="1",
                        COPY_CAPTURE=str(self.base / "copied-uri"))
        self.env["NOTIFY_CAPTURE"] = str(self.base / "notification.json")
        self.env.pop("TTS_SILENT", None)
        self.run_dir = self.base / "runtime/omarchy-tts"
        self.processes = []
        self.addCleanup(self.stop_jobs)

    def stop_jobs(self):
        self.call("--stop")
        for process in self.processes:
            try:
                process.communicate(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill(); process.communicate()

    def call(self, *args):
        return subprocess.run([str(ROOT / "bin/speak"), *args], env=self.env,
                              capture_output=True, text=True, timeout=8)

    def start(self, *args):
        process = subprocess.Popen([str(ROOT / "bin/speak"), *args], env=self.env,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.processes.append(process)
        return process

    def wait_for(self, predicate, maximum=4):
        end = time.monotonic() + maximum
        while time.monotonic() < end:
            if predicate():
                return
            time.sleep(.025)
        self.fail("condition did not become true")

    def test_runtime_owner_refuses_fifo_and_symlink(self):
        fifo = self.base / "owner-fifo"
        os.mkfifo(fifo)
        self.assertFalse(owner_live(fifo))
        link = self.base / "owner-link"
        link.symlink_to(fifo)
        self.assertFalse(owner_live(link))

    def test_export_source_flag_order_is_independent(self):
        result = subprocess.run([str(ROOT / "bin/speak"), "--stdin-json", "--export-wav"],
                                input=json.dumps("A JSON input."), env=self.env,
                                capture_output=True, text=True, timeout=8)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("JSON input", self.server.requests[0]["payload"]["text"])

    def test_audio_format_default_preference_override_and_explicit_uri(self):
        self.server.frames = 44100
        default = self.call("--export-audio", "--raw", "Audio attachment.")
        self.assertEqual(default.returncode, 0, default.stderr)
        item = json.loads(default.stdout)
        self.assertTrue(item["filename"].endswith(".mp3"))
        self.assertFalse((self.base / "copied-uri").exists())
        self.assertEqual(self.call("--audio-copy", item["id"]).returncode, 0)
        self.assertTrue((self.base / "copied-uri").read_text().strip().endswith(".mp3"))
        self.assertEqual(self.call("--set", ".ui.exportFormat", "ogg").returncode, 0)
        result = self.call("--raw", "Saved format.", "--export-audio")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)["filename"].endswith(".ogg"))
        result = self.call("--format", "wav", "--export-audio", "--raw", "Explicit format.")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)["filename"].endswith(".wav"))
        self.assertNotEqual(self.call("--export-wav", "--format", "mp3", "Invalid mix.").returncode, 0)

    def test_stop_during_encoding_cleans_both_parts(self):
        self.server.frames = 44100
        tools = self.base / "bin"
        (tools / "ffmpeg").write_text('#!/bin/sh\nprintf started > "$ENCODER_CAPTURE"\nsleep 5\nexit 1\n')
        (tools / "ffmpeg").chmod(0o755)
        marker = self.base / "encoding"
        self.env["ENCODER_CAPTURE"] = str(marker)
        process = self.start("--export-audio", "--raw", "Cancel encoding.")
        self.wait_for(marker.exists)
        self.assertEqual(self.call("--stop").returncode, 0)
        process.communicate(timeout=3)
        folder = self.base / "data/omarchy-teratts/exports"
        self.assertEqual(list(folder.glob("*.part")), [])
        self.assertEqual(json.loads(self.call("--audio-list").stdout), [])

    @unittest.skipUnless(shutil.which("mpv"), "mpv is unavailable")
    def test_live_meter_follows_playback_pause_and_speed(self):
        pcm = b"".join(struct.pack("<h", round(8000 * math.sin(2 * math.pi * freq * n / 44100)))
                       for freq in (150, 5000) for n in range(44100 * 2))
        path = self.base / "tones.wav"
        with wave.open(str(path), "wb") as audio:
            audio.setparams((1, 2, 44100, 0, "NONE", "not compressed"))
            audio.writeframes(pcm)
        self.server.audio_data = path.read_bytes()
        process = self.start("--raw", "Measure actual playback.")
        state = lambda: read_json(self.run_dir / "player.json")
        self.wait_for(lambda: state().get("positionMs", 0) > 300)
        early = state()["bands"]
        self.assertEqual(early.index(max(early)), 0, early)
        self.assertEqual(self.call("--pause").returncode, 0)
        self.wait_for(lambda: state().get("status") == "paused")
        self.assertEqual(state()["bands"], [0] * 4)
        self.assertEqual(self.call("--playback-rate", "2").returncode, 0)
        self.assertEqual(self.call("--resume").returncode, 0)
        self.wait_for(lambda: state().get("positionMs", 0) > 2400)
        late = state()["bands"]
        self.assertEqual(late.index(max(late)), 3, late)
        self.call("--stop")
        process.communicate(timeout=3)

    def test_multichunk_wav_export_and_explicit_copy(self):
        result = self.call("--export-wav", "--raw", "A complete sentence. " * 120)
        self.assertEqual(result.returncode, 0, result.stderr)
        item = json.loads(result.stdout)
        self.assertGreater(len(self.server.requests), 1)
        folder = self.base / "data/omarchy-teratts/exports"
        with wave.open(str(folder / item["filename"]), "rb") as audio:
            self.assertEqual(audio.getnframes(), 200 * len(self.server.requests))
            self.assertEqual(audio.getframerate(), 44100)
        self.assertFalse((self.base / "copied-uri").exists())
        copied = self.call("--audio-copy", item["id"])
        self.assertEqual(copied.returncode, 0, copied.stderr)
        self.assertEqual((self.base / "copied-uri").read_bytes(), ((folder / item["filename"]).as_uri() + "\r\n").encode())

    def test_slow_export_limits_chunks_and_snapshots_rate(self):
        self.server.delay = .05
        process = self.start("--export-wav", "--raw", "--rate", ".25", "A complete sentence. " * 120)
        self.wait_for(self.server.entered.is_set)
        self.assertEqual(self.call("--set", ".rate", "4").returncode, 0)
        stdout, stderr = process.communicate(timeout=8)
        self.assertEqual(process.returncode, 0, stderr)
        self.assertEqual(json.loads(stdout)["rate"], .25)
        self.assertTrue(all(len(x["payload"]["text"]) <= 500 for x in self.server.requests))
        self.assertTrue(all(x["payload"]["duration_scale"] == 4 for x in self.server.requests))

    def test_busy_export_not_preempted_and_stop_removes_partial(self):
        self.server.delay = 2
        process = self.start("--export-wav", "--raw", "A sentence to export.")
        self.wait_for(self.server.entered.is_set)
        other = self.call("--raw", "Do not interrupt this export.")
        self.assertEqual(other.returncode, 75, other.stderr)
        self.assertIsNone(process.poll())
        self.assertEqual(self.call("--stop").returncode, 0)
        process.communicate(timeout=3)
        folder = self.base / "data/omarchy-teratts/exports"
        self.assertEqual(list(folder.glob("*.wav")), [])
        self.assertEqual(list(folder.glob("*.part")), [])

    def test_middle_failure_does_not_publish_wav(self):
        self.server.fail_after = 1
        result = self.call("--export-wav", "--raw", "A sentence. " * 120)
        self.assertEqual(result.returncode, 74)
        self.assertEqual(json.loads(result.stderr)["errorCode"], "network")
        self.assertEqual(len(self.server.requests), 1)
        folder = self.base / "data/omarchy-teratts/exports"
        self.assertEqual(list(folder.glob("*.wav")), [])
        self.assertEqual(list(folder.glob("*.part")), [])

    @unittest.skipUnless(shutil.which("mpv"), "mpv is unavailable")
    def test_delete_current_preview_stops_and_removes_file(self):
        self.server.frames = 44100 * 3
        item = json.loads(self.call("--export-wav", "--raw", "Delete this preview.").stdout)
        preview = self.start("--audio-preview", item["id"])
        self.wait_for(lambda: read_json(self.run_dir / "job.json").get("audioId") == item["id"])
        self.assertEqual(self.call("--pause").returncode, 0)
        self.wait_for(lambda: read_json(self.run_dir / "player.json").get("status") == "paused")
        self.assertEqual(self.call("--resume").returncode, 0)
        self.wait_for(lambda: read_json(self.run_dir / "player.json").get("status") == "playing")
        deleted = self.call("--audio-delete", item["id"])
        self.assertEqual(deleted.returncode, 0, deleted.stderr)
        preview.communicate(timeout=3)
        self.assertEqual(json.loads(self.call("--audio-list").stdout), [])
        self.assertFalse((self.base / "data/omarchy-teratts/exports" / item["filename"]).exists())
        self.assertEqual(self.call("--status").stdout.strip(), "idle")
        self.assertEqual(list(self.run_dir.glob("p-*.sock")), [])

    @unittest.skipUnless(shutil.which("mpv"), "mpv is unavailable")
    def test_active_preview_deletion_survives_late_monitor_attachment(self):
        bootstrap = self.base / "late-monitor"
        bootstrap.mkdir()
        marker = self.base / "delayed-mpv"
        (bootstrap / "sitecustomize.py").write_text(
            "import os,subprocess,time\n"
            "original = subprocess.Popen.__init__\n"
            "def delayed(self,args,*a,**kw):\n"
            "    original(self,args,*a,**kw)\n"
            "    if isinstance(args,list) and args and args[0]=='mpv':\n"
            "        open(os.environ['DELAY_MPV_CAPTURE'],'w').write('3.2')\n"
            "        time.sleep(3.2)\n"
            "subprocess.Popen.__init__ = delayed\n")
        self.env.update(PYTHONPATH=str(bootstrap), DELAY_MPV_CAPTURE=str(marker))
        self.test_delete_current_preview_stops_and_removes_file()
        self.assertEqual(marker.read_text(), "3.2")

    @unittest.skipUnless(shutil.which("mpv"), "mpv is unavailable")
    def test_preview_seek_and_other_delete_keep_the_player(self):
        self.server.frames = 44100 * 4
        item = json.loads(self.call("--export-wav", "--raw", "Keep this preview.").stdout)
        other = json.loads(self.call("--export-wav", "--raw", "Delete another file.").stdout)
        preview = self.start("--audio-preview", item["id"])
        self.wait_for(lambda: read_json(self.run_dir / "player.json").get("status") == "playing")
        with patch.dict(os.environ, TTS_STATE_DIR=str(self.run_dir)):
            self.assertEqual(snapshot()["audioId"], item["id"])
        path = next(self.run_dir.glob("p-*.sock"))
        self.assertEqual(self.call("--pause").returncode, 0)
        self.assertEqual(self.call("--audio-delete", other["id"]).returncode, 0)
        self.assertIsNone(preview.poll())
        self.assertTrue(path.exists())
        for value in ("nan", "inf", "-1", "oops"):
            self.assertNotEqual(self.call("--playback-seek", value).returncode, 0)
        self.assertEqual(self.call("--playback-seek", "2").returncode, 0)
        with patch.dict(os.environ, TTS_STATE_DIR=str(self.run_dir)):
            self.assertEqual(snapshot()["positionMs"], 2000)
        self.assertTrue(player_command(path, ["get_property", "pause"]))
        self.assertEqual(player_command(path, ["get_property", "speed"]), 1)
        self.assertEqual(self.call("--playback-seek", "0.5").returncode, 0)
        with patch.dict(os.environ, TTS_STATE_DIR=str(self.run_dir)):
            self.assertEqual(snapshot()["positionMs"], 500)
        self.assertEqual(self.call("--resume").returncode, 0)
        self.wait_for(lambda: player_command(path, ["get_property", "time-pos"]) >= .5)
        self.assertNotIn("pausedSeekMs", read_json(self.run_dir / "job.json"))
        self.call("--stop")
        preview.communicate(timeout=3)
        with patch.dict(os.environ, TTS_STATE_DIR=str(self.run_dir)):
            self.assertIsNone(snapshot()["audioId"])

    @unittest.skipUnless(shutil.which("mpv"), "mpv is unavailable")
    def test_pause_before_first_audio_and_preview_starts_at_one(self):
        self.server.delay = .4
        self.server.frames = 44100 * 2
        process = self.start("--raw", "A paused first fragment.")
        self.wait_for(self.server.entered.is_set)
        self.assertEqual(self.call("--pause").returncode, 0)
        self.wait_for(lambda: list(self.run_dir.glob("p-*.sock")))
        path = next(self.run_dir.glob("p-*.sock"))
        time.sleep(.55)
        self.assertTrue(player_command(path, ["get_property", "pause"]))
        self.assertLess(player_command(path, ["get_property", "time-pos"]), .03)
        self.assertEqual(self.call("--resume").returncode, 0)
        process.communicate(timeout=4)
        self.assertEqual(len(self.server.requests), 1)
        self.server.delay = 0
        self.server.frames = 44100 * 8
        item = json.loads(self.call("--export-wav", "--rate", "1.5", "--raw", "An export.").stdout)
        self.assertEqual(self.call("--set", ".rate", "3").returncode, 0)
        preview = self.start("--audio-preview", item["id"])
        self.wait_for(lambda: list(self.run_dir.glob("p-*.sock")))
        path = next(self.run_dir.glob("p-*.sock"))
        self.assertEqual(player_command(path, ["get_property", "speed"]), 1)
        self.assertEqual(self.call("--playback-rate", "2").returncode, 0)
        self.assertEqual(json.loads((self.base / "config/omarchy-tts/config.json").read_text())["rate"], 3)
        self.call("--stop")
        preview.communicate(timeout=3)
        listed = self.call("--audio-list")
        self.assertEqual(json.loads(listed.stdout)[0]["id"], item["id"])

    def test_watcher_emits_idle_heartbeat(self):
        import select
        watcher = self.start("--watch-state")
        self.addCleanup(watcher.terminate)
        first = json.loads(watcher.stdout.readline())
        self.assertEqual(first["status"], "idle")
        self.assertTrue(select.select([watcher.stdout], [], [], 4)[0])
        second = json.loads(watcher.stdout.readline())
        self.assertEqual(first, second)
        watcher.terminate()
        watcher.communicate(timeout=3)

    def test_failure_notifications_use_requested_catalog_without_payload(self):
        self.server.fail_with_code = 503
        for locale in ("ru", "en"):
            self.env["TTS_UI_LOCALE"] = locale
            result = self.call("--raw", "Private test source must not enter the notification.")
            self.assertEqual(result.returncode, 74)
            notification = json.loads((self.base / "notification.json").read_text())
            catalog = json.loads((ROOT / f"locales/{locale}.json").read_text())
            self.assertEqual(notification[-2:], [catalog["notify.network.title"], catalog["notify.network.body"]])

    def test_ocr_input_and_deadline_failures_preserve_engine_health(self):
        engine_dir = self.base / "config/omarchy-tts/ocr"
        engine_dir.mkdir(parents=True, exist_ok=True)
        engine = engine_dir / "fixture"
        engine.write_text("#!/bin/sh\n# kind: local\n# probe: true\nexit 65\n")
        engine.chmod(0o755)
        paste = self.base / "bin/wl-paste"
        paste.write_text('#!/bin/sh\nif [ "$1" = "--list-types" ]; then echo image/png; else cat "$OCR_IMAGE"; fi\n')
        paste.chmod(0o755)
        self.env["OCR_IMAGE"] = str(ROOT / "lib/ocr-probe.png")
        self.assertEqual(self.call("--set", ".ocr.engine", "fixture").returncode, 0)
        self.assertEqual(self.call("--clipboard").returncode, 65)
        health = self.base / "cache/omarchy-tts/health.json"
        self.assertNotEqual(read_json(health).get("ocr:fixture", {}).get("status"), "failed")
        engine.write_text("#!/usr/bin/env python3\n# kind: local\n# probe: true\nimport time\ntime.sleep(30)\n")
        deadline = self.base / "bin/timeout"
        deadline.write_text('#!/bin/bash\nif [[ "$1" == --kill-after=2s && "$2" == 120s ]]; then shift 2; exec /usr/bin/timeout --kill-after=.1s .15s "$@"; fi\nexec /usr/bin/timeout "$@"\n')
        deadline.chmod(0o755)
        result = self.call("--clipboard")
        self.assertEqual(result.returncode, 124, result.stderr)
        self.assertNotEqual(read_json(health).get("ocr:fixture", {}).get("status"), "failed")
        self.assertEqual(list(self.run_dir.glob(".ocr-output.*")), [])

    def test_ocr_failure_publishes_error_and_private_notification(self):
        engine_dir = self.base / "config/omarchy-tts/ocr"
        engine_dir.mkdir(parents=True, exist_ok=True)
        engine = engine_dir / "fixture"
        paste = self.base / "bin/wl-paste"
        paste.write_text('#!/bin/sh\nif [ "$1" = "--list-types" ]; then echo image/png; else cat "$OCR_IMAGE"; fi\n')
        paste.chmod(0o755)
        self.env["OCR_IMAGE"] = str(ROOT / "lib/ocr-probe.png")
        self.assertEqual(self.call("--set", ".ocr.engine", "fixture").returncode, 0)
        for rc, code in ((65, "invalid_input"), (69, "quota"), (74, "network"),
                         (75, "rate_limited"), (77, "unauthorized"), (124, "network")):
            with self.subTest(exit_code=rc):
                engine.write_text(f'#!/bin/sh\n# kind: cloud\n# probe: true\necho "private OCR detail" >&2\nexit {rc}\n')
                engine.chmod(0o755)
                notice = self.base / "notification.json"
                notice.unlink(missing_ok=True)
                result = self.call("--clipboard")
                self.assertEqual(result.returncode, rc, result.stderr)
                with patch.dict(os.environ, TTS_STATE_DIR=str(self.run_dir)):
                    state = snapshot()
                self.assertEqual(state["status"], "error")
                self.assertEqual(state["errorCode"], code)
                self.assertFalse(state["busy"])
                self.assertTrue(notice.exists())
                self.assertNotIn("private", notice.read_text())
                self.assertEqual(list(self.run_dir.glob(".ocr-output.*")), [])

    def test_stop_during_owned_capture_delay_never_starts_capture(self):
        self.env["TTS_CAPTURE_DELAY"] = "1"
        marker = self.base / "capture-started"
        delayed = self.base / "delay-started"
        sleep_tool = self.base / "bin/sleep"
        sleep_tool.write_text(f'#!/bin/sh\nif [ "$1" = "1" ]; then touch "{delayed}"; fi\nexec /usr/bin/sleep "$@"\n')
        sleep_tool.chmod(0o755)
        self.env["TMPDIR"] = str(self.base)
        for name in ("slurp", "hyprpicker", "grim"):
            tool = self.base / "bin" / name
            tool.write_text(f'#!/bin/sh\ntouch "{marker}"\nexit 1\n')
            tool.chmod(0o755)
        process = self.start("--snip")
        self.wait_for(delayed.exists)
        self.assertTrue(owner_live(self.run_dir / "preparing"))
        self.assertEqual(self.call("--stop").returncode, 0)
        process.communicate(timeout=3)
        self.assertFalse(marker.exists())
        self.assertEqual(list(self.base.glob("speak-*.png")), [])
        self.assertEqual(list(self.run_dir.glob(".bounded-output.*")), [])
        with patch.dict(os.environ, TTS_STATE_DIR=str(self.run_dir)):
            self.assertEqual(snapshot()["status"], "idle")
        self.assertFalse((self.base / "notification.json").exists())

    def test_cancelled_capture_has_no_error_or_notification(self):
        for name, content in (("slurp", "exit 1"), ("hyprpicker", "exit 0")):
            tool = self.base / "bin" / name
            tool.write_text("#!/bin/sh\n" + content + "\n")
            tool.chmod(0o755)
        result = self.call("--export-audio", "--snip")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertFalse((self.base / "notification.json").exists())
        with patch.dict(os.environ, TTS_STATE_DIR=str(self.run_dir)):
            self.assertEqual(snapshot()["status"], "idle")

    def test_missing_player_ipc_fails_instead_of_silent_monitor_loss(self):
        fake = self.base / "bin/mpv"
        fake.write_text("#!/usr/bin/env python3\nimport time\ntime.sleep(30)\n")
        fake.chmod(0o755)
        started = time.monotonic()
        result = self.call("--raw", "A controlled missing player socket.")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('"errorCode": "io"', result.stderr)
        self.assertLess(time.monotonic() - started, 6)
        self.assertEqual(list(self.run_dir.glob("p-*.sock")), [])

    @unittest.skipUnless(shutil.which("mpv"), "mpv is unavailable")
    def test_real_player_finishes_short_speech_and_preview_without_an_error(self):
        self.server.frames = 22050
        for rate in (1, 4):
            with self.subTest(rate=rate):
                result = self.call("--raw", "--rate", str(rate), "A short fixture.")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(read_json(self.run_dir / "player.json").get("status"), "idle")
        item = json.loads(self.call("--export-wav", "--raw", "A short preview.").stdout)
        result = self.call("--audio-preview", item["id"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(read_json(self.run_dir / "player.json").get("status"), "idle")
        self.assertEqual(list(self.run_dir.glob("p-*.sock")), [])

    def test_eof_without_player_exit_still_fails_with_a_deadline(self):
        fake = self.base / "bin/mpv"
        fake.write_text('''#!/usr/bin/env python3
import socket,sys,time
path=next(a.split("=",1)[1] for a in sys.argv if a.startswith("--input-ipc-server="))
s=socket.socket(socket.AF_UNIX);s.bind(path);s.listen()
c,_=s.accept();c.recv(16384);c.sendall(b'{"request_id":1,"error":"success"}\\n');c.close()
c,_=s.accept();c.recv(16384);c.sendall(b'{"event":"end-file","reason":"eof"}\\n');c.close()
time.sleep(30)
''')
        fake.chmod(0o755)
        start = time.monotonic()
        result = self.call("--raw", "A stuck EOF fixture.")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('"errorCode": "io"', result.stderr)
        self.assertLess(time.monotonic() - start, 6)
        self.assertEqual(list(self.run_dir.glob("p-*.sock")), [])

    def test_player_ipc_disconnect_fails_and_cleans_socket(self):
        fake = self.base / "bin/mpv"
        fake.write_text('''#!/usr/bin/env python3
import json,socket,sys,time
path=next(a.split("=",1)[1] for a in sys.argv if a.startswith("--input-ipc-server="))
s=socket.socket(socket.AF_UNIX);s.bind(path);s.listen()
c,_=s.accept();c.recv(16384);c.sendall(b'{"request_id":1,"error":"success"}\\n');c.close()
c,_=s.accept();c.recv(16384);c.close()
time.sleep(30)
''')
        fake.chmod(0o755)
        result = self.call("--raw", "A controlled disconnected player.")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('"errorCode": "io"', result.stderr)
        self.assertEqual(list(self.run_dir.glob("p-*.sock")), [])

    @unittest.skipUnless(shutil.which("mpv"), "mpv is unavailable")
    def test_real_pause_speed_resume_and_base_synthesis_rate(self):
        self.server.frames = 44100 * 4
        process = self.start("--raw", "--rate", "1.5", "A test of live playback controls.")
        self.wait_for(lambda: list(self.run_dir.glob("p-*.sock")))
        path = next(self.run_dir.glob("p-*.sock"))
        self.wait_for(lambda: self.server.requests)
        self.assertNotEqual(self.call("--playback-seek", "1").returncode, 0)
        time.sleep(.15)
        pause = self.call("--pause")
        self.assertEqual(pause.returncode, 0, pause.stderr)
        before = player_command(path, ["get_property", "time-pos"])
        time.sleep(.15)
        after = player_command(path, ["get_property", "time-pos"])
        self.assertAlmostEqual(before, after, places=2)
        self.assertEqual(self.call("--playback-rate", "2").returncode, 0)
        self.assertEqual(player_command(path, ["get_property", "speed"]), 2)
        self.assertEqual(self.call("--resume").returncode, 0)
        self.assertTrue(all(x["payload"]["duration_scale"] == 1 for x in self.server.requests))
        self.assertEqual(self.call("--stop").returncode, 0)
        process.communicate(timeout=3)


if __name__ == "__main__":
    unittest.main()
