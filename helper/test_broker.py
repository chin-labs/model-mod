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

    def test_write_submission(self):
        self.configure('abort')
        self.ensure().communicate(timeout=3)
        request = self.request()
        request['options']['write'] = True
        request['writeRoot'] = os.path.realpath(self.repo)
        request['cwd'] = request['writeRoot']
        for changes in ({'writeRoot': '/'}, {'writeRoot': 5}, {'extra': True}):
            self.assertFalse(self.client('submit', dict(request, **changes))['ok'])
        for value in ('true', 1, None):
            invalid = dict(request, options={'text': 'task', 'write': value})
            self.assertFalse(self.client('submit', invalid)['ok'])
        first = self.client('submit', request)
        self.assertTrue(first['ok'], first)
        self.assertEqual(first['job']['mode'], 'write')
        second = self.client('submit', request)
        self.assertFalse(second['ok'])
        self.assertIn('Only one write job', second['error'])
        self.call('cancel', {'id': first['job']['id']})

    def test_ensure_lock_serializes_launch(self):
        first, second = self.ensure(), self.ensure()
        for proc in (first, second):
            self.assertEqual(proc.communicate(timeout=3), (b'', b''))
            self.assertEqual(proc.returncode, 0)
        self.assertTrue(self.call('ping')['ok'])

    def test_ensure_with_locked_instance(self):
        import fcntl
        jobs.Store(self.root)
        path = os.path.join(self.root, '.instance.lock')
        fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with patch.dict(os.environ, self.env, clear=True), patch.object(broker.subprocess, 'Popen') as launch:
                broker.ensure()
                launch.assert_not_called()
            self.assertFalse(os.path.exists(broker.paths(self.root)[1]))
        finally:
            os.close(fd)

    def test_stopped_broker_and_duplicate_start(self):
        self.configure('delegate_delay')
        self.ensure().communicate(timeout=3)
        ident = self.submit()
        self.wait_state(ident, {'running'})
        sockpath, tokenpath, pidpath, _ = broker.paths(self.root)
        pid = int(Path(pidpath).read_text())
        original_token = Path(tokenpath).read_bytes()
        original_socket = os.stat(sockpath).st_ino
        os.kill(pid, signal.SIGSTOP)
        try:
            self.assertEqual(self.ensure().communicate(timeout=3), (b'', b''))
            self.assertEqual(Path(tokenpath).read_bytes(), original_token)
            self.assertEqual(int(Path(pidpath).read_text()), pid)
            duplicate = subprocess.run([sys.executable, HELPER, 'broker'], env=self.env, capture_output=True, timeout=3)
            self.assertEqual(duplicate.returncode, 0)
            self.assertEqual(os.stat(sockpath).st_ino, original_socket)
            self.assertEqual(Path(tokenpath).read_bytes(), original_token)
        finally:
            os.kill(pid, signal.SIGCONT)
        self.assertEqual(self.wait_state(ident, {'completed', 'interrupted', 'failed'})['state'], 'completed')

    def test_concurrent_broker_start(self):
        jobs.Store(self.root)
        tokenpath = broker.paths(self.root)[1]
        credentials = {'token': 'test-token', 'generation': 'test-generation'}
        jobs.atomic_write(tokenpath, json.dumps(credentials).encode())
        procs = [subprocess.Popen([sys.executable, HELPER, 'broker'], env=self.env,
                                  stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                 for _ in range(2)]
        try:
            deadline = time.monotonic() + 4
            while time.monotonic() < deadline:
                if sum(proc.poll() is None for proc in procs) == 1 and os.path.exists(broker.paths(self.root)[0]): break
                time.sleep(.02)
            self.assertEqual(sum(proc.poll() is None for proc in procs), 1)
            self.assertEqual([proc.returncode for proc in procs if proc.poll() is not None], [0])
            self.assertEqual(json.loads(Path(tokenpath).read_text()), credentials)
            self.assertTrue(self.call('ping')['ok'])
        finally:
            try: self.call('shutdown')
            except (OSError, ValueError): pass
            for proc in procs:
                try: proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.terminate()
                    proc.wait(timeout=3)

    def test_user_errors(self):
        self.configure('abort')
        self.ensure().communicate(timeout=3)
        self.assertEqual(self.client('status', {'id': 'f' * 32})['error'], 'Job not found.')
        self.assertEqual(self.client('submit', dict(self.request(), account='BAD NAME'))['error'], 'Invalid account.')
        ids = [self.submit() for _ in range(7)]
        self.assertEqual(self.client('result', {'id': ids[0]})['error'], 'No result is available.')
        self.assertEqual(self.client('submit', self.request())['error'], 'Account queue is full; wait for a job to start.')
        for ident in ids: self.call('cancel', {'id': ident})

    def test_bad_records_do_not_stop_other_jobs(self):
        self.configure('delegate_delay')
        store = jobs.Store(self.root)
        valid = store.create(str(self.repo), 'test', 'chat', None, 'rescue', 'read-only', 'generation')
        samples = [dict(valid, state=[]), dict(valid, updatedAt='old'), '{broken', '[' * 200000, 'x' * 1_000_001]
        for index, sample in enumerate(samples):
            ident = '%032x' % (index + 1)
            if isinstance(sample, dict): sample = json.dumps(dict(sample, id=ident))
            Path(store.path(ident, '.json')).write_text(sample)
        self.ensure().communicate(timeout=3)
        first, second = self.submit(), self.submit()
        self.wait_state(first, {'running'})
        self.wait_state(second, {'running'})
        Path(store.path(first, '.json')).write_text('{broken')
        self.assertEqual(self.wait_state(second, {'completed', 'failed', 'interrupted'})['state'], 'completed')
        self.assertTrue(self.call('ping')['ok'])
        self.call('shutdown')
        for _ in range(60):
            if not os.path.exists(broker.paths(self.root)[0]): break
            time.sleep(.05)
        self.assertFalse(os.path.exists(broker.paths(self.root)[0]))

    def test_normal_cancel_and_shutdown(self):
        self.configure('abort')
        self.ensure().communicate(timeout=3)
        first = self.submit()
        self.wait_state(first, {'running'})
        self.assertIsNone(self.call('cancel', {'id': first})['job']['errorCode'])
        second = self.submit()
        self.wait_state(second, {'running'})
        pid = int(Path(broker.paths(self.root)[2]).read_text())
        os.kill(pid, signal.SIGTERM)
        self.wait_dead(pid)
        record = jobs.Store(self.root).resolve(second)
        self.assertEqual((record['state'], record['errorCode']), ('interrupted', 'broker_stopped'))

    def test_reaped_child_permission_error(self):
        proc = unittest.mock.Mock()
        proc.poll.return_value = 0
        with patch.object(broker.os, 'killpg', side_effect=[None, PermissionError]), patch.object(broker.time, 'sleep'):
            self.assertTrue(broker.terminate_group(123, proc))
        with patch.object(broker.os, 'killpg', side_effect=[None, PermissionError]), patch.object(broker.time, 'sleep'):
            self.assertFalse(broker.terminate_group(123))

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
        self.assertIsNone(record['errorCode'])
        self.assertEqual(self.call('result', {'id': ident})['text'], 'hello')
        for suffix in ('.json', '.result'):
            data = Path(self.root, ident + suffix).read_text()
            self.assertNotIn('unique private prompt', data)
            self.assertNotIn(str(self.account), data)
            self.assertEqual(os.stat(Path(self.root, ident + suffix)).st_mode & 0o777, 0o600)

    def test_redacts_echoed_input(self):
        self.configure('delegate_echo')
        subprocess.run(['git', '-C', str(self.repo), 'config', 'user.name', 'Test'], check=True)
        subprocess.run(['git', '-C', str(self.repo), 'config', 'user.email', 'test@example.invalid'], check=True)
        path = self.repo / 'file'
        path.write_text('original\n')
        subprocess.run(['git', '-C', str(self.repo), 'add', 'file'], check=True)
        subprocess.run(['git', '-C', str(self.repo), 'commit', '-qm', 'initial'], check=True)
        path.write_text('unique private diff\n')
        self.ensure().communicate(timeout=3)
        request = self.request()
        request.update(kind='review', options={'adversarial': True, 'text': 'unique private prompt for redaction testing'})
        reply = self.client('submit', request)
        self.assertTrue(reply['ok'])
        ident = reply['job']['id']
        self.assertEqual(self.wait_state(ident, {'completed', 'failed'})['state'], 'completed')
        for suffix in ('.json', '.result'):
            data = Path(self.root, ident + suffix).read_text()
            for private in ('unique private prompt', 'unique private diff', str(self.account)):
                self.assertNotIn(private, data)

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

    def test_per_job_write_failure_is_isolated(self):
        server = object.__new__(broker.Server)
        server.store = unittest.mock.Mock()
        server.store.records.return_value = [
            {'id': ident, 'state': 'running', 'pgid': None, 'runner': None, 'appServer': None}
            for ident in ('a' * 32, 'b' * 32)]
        server.store.transition.side_effect = [OSError('disk'), True]
        server.recover()
        self.assertEqual(server.store.transition.call_count, 2)
        server.guard = threading.RLock()
        server.children = {ident: {'proc': unittest.mock.Mock(pid=index, poll=lambda: 0), 'cancel': False}
                           for index, ident in enumerate(('a' * 32, 'b' * 32), 10)}
        server.pending = {}
        server.last_cleanup = server.last_ipc = time.monotonic()
        server.stopping = False
        server.store.resolve.return_value = {'state': 'running'}
        server.store.transition.reset_mock(side_effect=True)
        server.store.transition.side_effect = [OSError('disk'), True]
        with patch.object(broker, 'terminate_group', return_value=True): server.tick()
        self.assertEqual(server.store.transition.call_count, 2)
        self.assertEqual(server.children, {})
        server.root = self.root
        jobs.Store(self.root)
        server.server_close = unittest.mock.Mock()
        for path in broker.paths(self.root)[:3]: Path(path).touch()
        server.pending = {'c' * 32: {}, 'd' * 32: {}}
        server.store.transition.reset_mock(side_effect=True)
        server.store.transition.side_effect = [OSError('disk'), True]
        server.finish()
        self.assertEqual(server.store.transition.call_count, 2)
        for path in broker.paths(self.root)[:3]: self.assertFalse(os.path.exists(path))

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
