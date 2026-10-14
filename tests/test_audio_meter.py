"""Measure real decoded audio and check the meter's playback-time contract."""
from pathlib import Path
import math
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
from audio_meter import Meter, filter_graph
from audio_runtime import atomic_json, snapshot


def measurement(meter, pts, db):
    for index, value in enumerate(db):
        meter.feed(f"frame:0 pts:0 pts_time:{pts}".encode())
        meter.feed(f"lavfi.astats.Overall.RMS_level={value}".encode())
        meter.feed(f"teratts.band={index}".encode())


class AudioMeterTests(unittest.TestCase):
    def test_buffered_future_is_not_displayed_and_timeline_is_bounded(self):
        meter = Meter()
        measurement(meter, 0, [-55, -40, -25, -12])
        measurement(meter, .2, [-12] * 4)
        self.assertEqual(meter.levels(.1), [0, .349, .698, 1])
        self.assertEqual(meter.levels(.6), [0] * 4)
        for frame in range(1000):
            measurement(meter, frame / 10, [-20] * 4)
        self.assertLessEqual(len(meter.samples), 256)
        self.assertEqual(meter.levels(1000), [0] * 4)

    def test_silence_and_incomplete_measurements_are_zero(self):
        meter = Meter()
        measurement(meter, 0, ["-inf", "nan", "inf", -80])
        self.assertEqual(meter.levels(.1), [0] * 4)
        meter.feed(b"frame:1 pts:4096 pts_time:0.2")
        meter.feed(b"lavfi.astats.Overall.RMS_level=-12")
        meter.feed(b"teratts.band=0")
        self.assertEqual(meter.levels(.4), [0] * 4)

    @unittest.skipUnless(shutil.which("ffmpeg"), "audio tools unavailable")
    def test_large_input_frames_keep_measurements_inside_the_freshness_window(self):
        pcm = b"".join(struct.pack("<h", round(8000 * math.sin(2 * math.pi * 600 * n / 44100)))
                       for n in range(44100))
        result = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-f", "s16le",
                                 "-ar", "44100", "-ac", "1", "-i", "pipe:0",
                                 "-filter_complex", "asetnsamples=n=22050:p=0," + filter_graph(),
                                 "-map", "[out]", "-f", "s16le", "pipe:1"],
                                input=pcm, capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr[-500:])
        self.assertEqual(result.stdout, pcm)
        meter = Meter()
        for line in result.stderr.splitlines():
            meter.feed(line)
        for position in (.1, .35, .6, .85):
            self.assertGreater(max(meter.levels(position)), .5, position)

    def test_paused_or_stale_job_clears_levels(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, TTS_STATE_DIR=folder):
            root = Path(folder)
            atomic_json(root / "job.json", {"jobId": "one", "kind": "speech", "pauseRequested": False})
            atomic_json(root / "player.json", {"jobId": "one", "status": "playing", "bands": [1] * 4})
            with patch("audio_runtime.owner_live", return_value=True):
                self.assertEqual(snapshot()["bands"], [1] * 4)
                atomic_json(root / "job.json", {"jobId": "one", "kind": "speech", "pauseRequested": True})
                self.assertEqual(snapshot()["bands"], [0] * 4)
                atomic_json(root / "job.json", {"jobId": "two", "kind": "speech", "pauseRequested": False})
                self.assertEqual(snapshot()["bands"], [0] * 4)
            self.assertEqual(snapshot()["bands"], [0] * 4)

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("mpv"), "audio tools unavailable")
    def test_real_frequency_bands_silence_and_unchanged_audio(self):
        pcm = b"".join(struct.pack("<h", round(8000 * math.sin(2 * math.pi * freq * n / 44100)))
                       if freq else b"\0\0"
                       for freq in (150, 600, 2000, 5000, 0) for n in range(44100))
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "bands.wav"
            with wave.open(str(path), "wb") as audio:
                audio.setparams((1, 2, 44100, 0, "NONE", "not compressed"))
                audio.writeframes(pcm)
            original = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", str(path),
                                       "-filter_complex", filter_graph(), "-map", "[out]",
                                       "-f", "s16le", "pipe:1"], capture_output=True, timeout=5)
            self.assertEqual(original.returncode, 0, original.stderr[-500:])
            self.assertEqual(original.stdout, pcm)
            player = subprocess.run(["mpv", "--no-config", "--load-scripts=no", "--no-video",
                                     "--ao=null", "--untimed", "--msg-level=all=no",
                                     "--af=lavfi=[" + filter_graph() + "]", str(path)],
                                    capture_output=True, timeout=8)
            self.assertEqual(player.returncode, 0, player.stderr[-500:])
            meter = Meter()
            for line in player.stderr.splitlines():
                meter.feed(line)
            diagnostic = {
                "sample_count": len(meter.samples),
                "first_pts": next(iter(meter.samples), None),
                "last_pts": next(reversed(meter.samples), None),
                "metadata_head": player.stderr[:3000],
                "metadata_tail": player.stderr[-1000:],
            }
            for index in range(4):
                levels = meter.levels(index + .6)
                self.assertGreater(levels[index], .5, diagnostic)
                self.assertEqual(levels.index(max(levels)), index, levels)
            self.assertEqual(meter.levels(4.6), [0] * 4)


if __name__ == "__main__":
    unittest.main()
