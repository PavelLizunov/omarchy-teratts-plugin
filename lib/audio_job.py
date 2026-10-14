"""Run one provider operation. Text arrives only on stdin."""
from dataclasses import replace
import json
import os
from pathlib import Path
import signal
import sys
import re

from audio_player import Player
from audio_runtime import publish
from audio_store import Store, StoreError
from teratts_synthesis import Settings, SynthesisError, clean_text_for_synthesis, iter_audio


def store_root():
    return Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share"))) / "omarchy-teratts/exports"


def main():
    job_id = os.environ.get("TTS_JOB_ID", "")
    writer = None
    try:
        signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
        signal.signal(signal.SIGINT, lambda *_: sys.exit(130))
        mode = os.environ.get("TTS_JOB_KIND", "speech")
        if mode == "preview":
            audio_id = os.environ["TTS_AUDIO_ID"]
            Player(job_id, 1.0, file=Store(store_root()).path(audio_id)).run()
        else:
            raw = sys.stdin.buffer.read(1048577)
            if len(raw) > 1048576:
                raise SynthesisError("input limit exceeded", "invalid_input", 65)
            text = raw.decode("utf-8")
            if mode != "export" and not re.search(r"[a-zA-Z0-9\u0400-\u04FF]", clean_text_for_synthesis(text)):
                return 0
            settings = Settings.from_env()
            if job_id:
                publish(job_id, status="exporting" if mode == "export" else "preparing", phase="synthesis")
            if mode == "export":
                writer = Store(store_root()).begin(settings.voice, settings.rate, os.environ.get("TTS_SOURCE", "selection"),
                                                  os.environ.get("TTS_EXPORT_FORMAT", "wav"))
                for chunk in iter_audio(text, settings, slow_chunks=True):
                    writer.add(chunk.pcm)
                publish(job_id, status="exporting", phase="finalizing")
                entry = writer.finish()
                print(json.dumps(entry, ensure_ascii=False))
            elif os.environ.get("TTS_SILENT") == "1":
                # Keep the old direct-provider payload for quiet health checks.
                for _ in iter_audio(text, settings):
                    pass
            else:
                if not job_id:
                    job_id = "direct-" + str(os.getpid())
                Player(job_id, settings.rate, source=iter_audio(text, replace(settings, rate=1.0))).run()
        if os.environ.get("TTS_JOB_ID"):
            publish(job_id, status="idle", phase=None)
        return 0
    except (SynthesisError, StoreError) as error:
        code = error.code
        if code in ("request_error", "network_error"):
            code = "network"
        if os.environ.get("TTS_JOB_ID"):
            publish(job_id, status="error", errorCode=code, phase=None,
                    errorDetails=getattr(error, "details", {}))
        if os.environ.get("TTS_JOB_ID"):
            print(json.dumps({"errorCode": code, "errorDetails": getattr(error, "details", {})}), file=sys.stderr)
        else:
            print("teratts: " + str(error), file=sys.stderr)
        return getattr(error, "exit_code", 1)
    except (OSError, ValueError):
        if os.environ.get("TTS_JOB_ID"):
            publish(job_id, status="error", errorCode="io", phase=None)
        print('{"errorCode":"io"}', file=sys.stderr)
        return 1
    finally:
        if writer is not None:
            writer.abort()


if __name__ == "__main__":
    sys.exit(main())
