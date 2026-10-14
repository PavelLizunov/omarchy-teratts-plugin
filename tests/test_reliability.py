"""Real CLI transitions and parent-loss regressions, without a desktop audio sink."""
import json
import os
from pathlib import Path
import select
import shutil
import signal
import subprocess
import time
import unittest
from unittest.mock import patch

import test_audio_jobs as fixtures
from audio_runtime import read_json, snapshot


class PlaybackReliability(unittest.TestCase):
    def setUp(self):
        self.case = fixtures.AudioJobs()
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.case.server.frames = 44100 * 20

    def players(self):
        result = []
        for path in Path('/proc').iterdir():
            if not path.name.isdigit():
                continue
            try:
                args = (path / 'cmdline').read_bytes().split(b'\0')
            except OSError:
                continue
            if (args and Path(os.fsdecode(args[0])).name == 'mpv'
                    and any(str(self.case.run_dir).encode() in arg for arg in args)):
                result.append(int(path.name))
        return result

    def playing(self):
        self.case.wait_for(lambda: read_json(self.case.run_dir / 'player.json').get('status') == 'playing')
        self.assertEqual(len(self.players()), 1)

    @unittest.skipUnless(shutil.which('mpv'), 'mpv is unavailable')
    def test_player_exits_when_speech_or_preview_owner_is_killed(self):
        c = self.case
        item = json.loads(c.call('--export-wav', '--raw', 'Saved preview.').stdout)
        for args in [('--raw', 'Live speech.'), ('--audio-preview', item['id'])]:
            with self.subTest(args=args):
                process = c.start(*args)
                self.playing()
                # pidfd keeps cleanup bound to this exact disposable mpv, even
                # if its numeric PID is reused after the intentional failure.
                fd = os.pidfd_open(self.players()[0])
                try:
                    leader = int((c.run_dir / 'pgid').read_text().split()[0])
                    os.kill(leader, signal.SIGKILL)
                    process.communicate(timeout=4)
                    self.assertTrue(select.select([fd], [], [], 3)[0], 'mpv outlived its owner')
                    self.assertEqual(c.call('--stop').returncode, 0)
                    self.assertEqual(self.players(), [])
                    replacement = c.start('--raw', 'Replacement speech.')
                    self.playing()
                    self.assertEqual(c.call('--stop').returncode, 0)
                    replacement.communicate(timeout=3)
                finally:
                    try:
                        signal.pidfd_send_signal(fd, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    os.close(fd)

    @unittest.skipUnless(shutil.which('mpv'), 'mpv is unavailable')
    def test_replacement_and_hotkey_resume_keep_one_job(self):
        c = self.case
        for paused in (False, True):
            with self.subTest(paused=paused):
                first = c.start('--raw', 'First speech.')
                self.playing()
                if paused:
                    self.assertEqual(c.call('--pause').returncode, 0)
                    c.wait_for(lambda: read_json(c.run_dir / 'player.json').get('status') == 'paused')
                first_id = read_json(c.run_dir / 'job.json')['jobId']
                second = c.start('--raw', 'Replacement speech.')
                c.wait_for(lambda: read_json(c.run_dir / 'job.json').get('jobId') not in (None, first_id))
                self.playing()
                job_id = read_json(c.run_dir / 'job.json')['jobId']
                self.assertFalse(read_json(c.run_dir / 'job.json')['pauseRequested'])
                for command, status in [('--pause-toggle', 'paused'), ('--quick-action', 'playing'),
                                        ('--quick-action', 'paused'), ('--pause-toggle', 'playing')]:
                    self.assertEqual(c.call(command).returncode, 0)
                    c.wait_for(lambda: read_json(c.run_dir / 'player.json').get('status') == status)
                    self.assertEqual(read_json(c.run_dir / 'job.json')['jobId'], job_id)
                    self.assertEqual(len(self.players()), 1)
                    with patch.dict(os.environ, TTS_STATE_DIR=str(c.run_dir)):
                        state = snapshot()
                    self.assertEqual(state['pauseRequested'], status == 'paused')
                    self.assertEqual(state['speaking'], status == 'playing')
                c.call('--stop')
                first.communicate(timeout=3)
                second.communicate(timeout=3)
                # Immediate start after Stop must not inherit the paused state.
                third = c.start('--raw', 'After Stop.')
                self.playing()
                self.assertFalse(read_json(c.run_dir / 'job.json')['pauseRequested'])
                c.call('--stop')
                third.communicate(timeout=3)

    def test_stop_refuses_a_reused_owner_identity(self):
        c = self.case
        c.call('--status')
        foreign = subprocess.Popen(['sleep', '10'], start_new_session=True)
        self.addCleanup(foreign.wait)
        self.addCleanup(foreign.terminate)
        (c.run_dir / 'pgid').write_text(f'{foreign.pid} 0\n')
        self.assertEqual(c.call('--stop').returncode, 0)
        self.assertIsNone(foreign.poll())
