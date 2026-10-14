"""Four RMS frequency bands from mpv's own decoder, aligned to playback time."""
from __future__ import annotations

from collections import OrderedDict
import math
import re
import threading


BANDS = ((80, 300), (300, 1000), (1000, 3000), (3000, 8000))
ZERO = [0.0] * 4
FRAME = re.compile(rb"^frame:\d+\s+pts:-?\d+\s+pts_time:([0-9.eE+-]+)\s*$")
RMS = b"lavfi.astats.Overall.RMS_level="
MARKER = b"teratts.band="


def filter_graph() -> str:
    # Rebatch without padding before the split: every output consumes the same
    # frames. Per-branch rebatching leaves analysis frames queued in older
    # libavfilter/mpv while the audible output continues. PCM is unchanged.
    parts = ["asetnsamples=n=1024:p=0,asplit=5[out][a][b][c][d]"]
    for index, ((low, high), name) in enumerate(zip(BANDS, "abcd")):
        parts.append(
            f"[{name}]highpass=f={low},lowpass=f={high},"
            "astats=metadata=1:reset=1:measure_perchannel=none:measure_overall=RMS_level,"
            f"ametadata=mode=add:key=teratts.band:value={index},"
            "ametadata=mode=print:file='pipe\\:2':direct=1,anullsink")
    return ";".join(parts)


class Meter:
    def __init__(self):
        self.samples = OrderedDict()
        self.lock = threading.Lock()
        self.pts = None
        self.rms = None

    def feed(self, line: bytes) -> None:
        frame = FRAME.fullmatch(line)
        try:
            if frame:
                value = float(frame.group(1))
                self.pts = value if math.isfinite(value) and value >= 0 else None
                self.rms = None
            elif line.startswith(RMS):
                value = float(line[len(RMS):])
                self.rms = (max(0.0, min(1.0, (value + 55) / 43))
                            if math.isfinite(value) else 0.0)
            elif line.startswith(MARKER) and self.pts is not None and self.rms is not None:
                index = int(line[len(MARKER):])
                if not 0 <= index < 4:
                    return
                with self.lock:
                    levels = self.samples.setdefault(self.pts, [None] * 4)
                    levels[index] = round(self.rms, 3)
                    while len(self.samples) > 256:
                        self.samples.popitem(last=False)
        except ValueError:
            self.pts = self.rms = None

    def read(self, stream) -> None:
        while True:
            line = stream.readline(512)
            if not line:
                return
            if line.endswith(b"\n"):
                self.feed(line.strip())

    def levels(self, position: float) -> list[float]:
        with self.lock:
            # Decoder lookahead must not animate bars ahead of what is heard.
            candidates = [pts for pts, levels in self.samples.items()
                          if pts <= position and position - pts <= .25 and None not in levels]
            if not candidates:
                return ZERO.copy()
            return self.samples[max(candidates)].copy()
