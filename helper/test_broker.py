import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import broker
import job_process
import jobs

HELPER = str(Path(__file__).with_name('delegate.py').resolve())
FAKE = str(Path(__file__).with_name('fake_codex.py').resolve())


class BrokerTest(unittest.TestCase):
    def setUp(self):
        os.makedirs('.test' + '-out', exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(prefix='bg-', dir='.test' + '-out')
        self.user_dir = os.path.abspath(self.tmp.name)
        self.state = os.path.relpath(self.tmp.name)
        self.account = Path(self.user_dir) / '.config' / 'model-mod' / 'accounts' / 'test'
        self.account.mkdir(parents=True)
        self.log = Path(self.user_dir) / 'fake.log'
        self.repo = Path(self.user_dir) / 'repo'
        self.repo.mkdir()
        subprocess.run(['git', 'init', '-q', str(self.repo)], check=True)
        self.env = dict(os.environ, HOME=self.user_dir, XDG_STATE_HOME=self.state)
        self.root = os.path.join(self.state, 'model-mod', 'delegate', 'v1')
        self.pids = set()

    def tearDown(self):
        try: self.call('shutdown')
        except Exception: pass
        for _ in range(40):
            if not os.path.exists(broker.paths(self.root)[0]): break
            time.sleep(.05)
        try:
            rows = [json.loads(line) for line in self.log.read_text().splitlines()]
            self.pids.update(row[key] for row in rows for key in ('pid', 'child') if key in row)
        except (OSError, ValueError): pass
        for pid in self.pids:
            self.wait_dead(pid)
        self.tmp.cleanup()

    def ensure(self):
        return subprocess.Popen([sys.executable, HELPER, 'broker-ensure'], env=self.env,
                                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def call(self, method, payload=None):
        with patch.dict(os.environ, self.env, clear=True):
            return broker.connect(self.root, method, payload, timeout=3)

    def client(self, method, payload):
        result = subprocess.run([sys.executable, HELPER, 'client', method], env=self.env,
                                input=json.dumps(payload), text=True, capture_output=True, timeout=5, check=True)
        self.assertEqual(result.stderr, '')
        return json.loads(result.stdout)

    def configure(self, mode):
        (self.account / 'fake_config.json').write_text(json.dumps({'mode': mode, 'log': str(self.log)}))

    def request(self):
        return {'cwd': str(self.repo), 'account': 'test', 'model': 'chat', 'kind': 'rescue',
                'options': {'text': 'unique private prompt'}, 'codexBin': FAKE}

    def submit(self):
        reply = self.client('submit', self.request())
        self.assertTrue(reply.get('ok'), reply)
        return reply['job']['id']

    def wait_state(self, ident, states):
        deadline = time.monotonic() + 6
        while time.monotonic() < deadline:
            record = self.call('status', {'id': ident})['job']
            if record['state'] in states: return record
            time.sleep(.05)
        self.fail('job did not reach %s: %s' % (states, record['state']))

    def fake_pids(self):
        deadline = time.monotonic() + 6
        while time.monotonic() < deadline:
            try:
                rows = [json.loads(line) for line in self.log.read_text().splitlines()]
                pid = next(x['pid'] for x in rows if 'pid' in x)
                child = next(x['child'] for x in rows if 'child' in x)
                self.pids.update((pid, child))
                return pid, child
            except (OSError, ValueError, StopIteration): time.sleep(.05)
        self.fail('fake process did not spawn')

    def wait_dead(self, pid):
        for _ in range(80):
            try: os.kill(pid, 0)
            except ProcessLookupError: return
            time.sleep(.05)
        self.fail('process %s remained alive' % pid)

    def test_ensure_lock_serializes_launch(self):
        launched = []
        active = {}
        class Process:
            pid = 12345
            def poll(self): return None
        def launch(*args, **kwargs):
            time.sleep(.1)
            with open(broker.paths(self.root)[1]) as source: active.update(json.load(source))
            launched.append(True)
            return Process()
        def ping(root, method, timeout):
            if not active: raise OSError('not running')
            return {'ok': True, 'generation': active['generation']}
        with patch.dict(os.environ, self.env, clear=True), patch.object(broker.subprocess, 'Popen', side_effect=launch), \
             patch.object(broker, 'connect', side_effect=ping):
            threads = [threading.Thread(target=broker.ensure) for _ in range(2)]
            for thread in threads: thread.start()
            for thread in threads: thread.join(3)
        self.assertEqual(len(launched), 1)

    def test_ensure_auth_and_result(self):
        self.configure('text')
        first, second = self.ensure(), self.ensure()
        for proc in (first, second):
            out, err = proc.communicate(timeout=3)
            self.assertEqual((proc.returncode, out, err), (0, b'', b''))
        ping = self.call('ping')
        self.assertTrue(ping['ok'])
        sockpath, tokenpath, pidpath, _ = broker.paths(self.root)
        self.assertEqual(os.stat(self.root).st_mode & 0o777, 0o700)
        for path in (sockpath, tokenpath, pidpath): self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
            conn.connect(sockpath)
            conn.sendall(json.dumps({'method': 'ping', 'token': 'wrong', 'generation': ping['generation']}).encode() + b'\n')
            self.assertFalse(json.loads(conn.recv(4096))['ok'])
        reply = self.call('submit', {'request': dict(self.request(), accountsDir='/untrusted')})
        self.assertFalse(reply['ok'])
        self.assertFalse(self.client('submit', dict(self.request(), accountsDir='/untrusted'))['ok'])
        ident = self.submit()
        record = self.wait_state(ident, {'completed', 'failed', 'interrupted'})
        self.assertEqual(record['state'], 'completed')
        self.assertEqual(self.call('result', {'id': ident})['text'], 'hello')
        for suffix in ('.json', '.result'):
            data = Path(self.root, ident + suffix).read_text()
            self.assertNotIn('unique private prompt', data)
            self.assertNotIn(str(self.account), data)
            self.assertEqual(os.stat(Path(self.root, ident + suffix)).st_mode & 0o777, 0o600)

    def test_queued_and_running_cancel(self):
        self.configure('stubborn')
        self.ensure().communicate(timeout=3)
        first, second, queued = self.submit(), self.submit(), self.submit()
        self.wait_state(first, {'running'})
        self.wait_state(second, {'running'})
        self.assertEqual(self.wait_state(queued, {'queued'})['state'], 'queued')
        self.fake_pids()
        self.assertEqual(self.call('cancel', {'id': queued})['job']['state'], 'cancelled')
        self.assertEqual(self.call('cancel', {'id': first})['job']['state'], 'cancelled')
        self.call('cancel', {'id': second})
        for pid in self.pids: self.wait_dead(pid)

    def test_runner_killed_cleans_group(self):
        self.configure('stubborn')
        self.ensure().communicate(timeout=3)
        ident = self.submit()
        record = self.wait_state(ident, {'running'})
        pids = self.fake_pids()
        os.kill(record['runner']['pid'], signal.SIGKILL)
        self.assertEqual(self.wait_state(ident, {'interrupted'})['state'], 'interrupted')
        for pid in pids: self.wait_dead(pid)

    def test_broker_death_and_recovery(self):
        self.configure('stubborn')
        self.ensure().communicate(timeout=3)
        ident = self.submit()
        self.wait_state(ident, {'running'})
        pids = self.fake_pids()
        pid = int(Path(broker.paths(self.root)[2]).read_text())
        os.kill(pid, signal.SIGKILL)
        self.wait_dead(pid)
        for child in pids: self.wait_dead(child)
        self.ensure().communicate(timeout=3)
        record = self.wait_state(ident, {'interrupted'})
        self.assertIn(record['errorCode'], ('possible_leftover', 'broker_restarted'))

    def test_wrong_peer_uid_is_rejected(self):
        left, right = socket.socketpair()
        try:
            with patch.object(broker, 'peer_uid', return_value=os.getuid() + 1):
                broker.Handler(left, None, object())
            right.settimeout(.1)
            with self.assertRaises(socket.timeout): right.recv(10)
        finally:
            left.close()
            right.close()

    def test_recovery_checks_identity(self):
        member = {'pid': 23, 'started': 'expected'}
        for started, group in (('different', 42), ('expected', 43), (None, 42)):
            with patch.object(job_process, 'start_time', return_value=started), \
                 patch.object(job_process.os, 'getpgid', return_value=group), \
                 patch.object(broker, 'terminate_group') as terminate:
                server = object.__new__(broker.Server)
                server.store = unittest.mock.Mock()
                server.store.records.return_value = [{'id': 'a' * 32, 'state': 'running', 'pgid': 42,
                                                       'runner': member, 'appServer': None}]
                server.recover()
                terminate.assert_not_called()
                server.store.transition.assert_called_once_with('a' * 32, 'interrupted', error='possible_leftover')


if __name__ == '__main__': unittest.main()
