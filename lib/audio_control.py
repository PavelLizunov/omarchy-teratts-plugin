"""Short control commands and the existing widget's JSON state stream."""
import json
import math
import secrets
import subprocess
import sys
import time

from audio_job import store_root
from audio_runtime import atomic_json, job_lock, player_command, read_json, runtime_dir, snapshot
from audio_store import Store, StoreError


def control(action, value=None):
    with job_lock():
        state = snapshot()
        if not state["busy"] or state["kind"] == "export":
            raise StoreError("no player", "no_player")
        directory = runtime_dir()
        job = read_json(directory / "job.json")
        path = directory / ("p-" + str(job["jobId"])[:12] + ".sock")
        if action == "--playback-seek":
            try:
                seconds = float(value)
            except (TypeError, ValueError):
                raise StoreError("invalid position", "invalid_input")
            if not math.isfinite(seconds) or seconds < 0:
                raise StoreError("invalid position", "invalid_input")
            if state["kind"] != "preview" or not path.exists():
                raise StoreError("no file player", "no_player")
            duration = player_command(path, ["get_property", "duration"])
            if type(duration) not in (int, float) or not math.isfinite(duration) or duration <= 0:
                raise StoreError("unknown duration", "no_player")
            target = min(seconds, duration)
            player_command(path, ["seek", target, "absolute+exact"])
            # mpv's paused audio clock can still subtract queued sink latency.
            # Keep the requested position visible until playback resumes.
            if player_command(path, ["get_property", "pause"]):
                job["pausedSeekMs"] = round(target * 1000)
            else:
                job.pop("pausedSeekMs", None)
            atomic_json(directory / "job.json", job)
        elif action == "--playback-rate":
            try:
                rate = float(value)
            except (TypeError, ValueError):
                raise StoreError("invalid rate", "invalid_input")
            if not math.isfinite(rate) or not .25 <= rate <= 4:
                raise StoreError("invalid rate", "invalid_input")
            if not path.exists():
                raise StoreError("no player", "no_player")
            player_command(path, ["set_property", "speed", rate])
        else:
            paused = (not bool(job.get("pauseRequested")) if action in ("--quick-action", "--pause-toggle")
                      else action == "--pause")
            if path.exists():
                player_command(path, ["set_property", "pause", paused])
            job["pauseRequested"] = paused
            if not paused:
                job.pop("pausedSeekMs", None)
            atomic_json(directory / "job.json", job)
    return {"ok": True}


def show_audio():
    directory = runtime_dir()
    request = {"requestId": secrets.token_hex(8), "tab": "audio", "expires": time.time() + 5}
    with job_lock():
        atomic_json(directory / "ui-request.json", request)
    try:
        result = subprocess.run(["omarchy-shell", "shell", "summon", "io.github.pavellizunov.teratts"],
                                capture_output=True, text=True, timeout=3)
        if result.returncode or result.stdout.strip() != "ok":
            raise StoreError("panel unavailable", "dependency_missing")
    except (OSError, subprocess.TimeoutExpired, StoreError):
        with job_lock():
            if read_json(directory / "ui-request.json").get("requestId") == request["requestId"]:
                (directory / "ui-request.json").unlink(missing_ok=True)
        raise StoreError("panel unavailable", "dependency_missing")
    return {"ok": True}


def main(args):
    action = args[0]
    if action == "--watch-state":
        previous = None
        heartbeat = 0.0
        while True:
            state = snapshot()
            if isinstance(state["positionMs"], int):
                state["positionMs"] = (state["positionMs"] // 500) * 500
            encoded = json.dumps(state, separators=(",", ":"))
            if len(encoded.encode("utf-8")) > 65535:
                encoded = json.dumps({"status":"error", "errorCode":"io", "busy":False,
                                      "speaking":False, "bands":[0, 0, 0, 0]}, separators=(",", ":"))
            now = time.monotonic()
            if encoded != previous or now - heartbeat >= 3:
                print(encoded, flush=True)
                previous = encoded
                heartbeat = now
            time.sleep(.1)
    if action == "--quick-action" and not snapshot()["busy"]:
        return 3  # The shell CLI continues through its selection intake.
    if action in ("--quick-action", "--pause", "--resume", "--pause-toggle", "--playback-rate", "--playback-seek"):
        result = control(action, args[1] if len(args) > 1 else None)
    elif action == "--phase":
        from audio_runtime import publish
        job = read_json(runtime_dir() / "job.json")
        if job:
            publish(job["jobId"], status="exporting" if job["kind"] == "export" else "preparing", phase=args[1])
        return 0
    elif action == "--show-audio":
        result = show_audio()
    elif action == "--consume-ui-request":
        with job_lock():
            path = runtime_dir() / "ui-request.json"
            request = read_json(path, 1024)
            path.unlink(missing_ok=True)
        result = {"tab": "audio" if request.get("tab") == "audio" and
                  isinstance(request.get("expires"), (int, float)) and request["expires"] > time.time() else "voice"}
    elif action == "--audio-list":
        result = Store(store_root()).items()
    elif action in ("--audio-copy", "--audio-delete", "--audio-open-folder", "--audio-path"):
        store = Store(store_root())
        if action == "--audio-open-folder":
            subprocess.run(["xdg-open", str(store.root)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           timeout=3, check=True)
        elif action == "--audio-delete":
            with job_lock():
                job = read_json(runtime_dir() / "job.json")
                if snapshot()["busy"] and job.get("audioId") == args[1]:
                    raise StoreError("file is playing", "busy")
                store.remove(args[1])
        elif action == "--audio-path":
            print(store.path(args[1]))
            return 0
        else:
            uri = (store.path(args[1]).as_uri() + "\r\n").encode()
            subprocess.run(["wl-copy", "--type", "text/uri-list"], input=uri, timeout=3, check=True)
        result = {"ok": True}
    else:
        raise StoreError("invalid action", "invalid_input")
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except StoreError as error:
        print(json.dumps({"errorCode": error.code}), file=sys.stderr)
        sys.exit(75 if error.code == "busy" else 1)
    except (OSError, ValueError, IndexError, subprocess.SubprocessError):
        print('{"errorCode":"io"}', file=sys.stderr)
        sys.exit(1)
