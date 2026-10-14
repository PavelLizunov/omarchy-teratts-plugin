"""Reusable synthesis library for TeraTTS provider."""

from dataclasses import dataclass
import io
import http.client
import json
import math
import os
import re
import time
from typing import Iterator
import urllib.error
import urllib.request
import wave

_ENDPOINT_RE = re.compile(
    r"^(https://[A-Za-z0-9.-]+(:[0-9]{1,5})?|http://(?:127\.0\.0\.1|localhost|\[::1\])(:[0-9]{1,5})?)$"
)


class SynthesisError(Exception):
    """Raised when synthesis fails or input is invalid."""

    def __init__(self, message: str, code: str, exit_code: int = 1, details: dict | None = None):
        super().__init__(message)
        self.code = code
        self.exit_code = exit_code
        self.details = details or {}


@dataclass(frozen=True)
class AudioChunk:
    """PCM audio chunk, guaranteed mono signed 16-bit 44100Hz."""

    pcm: bytes
    frames: int


@dataclass(frozen=True)
class Settings:
    """TeraTTS provider settings."""

    endpoint: str
    token: str
    voice: str
    rate: float
    text_mode: str
    speech_front: bool

    def __post_init__(self):
        cleaned_endpoint = self.endpoint.rstrip("/")
        if not _ENDPOINT_RE.fullmatch(cleaned_endpoint):
            raise SynthesisError("invalid endpoint", code="invalid_input", exit_code=65)
        object.__setattr__(self, "endpoint", cleaned_endpoint)
        if not math.isfinite(self.rate) or not (0.25 <= self.rate <= 4.0):
            raise SynthesisError("rate must be between 0.25 and 4.0", code="invalid_input", exit_code=65)

    @classmethod
    def from_env(cls) -> "Settings":
        endpoint = (
            os.environ.get("TERATTS_ENDPOINT")
            or os.environ.get("TERATTS_URL")
            or ""
        )
        token = (
            os.environ.get("TERATTS_TOKEN")
            or os.environ.get("TERATTS_BEARER_TOKEN")
            or ""
        ).strip()
        voice = os.environ.get("TERATTS_VOICE") or "ru_f1"
        rate_raw = os.environ.get("TERATTS_RATE") or "1.0"
        try:
            rate = float(rate_raw)
        except (ValueError, TypeError) as err:
            raise SynthesisError("invalid rate", code="invalid_input", exit_code=65) from err
        text_mode = os.environ.get("TERATTS_TEXT_MODE") or "russian_only"
        speech_front_raw = os.environ.get("TERATTS_SPEECH_FRONT", "true").lower()
        speech_front = speech_front_raw != "false"
        return cls(
            endpoint=endpoint,
            token=token,
            voice=voice,
            rate=rate,
            text_mode=text_mode,
            speech_front=speech_front,
        )


def clean_text_for_synthesis(text: str, language: str = "ru") -> str:
    # 1. Normalize line breaks
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # 2. Strip non-printable control characters that crash russian_only mode (except \n, \t)
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    # 3. Replace snake_case underscores with spaces so identifiers pronounce cleanly
    text = re.sub(r"(?<=\w)_(?=\w)", " ", text)
    # 4. Normalize case-variant language tags: <RU> -> <ru>, </EN> -> </en>
    text = re.sub(
        r"<(/?)(?:RU|EN)>",
        lambda m: f"<{m.group(1)}{m.group(0)[-3:-1].lower()}>",
        text,
        flags=re.IGNORECASE,
    )
    # 5. Strip other HTML/XML tags (like <br>, <li>, <div>) that trigger server tag validation errors
    tags = r"(?:br|hr|li|ul|ol|div|span|p|a|b|i|strong|em|code|pre|h[1-6]|table|tr|td|th)"
    text = re.sub(r"</?" + tags + r"(?:\s+[^<>]*)?/?>", " ", text, flags=re.IGNORECASE)
    # 6. Convert math comparison operators so bare angle brackets do not confuse tag parser
    operators = {
        "ru": {"<=": "меньше или равно", ">=": "больше или равно", "<": "меньше", ">": "больше"},
        "en": {"<=": "less than or equal to", ">=": "greater than or equal to", "<": "less than", ">": "greater than"},
    }
    active = language
    parts = re.split(r"(</?(?:ru|en)>)", text)
    for index, part in enumerate(parts):
        if part in ("<ru>", "<en>"):
            active = part[1:3]
        elif part in ("</ru>", "</en>"):
            active = language
        else:
            parts[index] = re.sub(r"<=|>=|<|>", lambda m: " " + operators[active][m.group()] + " ", part)
    return "".join(parts)


