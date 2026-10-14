"""Synthesis request boundaries preserve language and speakable input."""
import io
import json
from pathlib import Path
import re
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'lib'))
from teratts_synthesis import Settings, SynthesisError, iter_audio
from test_teratts import make_dummy_wav


class LanguageChunkTests(unittest.TestCase):
    def requests(self, text, voice='ru_f1', rate=1):
        sent = []
        def receive(request, timeout):
            sent.append(json.loads(request.data))
            return io.BytesIO(make_dummy_wav(100))
        settings = Settings('https://tts.example.test', '', voice, rate, 'russian_only', True)
        with patch('teratts_synthesis.urllib.request.build_opener') as opener:
            opener.return_value.open.side_effect = receive
            list(iter_audio(text, settings, slow_chunks=rate < 1))
        return sent

    def spans(self, text):
        active = None
        words = []
        for token in re.split(r'(<\/?(?:ru|en)>)', text):
            if token in ('<ru>', '<en>'):
                self.assertIsNone(active, text)
                active = token[1:3]
            elif token in ('</ru>', '</en>'):
                self.assertEqual(active, token[2:4], text)
                active = None
            else:
                words.extend((active, word) for word in token.split())
        self.assertIsNone(active, text)
        return words

    def test_long_language_spans_are_balanced_without_lost_words(self):
        text = 'Начало. <en>' + 'Hello world. ' * 100 + '</en> <ru>' + 'Снова речь. ' * 40 + '</ru> Конец.'
        expected = self.spans(text)
        for rate in (1, .25):
            with self.subTest(rate=rate):
                requests = self.requests(text, rate=rate)
                self.assertGreater(len(requests), 1)
                actual = []
                for item in requests:
                    self.assertLessEqual(len(item['text']), round(480 * rate))
                    actual.extend(self.spans(item['text']))
                self.assertEqual(actual, expected)

    def test_short_language_spans_share_one_request(self):
        text = 'Привет <en>Hello world</en> <ru>мир</ru>.'
        self.assertEqual([x['text'] for x in self.requests(text)], [text])

    def test_invalid_language_tags_fail_before_network(self):
        for text in ('<en>Hello', 'Hello</en>', '<en>Hello</ru>', '<en><ru>Привет</ru></en>'):
            with self.subTest(text=text), patch('teratts_synthesis.urllib.request.build_opener') as opener:
                with self.assertRaises(SynthesisError) as caught:
                    list(iter_audio(text, Settings('https://tts.example.test', '', 'ru_f1', 1, 'russian_only', True)))
                self.assertEqual(caught.exception.code, 'invalid_input')
                opener.assert_not_called()

    def test_operators_follow_voice_and_explicit_language_spans(self):
        english = self.requests('5 < 10 and 12 >= 3', voice='eng_f3')[0]['text']
        self.assertIn('less than', english)
        self.assertIn('greater than or equal to', english)
        self.assertIsNone(re.search('[А-Яа-я]', english))
        mixed = self.requests('5 < 10 <en>12 >= 3</en>')[0]['text']
        self.assertIn('меньше', mixed)
        self.assertIn('<en>12  greater than or equal to  3</en>', mixed)
