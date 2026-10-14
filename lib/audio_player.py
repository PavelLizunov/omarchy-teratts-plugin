"""An mpv player owned by one speech job, with bounded synthesis ahead."""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import queue
import shutil
import socket
import subprocess
import threading
import time

from audio_runtime import job_lock, player_command, publish, read_json, runtime_dir
from audio_meter import Meter, filter_graph
from teratts_synthesis import SynthesisError


class Player:
    def __init__(self, job_id: str, rate: float, source=None, file: Path | None = None):
        if not shutil.which("mpv"):
            raise SynthesisError("mpv is required", "dependency_missing", 127)
        self.job_id = job_id
        self.socket_path = runtime_dir() / ("p-" + job_id[:12] + ".sock")
        self.rate = rate
        self.paused = bool(read_json(runtime_dir() / "job.json").get("pauseRequested"))
        self.position = 0.0
        self.duration = None
        self.buffering = False
        self.core_idle = True
        self.ends: list[int] = []
        self.total_frames = 0
        self.finished = False
        self.failure = None
        self.closed = threading.Event()
        self.chunks = queue.Queue(maxsize=2)
        self.source = source
        self.file = file
        self.meter = Meter()
        args = ["mpv", "--no-config", "--load-scripts=no", "--no-video", "--terminal=no",
                "--input-terminal=no", "--audio-display=no", "--audio-pitch-correction=yes",
                "--msg-level=all=no", "--af=lavfi=[" + filter_graph() + "]",
                "--input-ipc-server=" + str(self.socket_path), "--speed=" + str(rate),
                "--pause=" + ("yes" if self.paused else "no"),
                "--cache=yes", "--cache-secs=1", "--demuxer-readahead-secs=1",
                "--demuxer-max-bytes=8MiB", "--demuxer-max-back-bytes=0", "--cache-pause-initial=no"]
        # Tests use a real timed player without touching the user's audio sink.
        if os.environ.get("TTS_TEST_AUDIO_NULL") == "1":
            args.append("--ao=null")
        if file is None:
            args += ["--demuxer=rawaudio", "--demuxer-rawaudio-rate=44100",
                     "--demuxer-rawaudio-channels=mono", "--demuxer-rawaudio-format=s16le", "-"]
        else:
            args.append(str(file))
        if self.socket_path.exists() or self.socket_path.is_symlink():
            raise SynthesisError("player socket already exists", "io", 1)
        # mpv exits when this inherited IPC connection closes, including when
        # this owner is SIGKILLed. A preview file otherwise keeps playing after
        # its Python parent dies. Pass only the child's end; a duplicated parent
        # end in mpv would keep the connection alive and defeat the guarantee.
        self.lifetime, peer = socket.socketpair()
        try:
            args.append("--input-ipc-client=fd://" + str(peer.fileno()))
            self.process = subprocess.Popen(args, stdin=subprocess.PIPE if file is None else subprocess.DEVNULL,
                                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                                            pass_fds=(peer.fileno(),))
        except BaseException:
            self.lifetime.close()
            raise
        finally:
            peer.close()

    def _produce(self):
        try:
            iterator = iter(self.source)
            while not self.closed.is_set():
                # Admission counts generated fragments until actually played,
                # rather than considering a pipe write to be consumption.
                while (len(self.ends) >= 3 or (self.paused and self.total_frames)) and not self.closed.wait(.05):
                    pass
                if self.closed.is_set():
                    return
                try:
                    chunk = next(iterator)
                except StopIteration:
                    self.finished = True
                    return
                self.total_frames += chunk.frames
                self.ends.append(self.total_frames)
                while not self.closed.is_set():
                    try:
                        self.chunks.put(chunk, timeout=.1)
                        break
                    except queue.Full:
                        continue
        except Exception as error:
            self.failure = error
        finally:
            self.finished = True

    def _monitor(self):
        deadline = time.monotonic() + 3
        while not self.socket_path.exists() and not self.closed.wait(.02):
            if self.process.poll() is not None:
                return
            if time.monotonic() > deadline:
                self.failure = SynthesisError("player IPC startup timed out", "io", 1)
                self.process.terminate()
                return
        try:
            # Serialize with early controls: mpv may have been created after a
            # pause request was latched while its socket did not yet exist.
            with job_lock():
                job = read_json(runtime_dir() / "job.json")
                if job.get("jobId") == self.job_id:
                    self.paused = bool(job.get("pauseRequested"))
                    player_command(self.socket_path, ["set_property", "pause", self.paused])
            with socket.socket(socket.AF_UNIX) as ipc:
                ipc.settimeout(.2)
                ipc.connect(str(self.socket_path))
                props = ("pause", "speed", "time-pos", "duration", "paused-for-cache", "core-idle")
                for index, prop in enumerate(props):
                    ipc.sendall((json.dumps({"command": ["observe_property", index + 1, prop]}) + "\n").encode())
                data = b""
                last = 0.0
                ended = False
                while not self.closed.is_set():
                    try:
                        piece = ipc.recv(16384)
                        if not piece:
                            # After confirmed EOF, mpv may close IPC before its
                            # decoder/audio threads finish shutdown. Keep this
                            # bounded; an unexpected disconnect stays a failure.
                            try:
                                self.process.wait(timeout=2 if ended else .2)
                            except subprocess.TimeoutExpired:
                                raise OSError("player IPC disconnected")
                            break
                        data += piece
                        if len(data) > 65536:
                            raise OSError("mpv response limit")
                    except socket.timeout:
                        pass
                    while b"\n" in data:
                        line, data = data.split(b"\n", 1)
                        event = json.loads(line)
                        if event.get("event") == "end-file" and event.get("reason") == "eof":
                            ended = True
                        if event.get("event") != "property-change":
                            continue
                        name, value = event.get("name"), event.get("data")
                        if name == "pause" and isinstance(value, bool):
                            self.paused = value
                        elif name == "speed" and type(value) in (int, float) and math.isfinite(value) and .25 <= value <= 4:
                            self.rate = value
                        elif name == "time-pos" and type(value) in (int, float) and math.isfinite(value) and value >= 0:
                            self.position = value
                            while self.ends and self.ends[0] <= int(value * 44100):
                                self.ends.pop(0)
                        elif name == "duration" and type(value) in (int, float) and math.isfinite(value) and value >= 0:
                            self.duration = value
                        elif name == "paused-for-cache" and isinstance(value, bool):
                            self.buffering = value
                        elif name == "core-idle" and isinstance(value, bool):
                            self.core_idle = value
                    if time.monotonic() - last >= .1:
                        has_audio = self.file is not None or self.total_frames > 0
                        status = ("paused" if self.paused and has_audio else
                                  "buffering" if self.buffering and has_audio else
                                  "preparing" if self.core_idle else "playing")
                        publish(self.job_id, status=status, phase="synthesis" if status == "preparing" else None,
                                playbackRate=self.rate, positionMs=round(self.position * 1000),
                                bands=self.meter.levels(self.position) if status == "playing" else [0.0] * 4,
                                durationMs=round(self.duration * 1000) if self.duration is not None else None)
                        last = time.monotonic()
        except (OSError, ValueError):
            if not self.closed.is_set() and self.process.poll() is None:
                self.failure = SynthesisError("player monitoring failed", "io", 1)
                # Unblock a raw PCM writer waiting on an unresponsive player.
                self.process.terminate()

    def run(self):
        meter_reader = threading.Thread(target=self.meter.read, args=(self.process.stderr,), daemon=True)
        meter_reader.start()
        monitor = threading.Thread(target=self._monitor, daemon=True)
        monitor.start()
        producer = None
        try:
            if self.file is None:
                producer = threading.Thread(target=self._produce, daemon=True)
                producer.start()
                while self.process.poll() is None:
                    if self.failure:
                        raise self.failure
                    try:
                        chunk = self.chunks.get(timeout=.1)
                    except queue.Empty:
                        if self.finished:
                            break
                        continue
                    self.process.stdin.write(chunk.pcm)
                    self.process.stdin.flush()
                self.process.stdin.close()
                if self.failure:
                    raise self.failure
            while self.process.poll() is None:
                if self.failure:
                    raise self.failure
                time.sleep(.05)
            if self.process.returncode != 0:
                if self.failure:
                    raise self.failure
                raise SynthesisError("audio player failed", "io", 1)
        finally:
            self.closed.set()
            self.lifetime.close()
            if self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait()
            monitor.join(timeout=1)
            meter_reader.join(timeout=1)
            self.process.stderr.close()
            self.socket_path.unlink(missing_ok=True)