_LATIN_LOOKALIKES = dict(zip("ABCEHKMOPTXYaceopxy", "АВСЕНКМОРТХУасеорху"))
_CYRILLIC_LOOKALIKES = {value: key for key, value in _LATIN_LOOKALIKES.items()}


def repair_mixed_script_words(text: str) -> str:
    """Repair visual substitutions for Russian speech, not general transliteration."""
    def repair(match):
        word = match.group()
        latin = {c for c in word if "A" <= c <= "Z" or "a" <= c <= "z"}
        cyrillic = {c for c in word if "А" <= c <= "я" or c in "Ёё"}
        if not latin or not cyrillic or set(word) - latin - cyrillic:
            return word
        # Fully confusable mixed words prefer Cyrillic in russian_only mode:
        # Нa → На. A distinctive Latin letter instead preserves brands:
        # Аррlе → Apple, MаcВoоk → MacBook. Genuine mixed names stay intact
        # when neither alphabet can represent the entire word visually.
        if latin <= _LATIN_LOOKALIKES.keys():
            mapping = _LATIN_LOOKALIKES
        elif cyrillic <= _CYRILLIC_LOOKALIKES.keys():
            mapping = _CYRILLIC_LOOKALIKES
        else:
            return word
        return "".join(mapping.get(c, c) for c in word)

    # Split on tag boundaries rather than repeatedly scanning for a closing
    # tag: even malformed input with many unmatched openers stays bounded.
    parts = re.split(r"(<en>|</en>)", text)
    english = False
    for index, part in enumerate(parts):
        if part == "<en>":
            english = True
        elif part == "</en>":
            english = False
        elif not english:
            parts[index] = re.sub(r"[^\W\d_]+", repair, part)
    return "".join(parts)


MAX_SEGMENT_CHARS = 480


def split_text_into_chunks(
    text: str,
    max_chunk: int = MAX_SEGMENT_CHARS,
    first_chunk: int = 240,
    second_chunk: int = 480,
) -> list[str]:
    text = text.strip()
    if not text:
        return []
    tags = re.compile(r"<(/?)(ru|en)>")
    tagged = bool(tags.search(text))
    active = None
    for match in tags.finditer(text):
        closing, language = match.groups()
        if closing:
            if active != language:
                raise ValueError("mismatched language tag")
            active = None
        else:
            if active is not None:
                raise ValueError("nested language tags")
            active = language
    if active is not None:
        raise ValueError("unclosed language tag")
    # The server also caps audio at 180 seconds. Abbreviation expansion can
    # exceed that well before its 2400-character input limit.
    # Prefer sentence/space boundaries; never cut a word to fit a request.
    # A split inside a span needs <xx> plus </xx> (nine characters). Reserve
    # that space in every tagged request, including rate-scaled exports.
    overhead = 9 if tagged else 0
    limit = min(max_chunk, MAX_SEGMENT_CHARS) - overhead
    if limit < 1:
        raise ValueError("segment limit cannot fit language tags")
    first_chunk = max(1, first_chunk - overhead)
    second_chunk = max(1, second_chunk - overhead)
    chunks = []
    while text:
        target = min(limit, first_chunk if not chunks else second_chunk if len(chunks) == 1 else limit)
        if len(text) <= target:
            chunks.append(text)
            break
        sentence = list(re.finditer(r"[.!?…](?=\s)", text[: target + 1]))
        cut = sentence[-1].end() if sentence else 0
        if not cut:
            next_sentence = re.search(r"[.!?…](?=\s)", text[target : limit + 1])
            if next_sentence:
                cut = target + next_sentence.end()
        if not cut:
            cut = text.rfind(" ", 0, target + 1)
        if cut <= 0:
            cut = text.find(" ")
        if cut < 0 and len(text) <= limit:
            chunks.append(text)
            break
        if cut < 0 or cut > limit:
            raise ValueError("word exceeds TeraTTS segment limit")
        chunks.append(text[:cut].strip())
        text = text[cut:].strip()
    if tagged:
        active = None
        for index, chunk in enumerate(chunks):
            prefix = f"<{active}>" if active else ""
            for match in tags.finditer(chunk):
                active = None if match[1] else match[2]
            chunks[index] = prefix + chunk + (f"</{active}>" if active else "")
    return chunks


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, url):
        return None


