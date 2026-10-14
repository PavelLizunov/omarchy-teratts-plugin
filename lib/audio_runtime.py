"""Private job state shared by the CLI and its owned player."""
from __future__ import annotations

from contextlib import contextmanager
import fcntl
import json
import math
import os
from pathlib import Path
import socket
import stat
import tempfile
import time


def runtime_dir() -> Path:
    if os.environ.get("TTS_STATE_DIR"):
        return Path(os.environ["TTS_STATE_DIR"])
    if os.environ.get("XDG_RUNTIME_DIR"):
        return Path(os.environ["XDG_RUNTIME_DIR"]) / "omarchy-tts"
    return Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state"))) / "omarchy-tts/run"


def read_json(path: Path, maximum: int = 16384) -> dict:
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
                return {}
            data = stream.read(maximum + 1)
        value = json.loads(data) if len(data) <= maximum else {}
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def atomic_json(path: Path, value: dict) -> None:
    data = (json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n").encode()
    if len(data) > 16384:
        raise ValueError("state limit")
    fd, name = tempfile.mkstemp(prefix=".state-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


@contextmanager
def job_lock():
    fd = os.open(runtime_dir() / "speech.lock", os.O_CREAT | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
            raise OSError("unsafe lock")
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def owner_live(path: Path) -> bool:
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_size > 256:
                return False
            raw = stream.read(257)
        if len(raw) > 256:
            return False
        pid, start = raw.decode("utf-8").strip().split()
        if not pid.isdigit() or int(pid) < 2:
            return False
        fields = Path(f"/proc/{pid}/stat").read_text().rsplit(") ", 1)[1].split()
        return fields[19] == start and fields[2] == pid
    except (OSError, ValueError, IndexError):
        return False


def snapshot() -> dict:
    directory = runtime_dir()
    job = read_json(directory / "job.json")
    state = read_json(directory / "player.json")
    live = owner_live(directory / "pgid") or owner_live(directory / "preparing")
    result = {"schemaVersion": 1, "provider": "teratts", "jobId": None,
              "kind": None, "audioId": None, "status": "idle", "phase": None, "pauseRequested": False,
              "playbackRate": None, "positionMs": None, "durationMs": None,
              "errorCode": None, "busy": False, "speaking": False, "bands": [0.0] * 4}
    if job and (live or (state.get("jobId") == job.get("jobId") and state.get("status") == "error")):
        result.update({key: job.get(key) for key in ("jobId", "kind", "pauseRequested")})
        if result["kind"] == "preview":
            result["audioId"] = job.get("audioId")
        result["status"] = "exporting" if job.get("kind") == "export" else "preparing"
        result["phase"] = "capture"
        if state.get("jobId") == job.get("jobId"):
            for key in ("status", "phase", "playbackRate", "positionMs", "durationMs", "errorCode", "errorDetails"):
                if key in state:
                    result[key] = state[key]
        result["busy"] = live
        if (result["kind"] == "preview" and result["status"] == "paused"
                and type(job.get("pausedSeekMs")) is int and job["pausedSeekMs"] >= 0):
            result["positionMs"] = job["pausedSeekMs"]
        result["speaking"] = result["status"] == "playing" and live
        bands = state.get("bands") if state.get("jobId") == job.get("jobId") else None
        if (result["speaking"] and not result["pauseRequested"] and isinstance(bands, list)
                and len(bands) == 4 and all(type(n) in (int, float) and math.isfinite(n) for n in bands)):
            result["bands"] = [max(0.0, min(1.0, n)) for n in bands]
    root = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share"))) / "omarchy-teratts/exports"
    try:
        result["audioRevision"] = str((root / "index.json").stat().st_mtime_ns)
    except OSError:
        result["audioRevision"] = "0"
    return result


def publish(job_id: str, **changes) -> None:
    # Never let a finished worker overwrite the state of its replacement.
    directory = runtime_dir()
    with job_lock():
        if read_json(directory / "job.json").get("jobId") != job_id:
            return
        state = read_json(directory / "player.json")
        if state.get("jobId") != job_id:
            state = {"jobId": job_id}
        state.update(changes)
        atomic_json(directory / "player.json", state)


def player_command(path: Path, command: list, timeout: float = .3):
    info = path.lstat()
    if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid():
        raise OSError("unsafe player socket")
    with socket.socket(socket.AF_UNIX) as client:
        client.settimeout(timeout)
        client.connect(str(path))
        client.sendall((json.dumps({"command": command, "request_id": 1}) + "\n").encode())
        pending = b""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            piece = client.recv(16384)
            if not piece:
                raise OSError("player disconnected")
            pending += piece
            if len(pending) > 65536:
                raise OSError("player response limit")
            while b"\n" in pending:
                line, pending = pending.split(b"\n", 1)
                value = json.loads(line)
                if value.get("request_id") == 1:
                    if value.get("error") != "success":
                        raise OSError("player command failed")
                    return value.get("data")
    raise OSError("player timeout")
