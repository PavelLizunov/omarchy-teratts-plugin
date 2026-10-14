"""Unit tests for lib/audio_store.py."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import os
import sys
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import wave

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

import audio_store  # noqa: E402
from audio_store import Store, StoreError  # noqa: E402


class AudioStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_root = Path(tempfile.mkdtemp(prefix="teratts-test-"))
        self.store_dir = self.tmp_root / "store"
        self.store = Store(self.store_dir)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp_root, ignore_errors=True)

    def _export(self, pcm: bytes = b"\x01\x02" * 60, voice: str = "af_heart", rate: float = 1.0, source: str = "tts") -> dict:
        writer = self.store.begin(voice=voice, rate=rate, source=source)
        writer.add(pcm)
        return writer.finish()

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "audio codecs unavailable")
    def test_real_formats_old_wav_index_and_recovery(self):
        legacy = self._export()
        for format in ("mp3", "ogg"):
            writer = self.store.begin("ru_f1", 1.25, "sample", format)
            writer.add(b"\x00\x10" * 44100)
            meta = writer.finish()
            path = self.store.path(meta["id"])
            self.assertEqual(path.suffix, "." + format)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertLess(abs(meta["durationMs"] - 1000), 100)
        self.assertEqual(len(Store(self.store_dir).items()), 3)
        self.assertTrue(self.store.path(legacy["id"]).exists())
        (self.store_dir / "index.json").unlink()
        self.assertEqual(len(Store(self.store_dir).items()), 3)
        self.assertEqual(list(self.store_dir.glob("*.part")), [])

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "audio codecs unavailable")
    def test_encoded_output_quota_and_encoder_failure_preserve_previous_file(self):
        legacy = self._export()
        writer = self.store.begin("ru_f1", 1, "sample", "mp3")
        writer.add(b"\x00\x10" * 44100)
        with patch.object(audio_store, "MAX_TOTAL_BYTES", self.store._current_total_bytes() + 1024):
            with self.assertRaises(StoreError) as failure:
                writer.finish()
        self.assertEqual(failure.exception.code, "storage_full")
        tools = self.tmp_root / "bin"
        tools.mkdir()
        (tools / "ffmpeg").write_text("#!/bin/sh\nexit 1\n")
        (tools / "ffmpeg").chmod(0o755)
        with patch.dict(os.environ, PATH=str(tools) + os.pathsep + os.environ["PATH"]):
            writer = self.store.begin("ru_f1", 1, "sample", "ogg")
            writer.add(b"\x00\x10" * 44100)
            with self.assertRaises(StoreError) as failure:
                writer.finish()
        self.assertEqual(failure.exception.code, "io")
        self.assertEqual(list(self.store_dir.glob("*.part")), [])
        self.assertEqual([item["id"] for item in self.store.items()], [legacy["id"]])
        self.assertTrue(self.store.path(legacy["id"]).exists())

    def test_unknown_format_does_not_create_parts(self):
        with self.assertRaises(StoreError):
            self.store.begin("ru_f1", 1, "sample", "../escape")
        self.assertEqual(list(self.store_dir.glob("*.part")), [])

    def test_file_limit_reports_error_without_core_signal(self):
        output = self.tmp_root / "limited"
        with output.open("wb") as sink:
            result = subprocess.run([sys.executable, "-c",
                                     "import os\ntry: os.write(1,b'x'*4096); os.write(1,b'x')\n"
                                     "except OSError as e: raise SystemExit(23 if e.errno==27 else 24)"],
                                    stdout=sink, stderr=subprocess.PIPE,
                                    preexec_fn=audio_store._size_limit(1024), timeout=3)
        self.assertEqual(result.returncode, 23, result.stderr)
        self.assertEqual(output.stat().st_size, 1024)

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "audio codecs unavailable")
    def test_successful_but_truncated_encoding_is_not_published(self):
        executable = shutil.which("ffmpeg")
        tools = self.tmp_root / "bin"
        tools.mkdir()
        wrapper = tools / "ffmpeg"
        wrapper.write_text("#!" + sys.executable + "\nimport os,sys\nargs=sys.argv[1:]\n"
                           + "os.execv(" + repr(executable) + ", [" + repr(executable)
                           + "] + args[:-1] + ['-t','0.1',args[-1]])\n")
        wrapper.chmod(0o755)
        with patch.dict(os.environ, PATH=str(tools) + os.pathsep + os.environ["PATH"]):
            writer = self.store.begin("ru_f1", 1, "sample", "mp3")
            writer.add(b"\x00\x10" * 88200)
            with self.assertRaises(StoreError) as failure:
                writer.finish()
        self.assertEqual(failure.exception.code, "invalid_audio")
        self.assertEqual(self.store.items(), [])
        self.assertEqual(list(self.store_dir.glob("*.part")), [])

    def test_merged_wav_from_two_differing_fragments_verified_by_wave(self) -> None:
        frag1 = b"\x10\x01" * 120
        frag2 = b"\xf0\x7f" * 180
        self.assertNotEqual(frag1, frag2)

        writer = self.store.begin(voice="en_us", rate=1.25, source="selection")
        writer.add(frag1)
        writer.add(frag2)
        meta = writer.finish()

        expected_pcm = frag1 + frag2
        self.assertEqual(meta["bytes"], 44 + len(expected_pcm))
        self.assertEqual(meta["voice"], "en_us")
        self.assertEqual(meta["rate"], 1.25)
        self.assertEqual(meta["source"], "selection")

        wav_path = self.store.path(meta["id"])
        with wave.open(str(wav_path), "rb") as wf:
            self.assertEqual(wf.getnchannels(), 1)
            self.assertEqual(wf.getsampwidth(), 2)
            self.assertEqual(wf.getframerate(), 44100)
            self.assertEqual(wf.getnframes(), len(expected_pcm) // 2)
            self.assertEqual(wf.readframes(wf.getnframes()), expected_pcm)

    def test_abort_and_empty_finish_leave_no_artifacts(self) -> None:
        writer = self.store.begin(voice="en_us", rate=1.0, source="test")
        writer.add(b"\x01\x00" * 50)
        self.assertEqual(len(list(self.store_dir.glob("*.part"))), 1)

        writer.abort()
        self.assertEqual(list(self.store_dir.glob("*.part")), [])
        self.assertEqual(list(self.store_dir.glob("*.wav")), [])
        self.assertEqual(self.store.items(), [])

        with self.assertRaises(StoreError) as add_ctx:
            writer.add(b"\x01\x00")
        self.assertEqual(add_ctx.exception.code, "io")

        empty_writer = self.store.begin(voice="en_us", rate=1.0, source="test")
        with self.assertRaises(StoreError) as fin_ctx:
            empty_writer.finish()
        self.assertEqual(fin_ctx.exception.code, "invalid_audio")
        self.assertEqual(list(self.store_dir.glob("*.part")), [])
        self.assertEqual(list(self.store_dir.glob("*.wav")), [])

    def test_quota_refusal_preserves_previous_export(self) -> None:
        first_pcm = b"\x22\x33" * 15
        first_meta = self._export(pcm=first_pcm)

        with patch.object(audio_store, "MAX_WAV_BYTES", 100):
            w = self.store.begin(voice="en_us", rate=1.0, source="quota")
            with self.assertRaises(StoreError) as ctx:
                w.add(b"\x01\x02" * 40)
            self.assertEqual(ctx.exception.code, "storage_full")
            w.abort()

        limit = self.store._current_total_bytes() + 60
        with patch.object(audio_store, "MAX_TOTAL_BYTES", limit):
            w = self.store.begin(voice="en_us", rate=1.0, source="quota")
            with self.assertRaises(StoreError) as ctx:
                w.add(b"\x01\x02" * 20)
            self.assertEqual(ctx.exception.code, "storage_full")
            w.abort()

        with patch.object(audio_store, "MAX_FINALIZED_COUNT", 1):
            with self.assertRaises(StoreError) as ctx:
                self.store.begin(voice="en_us", rate=1.0, source="quota")
            self.assertEqual(ctx.exception.code, "storage_full")

        items = self.store.items()
        self.assertEqual([x["id"] for x in items], [first_meta["id"]])
        with wave.open(str(self.store.path(first_meta["id"])), "rb") as wf:
            self.assertEqual(wf.readframes(wf.getnframes()), first_pcm)

    def test_invalid_ids_and_poisoned_index_cannot_escape_root(self) -> None:
        outside_file = self.tmp_root / "outside.wav"
        outside_file.write_bytes(b"keep-me")

        for bad_id in ("", "../outside.wav", "../../etc/passwd", "a" * 31, "g" * 32):
            with self.assertRaises(StoreError) as p_ctx:
                self.store.path(bad_id)
            self.assertEqual(p_ctx.exception.code, "invalid_audio")
            with self.assertRaises(StoreError) as r_ctx:
                self.store.remove(bad_id)
            self.assertEqual(r_ctx.exception.code, "invalid_audio")

        valid_id = "a" * 32
        poisoned = [{
            "id": valid_id,
            "filename": "../outside.wav",
            "createdAt": "2026-01-01T00:00:00+00:00",
            "durationMs": 10,
            "bytes": 100,
            "voice": "v",
            "rate": 1.0,
            "source": "s",
        }]
        (self.store_dir / "index.json").write_text(json.dumps(poisoned), encoding="utf-8")

        with self.assertRaises(StoreError) as idx_ctx:
            self.store.remove(valid_id)
        self.assertEqual(idx_ctx.exception.code, "io")
        self.assertTrue(outside_file.exists())

    def test_symlink_refusal_for_root_index_and_wav(self) -> None:
        real_dir = self.tmp_root / "real_root"
        real_dir.mkdir()
        sym_root = self.tmp_root / "sym_root"
        sym_root.symlink_to(real_dir)
        with self.assertRaises(StoreError) as root_ctx:
            Store(sym_root)
        self.assertEqual(root_ctx.exception.code, "io")

        meta = self._export()
        wav_in_store = self.store_dir / meta["filename"]
        outside_wav = self.tmp_root / "outside_target.wav"
        wav_in_store.rename(outside_wav)
        wav_in_store.symlink_to(outside_wav)

        with self.assertRaises(StoreError) as wav_ctx:
            self.store.path(meta["id"])
        self.assertEqual(wav_ctx.exception.code, "io")
        with self.assertRaises(StoreError) as rm_ctx:
            self.store.remove(meta["id"])
        self.assertEqual(rm_ctx.exception.code, "io")
        self.assertTrue(outside_wav.exists())

        outside_index = self.tmp_root / "outside_index.json"
        outside_index.write_text("[]", encoding="utf-8")
        index_path = self.store_dir / "index.json"
        index_path.unlink()
        index_path.symlink_to(outside_index)

        with self.assertRaises(StoreError) as idx_ctx:
            self.store.items()
        self.assertEqual(idx_ctx.exception.code, "io")

    def test_delete_entry_and_remove_missing_file_from_index(self) -> None:
        m1 = self._export(pcm=b"\x01\x02" * 50)
        m2 = self._export(pcm=b"\x03\x04" * 50)
        p1 = self.store.path(m1["id"])

        self.store.remove(m1["id"])
        self.assertFalse(p1.exists())
        self.assertEqual([x["id"] for x in self.store.items()], [m2["id"]])
        with self.assertRaises(StoreError) as ctx:
            self.store.path(m1["id"])
        self.assertEqual(ctx.exception.code, "file_missing")

        (self.store_dir / m2["filename"]).unlink()
        with self.assertRaises(StoreError) as ctx2:
            self.store.path(m2["id"])
        self.assertEqual(ctx2.exception.code, "file_missing")

        self.store.remove(m2["id"])
        self.assertEqual(self.store.items(), [])

    def test_recover_if_index_missing_and_preserve_corrupt_index(self) -> None:
        pcm = b"\x07\x08" * 100
        meta = self._export(pcm=pcm, voice="af_sky", rate=1.5, source="cli")
        bogus_wav = self.store_dir / f"teratts-20260101T000000Z-{'f' * 32}.wav"
        bogus_wav.write_bytes(b"corrupt-wav-content")

        index_path = self.store_dir / "index.json"
        index_path.unlink()

        recovered = self.store.items()
        self.assertTrue(index_path.exists())
        self.assertEqual(len(recovered), 1)
        self.assertEqual(recovered[0]["id"], meta["id"])
        self.assertEqual(recovered[0]["bytes"], meta["bytes"])
        with wave.open(str(self.store.path(meta["id"])), "rb") as wf:
            self.assertEqual(wf.readframes(wf.getnframes()), pcm)

        index_path.write_text("{corrupt-json", encoding="utf-8")
        self.assertEqual(self.store.items()[0]["id"], meta["id"])
        backups = list(self.store_dir.glob(".invalid-index-*"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(), "{corrupt-json")
        self.assertEqual(backups[0].stat().st_mode & 0o777, 0o600)

    def test_index_write_failure_preserves_recording_and_row(self):
        meta = self._export()
        path = self.store.path(meta["id"])
        with patch.object(self.store, "_save_index", side_effect=StoreError("injected write failure")):
            with self.assertRaises(StoreError):
                self.store.remove(meta["id"])
        self.assertTrue(path.exists())
        self.assertEqual(self.store.items()[0]["id"], meta["id"])

    def test_recovery_handles_stale_overflow_extra_recordings_and_duplicate_ids(self):
        meta = self._export()
        data = self.store.path(meta["id"]).read_bytes()
        for index in range(300):
            (self.store_dir / f"teratts-20260101T000000Z-{index:032x}.99999999.unknown.part").write_bytes(b"stale")
        for index in range(21):
            (self.store_dir / f"teratts-20260101T000000Z-{index:032x}.wav").write_bytes(data)
        (self.store_dir / meta["filename"].replace(meta["filename"].split('-')[1], "20260101T000001Z")).write_bytes(data)
        (self.store_dir / "index.json").unlink()
        recovered = Store(self.store_dir).items()
        self.assertEqual(len(recovered), 23)
        self.assertEqual(len({item["id"] for item in recovered}), 23)
        self.assertEqual(list(self.store_dir.glob("*.part")), [])
        self.assertEqual(len(Store(self.store_dir).items()), 23)
        with self.assertRaises(StoreError) as failure:
            self.store.begin("ru_f1", 1, "sample")
        self.assertEqual(failure.exception.code, "storage_full")


if __name__ == "__main__":
    unittest.main()