def iter_audio(
    text: str,
    settings: Settings,
    slow_chunks: bool = False,
) -> Iterator[AudioChunk]:
    language = "en" if settings.voice.startswith("eng_") else "ru"
    cleaned = clean_text_for_synthesis(text, language)
    if settings.voice.startswith("ru_") and settings.text_mode == "russian_only":
        cleaned = repair_mixed_script_words(cleaned)
    if not cleaned.strip() or not re.search(r"[a-zA-Z0-9\u0400-\u04FF]", cleaned):
        raise SynthesisError(
            "text contains no speakable characters",
            code="invalid_input",
            exit_code=65,
        )

    try:
        if slow_chunks:
            factor = min(settings.rate, 1.0)
            mc = max(1, int(round(MAX_SEGMENT_CHARS * factor)))
            fc = max(1, int(round(240 * factor)))
            sc = max(1, int(round(480 * factor)))
            chunks = split_text_into_chunks(cleaned, max_chunk=mc, first_chunk=fc, second_chunk=sc)
        else:
            chunks = split_text_into_chunks(cleaned)
    except ValueError as err:
        raise SynthesisError(str(err), code="invalid_input", exit_code=65) from err

    duration_scale = 1.0 / settings.rate if settings.rate > 0 else 1.0
    duration_scale = max(0.25, min(4.0, duration_scale))
    tts_url = f"{settings.endpoint}/tts"

    headers = {
        "Content-Type": "application/json",
        "User-Agent": "omarchy-tts/1.3.2",
    }
    if settings.token:
        headers["Authorization"] = f"Bearer {settings.token}"

    opener = urllib.request.build_opener(_NoRedirect)

    for segment_index, chunk in enumerate(chunks, 1):
        payload = {
            "text": chunk,
            "voice": settings.voice,
            "language": language,
            "duration_scale": round(duration_scale, 4),
            "speech_front": settings.speech_front,
            "text_mode": "compatible" if language == "en" else settings.text_mode,
        }
        req = urllib.request.Request(
            tts_url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        started = time.monotonic()
        for attempt in (1, 2):
            failure = None
            retryable = False
            try:
                with opener.open(req, timeout=35) as resp:
                    data = resp.read(15_876_045)
                    if len(data) > 15_876_044:
                        raise SynthesisError("WAV response exceeds 180 seconds", "invalid_audio", 74)
                break
            except urllib.error.HTTPError as err:
                status = err.code
                err.close()
                retryable = status in (408, 425, 500, 502, 503, 504)
                code, exit_code = ("unauthorized", 77) if status in (401, 403) else (
                    ("rate_limited", 75) if status == 429 else (
                        ("network_error", 74) if retryable else ("request_error", 1)))
                failure = SynthesisError(f"HTTP {status}", code, exit_code,
                                         {"failureKind": "http", "httpStatus": status})
            except (urllib.error.URLError, TimeoutError, ConnectionError, http.client.HTTPException) as err:
                reason = err.reason if isinstance(err, urllib.error.URLError) else err
                kind = "timeout" if isinstance(reason, TimeoutError) else "transport"
                failure = SynthesisError("network error", "network", 74, {"failureKind": kind})
                retryable = True
            except SynthesisError:
                raise
            except Exception as err:
                raise SynthesisError(f"request error: {type(err).__name__}", "request_error", 1) from None
            failure.details.update(segmentIndex=segment_index, segmentChars=len(chunk), attempts=attempt,
                                   elapsedMs=round((time.monotonic() - started) * 1000))
            if not retryable or attempt == 2:
                raise failure from None
            # Nothing from this segment has been yielded or heard. A single
            # retry cannot repeat previously played audio; group stop cancels it.
            time.sleep(1)

        try:
            with wave.open(io.BytesIO(data), "rb") as audio:
                if (audio.getnchannels(), audio.getsampwidth(), audio.getframerate()) != (1, 2, 44100):
                    raise SynthesisError("unexpected WAV format", code="invalid_audio", exit_code=74)
                frames = audio.getnframes()
                if not 0 < frames <= 44100 * 180:
                    raise SynthesisError("invalid WAV duration", code="invalid_audio", exit_code=74)
                pcm = audio.readframes(frames)
                if len(pcm) != frames * 2:
                    raise SynthesisError("truncated WAV", code="invalid_audio", exit_code=74)
        except SynthesisError:
            raise
        except (EOFError, wave.Error):
            raise SynthesisError("invalid WAV response", code="invalid_audio", exit_code=74) from None

        yield AudioChunk(pcm=pcm, frames=frames)
