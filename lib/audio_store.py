"""Module lib/audio_store: secure local audio export storage for TeraTTS."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import re
import secrets
import stat
import struct
import tempfile
import math
import resource
import signal
import shutil
import subprocess

MAX_FINALIZED_COUNT: int = 20
MAX_TOTAL_BYTES: int = 512 * 1024 * 1024
MAX_WAV_BYTES: int = 256 * 1024 * 1024
MAX_INDEX_BYTES: int = 64 * 1024
MAX_SCAN_ENTRIES: int = 256
MAX_RECOVERED_COUNT: int = 128

SAMPLE_RATE = 44100
CHANNELS = 1
BYTES_PER_SAMPLE = 2
WAV_HEADER_SIZE = 44

ID_RE = re.compile(r"^[0-9a-f]{32}$")
AUDIO_NAME_RE = re.compile(r"^teratts-(\d{8}T\d{6}Z)-([0-9a-f]{32})\.(wav|mp3|ogg)$")
PART_NAME_RE = re.compile(
    r"^teratts-(\d{8}T\d{6}Z)-([0-9a-f]{32})\.(\d+)\.([a-zA-Z0-9_\-]+)(?:\.encoded)?\.part$"
)


class StoreError(Exception):
    """Domain exception with stable code attribute."""

    def __init__(self, message: str, code: str = "io") -> None:
        super().__init__(message)
        self.code = code


def _proc_start_ident(pid: int) -> str:
    try:
        with open(f"/proc/{pid}/stat", "r", encoding="utf-8") as f:
            return f.read().split(")")[-1].split()[19]
    except Exception:
        return "unknown"


def _build_wav_header(pcm_len: int) -> bytes:
    riff_chunk_size = 36 + pcm_len
    byte_rate = SAMPLE_RATE * CHANNELS * BYTES_PER_SAMPLE
    block_align = CHANNELS * BYTES_PER_SAMPLE
    return (
        b"RIFF"
        + struct.pack("<I", riff_chunk_size)
        + b"WAVE"
        + b"fmt "
        + struct.pack("<IHHIIHH", 16, 1, CHANNELS, SAMPLE_RATE, byte_rate, block_align, 16)
        + b"data"
        + struct.pack("<I", pcm_len)
    )


def _validate_wav(path: Path) -> tuple[int, int]:
    st = _verify_regular_owned(path)
    if st.st_size < WAV_HEADER_SIZE or st.st_size > MAX_WAV_BYTES:
        raise StoreError(f"WAV file too small: {path.name}", code="invalid_audio")
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), "rb") as f:
        hdr = f.read(WAV_HEADER_SIZE)
    if len(hdr) != WAV_HEADER_SIZE or hdr[:4] != b"RIFF" or hdr[8:12] != b"WAVE":
        raise StoreError(f"Invalid RIFF/WAVE header in {path.name}", code="invalid_audio")
    if hdr[12:16] != b"fmt " or hdr[36:40] != b"data":
        raise StoreError(f"Malformed chunks in {path.name}", code="invalid_audio")

    _, fmt_size, fmt_code, ch, srate, brate, ba, bps = struct.unpack("<4sIHHIIHH", hdr[12:36])
    (data_bytes,) = struct.unpack("<I", hdr[40:44])
    if (fmt_size, fmt_code, ch, srate, ba, bps) != (16, 1, CHANNELS, SAMPLE_RATE, 2, 16):
        raise StoreError(f"Unsupported WAV format in {path.name}", code="invalid_audio")
    if brate != SAMPLE_RATE * 2 or data_bytes == 0 or data_bytes % 2 != 0:
        raise StoreError(f"Invalid WAV length or byte rate in {path.name}", code="invalid_audio")
    if st.st_size != WAV_HEADER_SIZE + data_bytes:
        raise StoreError(f"File size mismatch in {path.name}", code="invalid_audio")
    if struct.unpack("<I", hdr[4:8])[0] != st.st_size - 8:
        raise StoreError("Invalid RIFF size", code="invalid_audio")

    duration_ms = int(round((data_bytes / (SAMPLE_RATE * 2)) * 1000.0))
    return duration_ms, st.st_size


def _verify_regular_owned(path: Path) -> os.stat_result:
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        raise StoreError(f"File missing: {path.name}", code="file_missing")
    except OSError as e:
        raise StoreError(f"OS error: {e}", code="io")
    if stat.S_ISLNK(st.st_mode):
        raise StoreError(f"Symlinks rejected: {path.name}", code="io")
    if not stat.S_ISREG(st.st_mode):
        raise StoreError(f"Non-regular file rejected: {path.name}", code="io")
    if st.st_uid != os.getuid():
        raise StoreError(f"Wrong ownership on {path.name}", code="io")
    return st


def _size_limit(maximum: int):
    # Export/probe callers are single-threaded. Bound child output on disk,
    # including an encoder that fails to honor its expected bitrate.
    def apply():
        resource.setrlimit(resource.RLIMIT_FSIZE, (maximum, maximum))
        # Preserve EFBIG/quota failure without turning it into a desktop crash.
        # Ignored dispositions survive exec, unlike a Python signal handler.
        signal.signal(signal.SIGXFSZ, signal.SIG_IGN)
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    return apply


def _validate_audio(path: Path, format: str | None = None) -> tuple[int, int]:
    format = format or path.suffix[1:]
    if format == "wav":
        return _validate_wav(path)
    if format not in ("mp3", "ogg"):
        raise StoreError("Unsupported format", "invalid_audio")
    info = _verify_regular_owned(path)
    if not 0 < info.st_size <= MAX_WAV_BYTES:
        raise StoreError("Invalid audio size", "invalid_audio")
    if not shutil.which("ffprobe"):
        raise StoreError("ffprobe is required", "dependency_missing")
    try:
        # An inherited nofollow descriptor keeps the probe on the owned file.
        with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb") as source:
            current = os.fstat(source.fileno())
            if (not stat.S_ISREG(current.st_mode) or current.st_uid != os.getuid()
                    or not 0 < current.st_size <= MAX_WAV_BYTES):
                raise StoreError("Unsafe audio file")
            with tempfile.TemporaryFile(dir=path.parent) as output:
                result = subprocess.run(
                    ["ffprobe", "-v", "error", "-protocol_whitelist", "file", "-format_whitelist", format,
                     "-show_entries", "format=format_name,duration:stream=codec_type,codec_name,sample_rate,channels",
                     "-of", "json", "-i", f"/proc/self/fd/{source.fileno()}"],
                    stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.DEVNULL,
                    pass_fds=(source.fileno(),), preexec_fn=_size_limit(8192), timeout=5)
                output.seek(0)
                raw = output.read(8193)
        if result.returncode or len(raw) > 8192:
            raise ValueError("probe failed")
        data = json.loads(raw)
        streams = data["streams"]
        codec, rate = ("mp3", "44100") if format == "mp3" else ("opus", "48000")
        if (len(streams) != 1 or streams[0].get("codec_type") != "audio"
                or streams[0].get("codec_name") != codec or streams[0].get("sample_rate") != rate
                or streams[0].get("channels") != 1 or data["format"].get("format_name") != format):
            raise ValueError("unexpected audio stream")
        duration = float(data["format"]["duration"])
        if not math.isfinite(duration) or not 0 < duration <= (MAX_WAV_BYTES - 44) / 88200 + 1:
            raise ValueError("invalid duration")
        return round(duration * 1000), current.st_size
    except (OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired) as error:
        raise StoreError("Invalid encoded audio", "invalid_audio") from error


class Store:
    def __init__(self, root: Path) -> None:
        self.root = Path(root).absolute()
        self._lock_path = self.root / ".lock"
        self._index_path = self.root / "index.json"
        self._init_root()
        with self._flock():
            self._cleanup_stale_parts()
            self._ensure_index()

    def _init_root(self) -> None:
        if self.root.is_symlink():
            raise StoreError("Unsafe storage directory")
        if not self.root.exists():
            self.root.mkdir(parents=True, mode=0o700, exist_ok=True)
        st = os.lstat(self.root)
        if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
            raise StoreError("Store root must be a regular directory, not a symlink", code="io")
        if st.st_uid != os.getuid():
            raise StoreError("Store root owned by another user", code="io")
        if (st.st_mode & 0o777) != 0o700:
            os.chmod(self.root, 0o700)

    @contextmanager
    def _flock(self):
        fd = os.open(self._lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
                raise StoreError("Unsafe index lock")
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                os.close(fd)

    def _cleanup_stale_parts(self) -> None:
        # Reclaim abandoned parts before applying the normal directory bound.
        # One bounded pass also handles accumulated files beyond that bound.
        with os.scandir(self.root) as scan:
            entries = []
            for entry in scan:
                if len(entries) >= MAX_SCAN_ENTRIES * 16:
                    break
                entries.append(entry.name)
        for name in entries:
            m = PART_NAME_RE.match(name)
            if not m:
                continue
            path = self.root / name
            pid = int(m.group(3))
            start_id = m.group(4)
            stale = False
            try:
                os.kill(pid, 0)
                if _proc_start_ident(pid) != start_id:
                    stale = True
            except OSError:
                stale = True
            if stale:
                try:
                    _verify_regular_owned(path)
                    path.unlink(missing_ok=True)
                except (OSError, StoreError):
                    pass

    def _list_entries(self) -> list[str]:
        with os.scandir(self.root) as it:
            entries = []
            for entry in it:
                if len(entries) >= MAX_SCAN_ENTRIES:
                    raise StoreError("Store directory entry limit exceeded", code="storage_full")
                entries.append(entry.name)
        return entries

    def _load_index_raw(self) -> list[dict]:
        try:
            items = self._read_index()
        except StoreError as error:
            if error.code != "corrupt_index":
                raise
            # Only corrupt owned regular indexes are repaired. Unsafe paths and
            # I/O failures remain errors; preserve the exact damaged file.
            _verify_regular_owned(self._index_path)
            backup = self.root / (".invalid-index-" + secrets.token_hex(16))
            os.link(self._index_path, backup, follow_symlinks=False)
            self._index_path.unlink()
            return self._recover_index()
        present = []
        for item in items:
            try:
                _verify_regular_owned(self.root / item["filename"])
            except StoreError as error:
                if error.code != "file_missing":
                    raise
            else:
                present.append(item)
        if len(present) != len(items):
            self._save_index(present, recovery=True)
        return present

    def _read_index(self) -> list[dict]:
        if self._index_path.is_symlink():
            raise StoreError("Unsafe index")
        if not self._index_path.exists():
            return self._recover_index()
        st = _verify_regular_owned(self._index_path)
        if (st.st_mode & 0o777) != 0o600:
            os.chmod(self._index_path, 0o600)
        if st.st_size > MAX_INDEX_BYTES:
            raise StoreError("Index file exceeds max size", code="corrupt_index")
        try:
            with os.fdopen(os.open(self._index_path, os.O_RDONLY | os.O_NOFOLLOW), "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, list):
                raise StoreError("Corrupt index schema", code="corrupt_index")
            allowed = {"id", "filename", "createdAt", "durationMs", "bytes", "voice", "rate", "source"}
            if len(data) > MAX_RECOVERED_COUNT:
                raise StoreError("Index count limit exceeded", "storage_full")
            seen = set()
            for item in data:
                if not isinstance(item, dict) or set(item.keys()) != allowed:
                    raise StoreError("Corrupt item in index", code="corrupt_index")
                name = AUDIO_NAME_RE.fullmatch(str(item.get("filename", "")))
                if not name:
                    raise StoreError("Unsafe recording path in index")
                if (not ID_RE.fullmatch(str(item.get("id", ""))) or not name
                        or name.group(2) != item["id"] or item["id"] in seen
                        or type(item["rate"]) not in (int, float)
                        or not math.isfinite(item["rate"]) or not .25 <= item["rate"] <= 4
                        or type(item["bytes"]) is not int or not 0 < item["bytes"] <= MAX_WAV_BYTES
                        or type(item["durationMs"]) is not int or item["durationMs"] < 0
                        or any(not isinstance(item[k], str) or len(item[k]) > 256 for k in ("voice", "source", "createdAt"))):
                    raise StoreError("Invalid index entry", "corrupt_index")
                seen.add(item["id"])
            return data
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            raise StoreError(f"Corrupt index file: {e}", code="corrupt_index")

    def _save_index(self, items: list[dict], *, recovery: bool = False) -> None:
        raw = json.dumps(items, indent=2).encode("utf-8")
        if len(raw) > MAX_INDEX_BYTES:
            raise StoreError("Index file exceeds 64KiB quota", code="storage_full")
        if not recovery and self._current_total_bytes() + len(raw) > MAX_TOTAL_BYTES:
            raise StoreError("Index exceeds total storage quota", code="storage_full")
        fd, name = tempfile.mkstemp(prefix=".index-", dir=self.root)
        tmp = Path(name)
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(raw)
                f.flush()
                os.fsync(fd)
            os.replace(tmp, self._index_path)
        finally:
            tmp.unlink(missing_ok=True)

    def _recover_index(self) -> list[dict]:
        entries = sorted(self._list_entries())
        recovered = []
        seen = set()
        for name in entries:
            m = AUDIO_NAME_RE.match(name)
            if not m:
                continue
            path = self.root / name
            try:
                duration_ms, file_bytes = _validate_audio(path)
            except StoreError:
                continue
            ts_str, item_id = m.group(1), m.group(2)
            try:
                dt = datetime.strptime(ts_str, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
            except ValueError:
                continue
            if item_id in seen:
                # Preserve both recordings; a hard link refuses to overwrite an
                # existing name. A failed index write remains recoverable.
                item_id = secrets.token_hex(16)
                renamed = f"teratts-{ts_str}-{item_id}.{m.group(3)}"
                os.link(path, self.root / renamed, follow_symlinks=False)
                path.unlink()
                name = renamed
            seen.add(item_id)
            recovered.append({
                "id": item_id,
                "filename": name,
                "createdAt": dt.isoformat(),
                "durationMs": duration_ms,
                "bytes": file_bytes,
                "voice": "",
                "rate": 1.0,
                "source": "",
            })
        recovered.sort(key=lambda x: x["createdAt"], reverse=True)
        if len(recovered) > MAX_RECOVERED_COUNT:
            raise StoreError("Recovered file count exceeds quota", code="storage_full")
        self._save_index(recovered, recovery=True)
        return recovered

    def _ensure_index(self) -> None:
        self._load_index_raw()

    def _current_total_bytes(self) -> int:
        total = 0
        for name in self._list_entries():
            p = self.root / name
            try:
                st = os.lstat(p)
                if stat.S_ISREG(st.st_mode) and not stat.S_ISLNK(st.st_mode):
                    total += st.st_size
            except OSError:
                pass
        return total

    def items(self) -> list[dict]:
        with self._flock():
            return [dict(x) for x in self._load_index_raw()]

    def path(self, item_id: str) -> Path:
        if not ID_RE.fullmatch(item_id):
            raise StoreError(f"Invalid item ID: {item_id}", code="invalid_audio")
        with self._flock():
            items = self._load_index_raw()
            matched = [x for x in items if x["id"] == item_id]
            if not matched:
                raise StoreError(f"ID not found: {item_id}", code="file_missing")
            target = self.root / matched[0]["filename"]
            _validate_audio(target)
            return target

    def remove(self, item_id: str) -> None:
        if not ID_RE.fullmatch(item_id):
            raise StoreError(f"Invalid item ID: {item_id}", code="invalid_audio")
        with self._flock():
            items = self._load_index_raw()
            matched = [x for x in items if x["id"] == item_id]
            if not matched:
                return  # An already-missing recording is an idempotent deletion.
            entry = matched[0]
            target = self.root / entry["filename"]
            new_items = [x for x in items if x["id"] != item_id]
            # Commit the list before deleting the recording. Failed index writes
            # leave both file and row intact; failed unlink restores the row.
            try:
                _verify_regular_owned(target)
                self._save_index(new_items, recovery=True)
                target.unlink()
            except StoreError as e:
                if e.code != "file_missing":
                    raise
                self._save_index(new_items, recovery=True)
            except OSError as e:
                self._save_index(items, recovery=True)
                raise StoreError(f"Failed removing file: {e}", code="io")

    def begin(self, voice: str, rate: float, source: str, format: str = "wav") -> ExportWriter:
        if format not in ("wav", "mp3", "ogg"):
            raise StoreError("Unsupported format", "invalid_audio")
        if format != "wav" and (not shutil.which("ffmpeg") or not shutil.which("ffprobe")):
            raise StoreError("ffmpeg and ffprobe are required", "dependency_missing")
        with self._flock():
            items = self._load_index_raw()
            if len(items) >= MAX_FINALIZED_COUNT:
                raise StoreError("Max finalized WAV count reached", code="storage_full")
            if self._current_total_bytes() >= MAX_TOTAL_BYTES:
                raise StoreError("Storage quota reached", code="storage_full")
            item_id = secrets.token_hex(16)
            return ExportWriter(self, item_id, voice, rate, source, format)


class ExportWriter:
    def __init__(self, store: Store, item_id: str, voice: str, rate: float, source: str, format: str) -> None:
        self._store = store
        self._id = item_id
        self._voice = voice
        self._rate = rate
        self._source = source
        self._format = format
        self._now = datetime.now(timezone.utc)
        self._ts = self._now.strftime("%Y%m%dT%H%M%SZ")
        self._created_at = self._now.isoformat()
        self._final_name = f"teratts-{self._ts}-{self._id}.{format}"

        pid = os.getpid()
        start_id = _proc_start_ident(pid)
        self._part_path = store.root / f"teratts-{self._ts}-{self._id}.{pid}.{start_id}.part"
        self._encoded_path = self._part_path.with_suffix(".encoded.part")

        fd = os.open(self._part_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        self._file = open(fd, "wb", closefd=True)
        self._file.write(b"\x00" * WAV_HEADER_SIZE)
        self._file.flush()
        self._pcm_bytes = 0
        self._closed = False

    def add(self, pcm: bytes) -> None:
        if self._closed:
            raise StoreError("Writer is closed", code="io")
        if len(pcm) % 2 != 0:
            raise StoreError("PCM bytes must be 16-bit aligned", code="invalid_audio")
        new_total = self._pcm_bytes + len(pcm) + WAV_HEADER_SIZE
        if new_total > MAX_WAV_BYTES:
            raise StoreError("Single WAV limit exceeded", code="storage_full")
        with self._store._flock():
            if self._store._current_total_bytes() + len(pcm) > MAX_TOTAL_BYTES:
                raise StoreError("Total storage limit exceeded", code="storage_full")
            try:
                self._file.write(pcm)
                self._file.flush()
                self._pcm_bytes += len(pcm)
            except OSError as e:
                raise StoreError(f"Write failure: {e}", code="io")

    def finish(self) -> dict:
        if self._closed:
            raise StoreError("Writer is closed", code="io")
        if self._pcm_bytes == 0:
            self.abort()
            raise StoreError("Cannot finalize empty audio", code="invalid_audio")

        try:
            self._file.seek(0)
            self._file.write(_build_wav_header(self._pcm_bytes))
            self._file.flush()
            os.fsync(self._file.fileno())
            self._file.close()
            self._closed = True
        except OSError as e:
            self.abort()
            raise StoreError(f"Failed finalizing file: {e}", code="io")

        final_path = self._store.root / self._final_name
        try:
            duration_ms, file_bytes = _validate_wav(self._part_path)
            publish_path = self._part_path
            if self._format != "wav":
                self._encode()
                encoded_duration, file_bytes = _validate_audio(self._encoded_path, self._format)
                # Allow codec priming/padding, but reject both truncated and
                # unexpectedly extended output before it reaches the library.
                if abs(encoded_duration - duration_ms) > 100:
                    raise StoreError("Encoded duration mismatch", "invalid_audio")
                duration_ms = encoded_duration
                publish_path = self._encoded_path
        except BaseException:
            self.abort()
            raise

        meta = {
            "id": self._id,
            "filename": self._final_name,
            "createdAt": self._created_at,
            "durationMs": duration_ms,
            "bytes": file_bytes,
            "voice": self._voice,
            "rate": self._rate,
            "source": self._source,
        }

        try:
            with self._store._flock():
                items = self._store._load_index_raw()
                if len(items) >= MAX_FINALIZED_COUNT:
                    raise StoreError("Max finalized audio count exceeded", code="storage_full")
                if self._store._current_total_bytes() > MAX_TOTAL_BYTES:
                    raise StoreError("Total storage limit exceeded", "storage_full")
                os.replace(publish_path, final_path)
                self._part_path.unlink(missing_ok=True)
                items.insert(0, meta)
                try:
                    self._store._save_index(items)
                except BaseException:
                    final_path.unlink(missing_ok=True)
                    raise
        except BaseException:
            self.abort()
            raise
        self.abort()
        return meta

    def _encode(self) -> None:
        with self._store._flock():
            maximum = min(MAX_WAV_BYTES, MAX_TOTAL_BYTES - self._store._current_total_bytes())
        if maximum <= 0:
            raise StoreError("Storage quota reached", "storage_full")
        codec = (["-ar", "44100", "-c:a", "libmp3lame", "-b:a", "128k"] if self._format == "mp3" else
                 ["-ar", "48000", "-c:a", "libopus", "-b:a", "32k", "-application", "voip"])
        fd = os.open(self._encoded_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "wb") as output, os.fdopen(
                os.open(self._part_path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb") as source:
            info = os.fstat(source.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
                raise StoreError("Unsafe encoder input")
            try:
                result = subprocess.run(
                    ["ffmpeg", "-nostdin", "-v", "error", "-protocol_whitelist", "file", "-f", "wav",
                     "-i", f"/proc/self/fd/{source.fileno()}", "-map", "0:a:0", "-map_metadata", "-1", "-ac", "1"]
                    + codec + ["-f", self._format, "pipe:1"],
                    stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.DEVNULL,
                    pass_fds=(source.fileno(),), preexec_fn=_size_limit(maximum), timeout=60)
            except subprocess.TimeoutExpired as error:
                raise StoreError("Audio encoding timed out") from error
            if result.returncode:
                code = "storage_full" if os.fstat(output.fileno()).st_size >= maximum else "io"
                raise StoreError("Audio encoding failed", code)
            output.flush()
            os.fsync(output.fileno())

    def abort(self) -> None:
        if not self._closed:
            try:
                self._file.close()
            except OSError:
                pass
            self._closed = True
        try:
            self._part_path.unlink(missing_ok=True)
            self._encoded_path.unlink(missing_ok=True)
        except OSError:
            pass
