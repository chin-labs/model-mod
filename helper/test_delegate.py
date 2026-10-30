import json
import os
import signal
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

import delegate

FAKE = str(Path(__file__).with_name('fake_codex.py').resolve())
HELPER = str(Path(__file__).with_name('delegate.py').resolve())


class DelegateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='model-mod-delegate-test-')
        self.root = Path(self.tmp.name)
        self.account_dir = self.root / 'accounts' / 'test'
        self.account_dir.mkdir(parents=True)
        self.log = self.root / 'log'
        self.repo = self.root / 'repo'
        self.repo.mkdir()
        subprocess.run(['git', 'init', '-q', str(self.repo)], check=True)
        subprocess.run(['git', '-C', str(self.repo), 'config', 'user.name', 'Test'], check=True)
        subprocess.run(['git', '-C', str(self.repo), 'config', 'user.email', 'test@example.invalid'], check=True)
        (self.repo / 'file').write_text('original\n')
        subprocess.run(['git', '-C', str(self.repo), 'add', 'file'], check=True)
        subprocess.run(['git', '-C', str(self.repo), 'commit', '-qm', 'initial'], check=True)
        self.request = {'kind': 'rescue', 'options': {'text': 'test'}, 'account': 'test',
                        'accountsDir': str(self.account_dir.parent), 'directory': str(self.account_dir),
                        'codexBin': FAKE, 'model': 'chat', 'cwd': str(self.repo)}

    def tearDown(self):
        self.tmp.cleanup()

    def mode(self, mode):
        (self.account_dir / 'fake_config.json').write_text(json.dumps({'mode': mode, 'log': str(self.log)}))

    def records(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []

    def test_protocol_safety(self):
        self.mode('delegate_approval')
        self.assertEqual(delegate.execute(dict(self.request)), 'hello')
        approvals = [r for r in self.records() if r.get('id') in ('approval1', 'approval2')]
        self.assertEqual([r['result'] for r in approvals], [{'decision': 'decline'}, {'decision': 'decline'}])
        for mode, error in [('delegate_unknown', 'server request'), ('delegate_bad_sandbox', 'sandbox'), ('delegate_filechange', 'fileChange')]:
            self.mode(mode)
            with self.assertRaisesRegex(delegate.Failure, error): delegate.execute(dict(self.request))

    def test_timeout_and_cancel_reap_app_server(self):
        self.mode('abort')
        old = delegate.IDLE_SECONDS
        delegate.IDLE_SECONDS = 0.15
        try:
            with self.assertRaisesRegex(delegate.Failure, 'Timed out'): delegate.execute(dict(self.request))
        finally:
            delegate.IDLE_SECONDS = old
        pid = next(r['pid'] for r in self.records() if 'pid' in r)
        with self.assertRaises(ProcessLookupError): os.kill(pid, 0)
        self.log.unlink()
        proc = subprocess.Popen(['python3', HELPER], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        proc.stdin.write(json.dumps(self.request)); proc.stdin.close()
        for _ in range(100):
            if any(r.get('method') == 'turn/start' for r in self.records()): break
            time.sleep(0.02)
        pid = next(r['pid'] for r in self.records() if 'pid' in r)
        proc.send_signal(signal.SIGTERM)
        self.assertIn('Cancelled', proc.stdout.read())
        self.assertEqual(proc.wait(timeout=5), 0)
        proc.stdout.close()
        with self.assertRaises(ProcessLookupError): os.kill(pid, 0)

    def test_output_clean_and_truncate(self):
        self.mode('delegate_long')
        result = delegate.execute(dict(self.request))
        self.assertNotIn('\x1b', result)
        self.assertNotIn('\x01', result)
        self.assertIn('truncated', result)

    def test_adversarial_diffs(self):
        req = dict(self.request, kind='review', options={'adversarial': True, 'text': 'focus'})
        self.mode('text')
        self.assertIn('No changes', delegate.execute(req))
        self.assertFalse(self.log.exists())
        (self.repo / 'file').write_text('x' * (delegate.MAX_DIFF + 1000))
        with self.assertRaisesRegex(delegate.Failure, 'size limit'): delegate.execute(req)
        (self.repo / 'file').write_text('changed\n')
        self.assertEqual(delegate.execute(req), 'hello')
        turn = next(r for r in self.records() if r.get('method') == 'turn/start')
        self.assertIn('+changed', turn['params']['input'][0]['text'])
        with self.assertRaisesRegex(delegate.Failure, 'Invalid base ref'): delegate.diff_for(str(self.repo), 'main;touch x')


if __name__ == '__main__': unittest.main()
