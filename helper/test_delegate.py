import json
import os
import signal
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch
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
        records = self.records()
        thread = next(r for r in records if r.get('method') == 'thread/start')
        turn = next(r for r in records if r.get('method') == 'turn/start')
        self.assertEqual(thread['params'], {'serviceName': 'model_mod', 'model': 'chat', 'cwd': str(self.repo),
                                            'sandbox': 'read-only', 'approvalPolicy': 'never', 'ephemeral': True})
        self.assertEqual(turn['params'], {'threadId': '12345678-1234-4234-8234-123456789abc', 'model': 'chat',
                                         'effort': None, 'sandboxPolicy': {'type': 'readOnly', 'networkAccess': False},
                                         'input': [{'type': 'text', 'text': 'test', 'text_elements': []}]})
        approvals = [r for r in records if r.get('id') in ('approval1', 'approval2')]
        self.assertEqual([r['result'] for r in approvals], [{'decision': 'decline'}, {'decision': 'decline'}])
        for mode, ident in [('delegate_unknown', 'unknown1'), ('delegate_unknown_number', 7)]:
            self.log.unlink()
            self.mode(mode)
            with self.assertRaisesRegex(delegate.Failure, 'server request'): delegate.execute(dict(self.request))
            responses = [r for r in self.records() if r.get('id') == ident and 'method' not in r]
            self.assertEqual(responses, [{'id': ident, 'error': {'code': -32601, 'message': 'Unsupported request'}}])
        for mode, error in [('delegate_bad_sandbox', 'sandbox'), ('delegate_filechange', 'fileChange')]:
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

    def test_git_isolation(self):
        flag = self.root / 'flag'
        script = self.root / 'filter'
        script.write_text('#!/bin/sh\necho executed >> "' + str(flag) + '"\ncat\n')
        script.chmod(0o755)
        subprocess.run(['git', '-C', str(self.repo), 'config', 'core.fsmonitor', str(script)], check=True)
        subprocess.run(['git', '-C', str(self.repo), 'config', 'filter.x.clean', str(script)], check=True)
        (self.repo / '.gitattributes').write_text('* filter=x\n')
        (self.repo / 'file').write_text('expected diff\n')
        other = self.root / 'other'
        subprocess.run(['git', 'clone', '-q', str(self.repo), str(other)], check=True)
        (other / 'file').write_text('wrong repository\n')
        with patch.dict(os.environ, {'GIT_DIR': str(other / '.git'), 'SECRET_TOKEN': 'secret'}):
            diff = delegate.diff_for(str(self.repo), None)
            self.assertNotIn('SECRET_TOKEN', delegate.git_env())
            self.assertNotIn('GIT_DIR', delegate.git_env())
        self.assertIn(b'expected diff', diff)
        self.assertNotIn(b'wrong repository', diff)
        self.assertFalse(flag.exists())

    def test_blocked_stdin_times_out(self):
        self.mode('delegate_no_read')
        (self.repo / 'file').write_text('x' * 180000)
        req = dict(self.request, kind='review', options={'adversarial': True, 'text': 'focus'})
        started = time.monotonic()
        with patch.object(delegate, 'TOTAL_SECONDS', 3), patch.object(delegate, 'IDLE_SECONDS', 2):
            with self.assertRaisesRegex(delegate.Failure, 'Timed out; result is incomplete'): delegate.execute(req)
        self.assertLess(time.monotonic() - started, 12)
        pid = next(r['pid'] for r in self.records() if 'pid' in r)
        with self.assertRaises(ProcessLookupError): os.kill(pid, 0)

    @unittest.skipUnless(os.name == 'posix', 'process groups require POSIX')
    def test_stubborn_process_group_reaped(self):
        self.mode('stubborn')
        with patch.object(delegate, 'IDLE_SECONDS', 0.3):
            with self.assertRaisesRegex(delegate.Failure, 'Timed out'): delegate.execute(dict(self.request))
        records = self.records()
        parent = next(r['pid'] for r in records if 'pid' in r)
        child = next(r['child'] for r in records if 'child' in r)
        try:
            for pid in (parent, child):
                for _ in range(100):
                    try: os.kill(pid, 0)
                    except ProcessLookupError: break
                    time.sleep(0.02)
                else: self.fail('process %s survived' % pid)
        finally:
            try: os.killpg(parent, signal.SIGKILL)
            except ProcessLookupError: pass

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
