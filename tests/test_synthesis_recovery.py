"""Retry only unheard segments and keep diagnostics free of request payloads."""
from pathlib import Path
import io
import json
from dataclasses import replace
import sys
import unittest
from unittest.mock import patch
import urllib.error

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
from teratts_synthesis import Settings, SynthesisError, iter_audio
from test_teratts import make_dummy_wav


class SynthesisRecoveryTests(unittest.TestCase):
    settings = Settings("https://tts.example.test", "private-token", "ru_f1", 1, "russian_only", True)

    def run_request(self, replies):
        stack = self.enterContext(patch("teratts_synthesis.urllib.request.build_opener"))
        stack.return_value.open.side_effect = replies
        self.enterContext(patch("teratts_synthesis.time.sleep"))
        return stack.return_value.open

    def test_transient_second_segment_retries_without_repeating_first(self):
        self.enterContext(patch("teratts_synthesis.split_text_into_chunks", return_value=["First.", "Second."]))
        transient = urllib.error.HTTPError("private-url", 503, "private-body", {}, io.BytesIO())
        request = self.run_request([io.BytesIO(make_dummy_wav(100)), transient,
                                    io.BytesIO(make_dummy_wav(200))])
        result = list(iter_audio("Private source", self.settings))
        self.assertEqual([item.frames for item in result], [100, 200])
        self.assertEqual(request.call_count, 3)
        self.assertEqual(request.call_args_list[1].args[0].data, request.call_args_list[2].args[0].data)

    def test_permanent_transport_failure_has_bounded_private_diagnostics(self):
        request = self.run_request([urllib.error.URLError(TimeoutError("private detail"))] * 2)
        with self.assertRaises(SynthesisError) as failure:
            list(iter_audio("Private source", self.settings))
        self.assertEqual(request.call_count, 2)
        details = failure.exception.details
        self.assertEqual(details["failureKind"], "timeout")
        self.assertEqual(details["attempts"], 2)
        self.assertEqual(details["segmentIndex"], 1)
        self.assertEqual(details["segmentChars"], len("Private source"))
        self.assertNotIn("private", str(details).lower())

    def test_auth_and_rate_limits_do_not_retry(self):
        for status, code in ((401, "unauthorized"), (429, "rate_limited")):
            with self.subTest(status=status):
                error = urllib.error.HTTPError("private-url", status, "private", {}, io.BytesIO())
                with patch("teratts_synthesis.urllib.request.build_opener") as opener:
                    opener.return_value.open.side_effect = error
                    with self.assertRaises(SynthesisError) as failure:
                        list(iter_audio("Private source", self.settings))
                    self.assertEqual(opener.return_value.open.call_count, 1)
                    self.assertEqual(failure.exception.code, code)
                    self.assertEqual(failure.exception.details["httpStatus"], status)

    def test_invalid_audio_does_not_retry(self):
        request = self.run_request([io.BytesIO(b"not audio")])
        with self.assertRaises(SynthesisError) as failure:
            list(iter_audio("Private source", self.settings))
        self.assertEqual(request.call_count, 1)
        self.assertEqual(failure.exception.code, "invalid_audio")

    def test_expanding_text_finishes_without_resending_or_losing_words(self):
        # Model the observed independent audio-duration limit: abbreviations
        # take much longer to speak than their raw character count suggests.
        text = ("HTTP API CPU GPU. " * 112).strip()
        for rate, exporting in ((1, False), (.25, True)):
            with self.subTest(rate=rate, exporting=exporting):
                received = []

                def response(request, timeout):
                    payload = json.loads(request.data)
                    seconds = len(payload["text"].split()) * .9 * payload["duration_scale"]
                    if seconds > 180:
                        raise urllib.error.HTTPError("private-url", 500, "private-body", {}, io.BytesIO())
                    received.append(payload["text"])
                    return io.BytesIO(make_dummy_wav(100))

                with patch("teratts_synthesis.urllib.request.build_opener") as opener, \
                        patch("teratts_synthesis.time.sleep"):
                    opener.return_value.open.side_effect = response
                    result = list(iter_audio(text, replace(self.settings, rate=rate), slow_chunks=exporting))
                self.assertEqual(" ".join(received), text)
                self.assertEqual(len(result), len(received))
                self.assertEqual(opener.return_value.open.call_count, len(received))


if __name__ == "__main__":
    unittest.main()
