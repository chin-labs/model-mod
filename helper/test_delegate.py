import ast
import json
import os
import signal
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from pathlib import Path

import delegate
import image

FAKE = str(Path(__file__).with_name('fake_codex.py').resolve())
HELPER = str(Path(__file__).with_name('delegate.py').resolve())


class DelegateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='model-mod-delegate-test-')
        self.root = Path(self.tmp.name).resolve()
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

    def test_background_limits_and_codes(self):
        from bridge import BridgeError
        self.assertEqual((delegate.TOTAL_SECONDS, delegate.IDLE_SECONDS), (300, 120))
        self.assertEqual((delegate.BACKGROUND_TOTAL_SECONDS, delegate.BACKGROUND_IDLE_SECONDS), (1800, 300))
        self.mode('abort')
        with patch.object(delegate, 'BACKGROUND_IDLE_SECONDS', .1):
            with self.assertRaises(delegate.Failure) as caught:
                delegate.execute(dict(self.request), own_group=False)
        self.assertEqual(caught.exception.code, 'idle_timeout')
        self.assertIn('Background jobs', str(caught.exception))
        self.assertNotIn('future background', str(caught.exception))
        app = object.__new__(delegate.App)
        app.background = True
        app.deadline = time.monotonic() - 1
        with self.assertRaises(delegate.Failure) as caught: app.next()
        self.assertEqual(caught.exception.code, 'timeout')
        for code in ('timeout', 'idle_timeout', 'account_mismatch', 'codex_too_old'):
            self.assertEqual(delegate.failure_code(BridgeError('sensitive', code=code)), code)
        self.assertEqual(delegate.failure_code(BridgeError('sensitive', code='codex_not_logged_in')), 'not_logged_in')
        self.assertEqual(delegate.failure_code(Exception('sensitive')), 'delegation_failed')
        self.assertEqual(delegate.redact_result('hello', 'l', '', ''), 'hello')
        secret = 'x' * 32
        self.assertEqual(delegate.redact_result(secret + ' home', secret, '', 'home'), '[redacted] [redacted]')

    def test_orphan_runner_group_safety(self):
        with patch.object(delegate.os, 'getpgrp', return_value=42), patch.object(delegate.os, 'getpid', return_value=43), \
             patch.object(delegate.os, 'killpg') as kill, patch.object(delegate.os, '_exit') as exit_process:
            delegate.stop_orphan_runner()
            kill.assert_not_called()
            exit_process.assert_called_once_with(1)
        with patch.object(delegate.os, 'getpgrp', return_value=42), patch.object(delegate.os, 'getpid', return_value=42), \
             patch.object(delegate.os, 'killpg') as kill:
            delegate.stop_orphan_runner()
            kill.assert_called_once_with(42, signal.SIGKILL)

    def test_image_generation_and_isolation(self):
        generated = self.account_dir / 'generated_images'
        generated.mkdir()
        saved = generated / 'image.png'
        saved.write_bytes(b'fake')
        (self.account_dir / 'fake_config.json').write_text(json.dumps({'mode': 'image_success', 'log': str(self.log), 'savedPath': str(saved)}))
        request = dict(self.request, prompt='red dot', size='auto', quality='low')
        result = image.execute(request)
        self.assertTrue(result['ok'])
        self.assertFalse(saved.exists())
        records = self.records()
        argv = next(r['argv'] for r in records if 'argv' in r)
        self.assertIn(['--enable', 'image_generation'], [argv[i:i+2] for i in range(len(argv)-1)])
        for feature in ('shell_tool', 'unified_exec', 'view_image', 'apps', 'multi_agent', 'browser_use', 'in_app_browser', 'goals', 'memories', 'sleep_tool', 'computer_use', 'tool_suggest', 'skill_search', 'plugins', 'remote_plugin', 'hooks', 'guardian_approval', 'incremental_tools', 'browser_annotation_api', 'browser_use_external', 'browser_use_full_cdp_access', 'plugin_sharing', 'skill_mcp_dependency_install'):
            self.assertIn(['--disable', feature], [argv[i:i+2] for i in range(len(argv)-1)])
        thread = next(r['params'] for r in records if r.get('method') == 'thread/start')
        self.assertEqual(thread['serviceName'], 'model_mod')
        self.assertEqual(thread['sandbox'], 'read-only')
        self.assertEqual(thread['approvalPolicy'], 'never')
        for mode in ('image_failure', 'image_large', 'bad_flag', 'delegate_bad_sandbox'):
            self.log.unlink(missing_ok=True)
            self.mode(mode)
            with self.assertRaises(delegate.Failure): image.execute(dict(request))
            if mode in ('bad_flag', 'delegate_bad_sandbox'):
                self.assertFalse(any(r.get('method') == 'turn/start' for r in self.records()))
        self.mode('rate')
        with self.assertRaisesRegex(delegate.Failure, 'quota or rate limit'): image.execute(dict(request))
        (self.account_dir / 'fake_config.json').write_text(json.dumps({'mode': 'image_success', 'account': None}))
        with self.assertRaisesRegex(delegate.Failure, 'not logged in'): image.execute(dict(request))
        target = self.root / 'outside.png'
        target.write_bytes(b'untouched')
        for outside_path in (str(target), str(generated / '..' / '..' / '..' / 'outside.png')):
            with self.subTest(savedPath=outside_path):
                target.write_bytes(b'untouched')
                (self.account_dir / 'fake_config.json').write_text(json.dumps({'mode': 'image_success', 'savedPath': outside_path}))
                self.assertTrue(image.execute(dict(request))['ok'])
                self.assertTrue(target.exists())
                self.assertEqual(target.read_bytes(), b'untouched')
        target.write_bytes(b'untouched')
        saved.symlink_to(target)
        (self.account_dir / 'fake_config.json').write_text(json.dumps({'mode': 'image_success', 'log': str(self.log), 'savedPath': str(saved)}))
        self.assertTrue(image.execute(dict(request))['ok'])
        self.assertTrue(saved.is_symlink())
        self.assertEqual(target.read_bytes(), b'untouched')
        image.remove_generated(str(self.account_dir), str(generated / 'missing.png'))

    def test_image_writer(self):
        import base64
        data = base64.b64encode(b'\x89PNG\r\n\x1a\nimage').decode()
        request = {'cwd': str(self.repo), 'path': 'new/image.png', 'bytes_b64': data}
        result = image.write_image(request)
        self.assertTrue(result['ok'])
        target = self.repo / 'new' / 'image.png'
        self.assertEqual(target.read_bytes(), base64.b64decode(data))
        self.assertEqual(target.stat().st_mode & 0o777, 0o600)
        with self.assertRaises(FileExistsError): image.write_image(request)
        (self.repo / 'link').symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(OSError): image.write_image(dict(request, path='link/outside.png'))
        self.assertFalse((self.root / 'outside.png').exists())
        with self.assertRaises(delegate.Failure): image.write_image(dict(request, path='../outside.png'))
        with self.assertRaises(delegate.Failure): image.write_image(dict(request, path='other.png', bytes_b64=base64.b64encode(b'bad').decode()))
        self.assertFalse((self.repo / 'other.png').exists())

    @unittest.skipUnless(os.name == 'posix', 'process groups require POSIX')
    def test_image_cancellation(self):
        self.mode('stubborn')
        request = dict(self.request, prompt='red dot', size='auto', quality='low')
        script = str(Path(__file__).with_name('image.py').resolve())
        proc = subprocess.Popen([sys.executable, script], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        proc.stdin.write(json.dumps(request))
        proc.stdin.close()
        for _ in range(150):
            if any(r.get('method') == 'turn/start' for r in self.records()): break
            time.sleep(0.02)
        records = self.records()
        parent = next(r['pid'] for r in records if 'pid' in r)
        child = next(r['child'] for r in records if 'child' in r)
        try:
            proc.send_signal(signal.SIGTERM)
            self.assertIn('cancelled', proc.stdout.read().lower())
            self.assertEqual(proc.wait(timeout=10), 0)
            for pid in (parent, child):
                for _ in range(100):
                    try: os.kill(pid, 0)
                    except ProcessLookupError: break
                    time.sleep(0.02)
                else: self.fail('process survived cancellation')
        finally:
            proc.stdout.close()
            if proc.poll() is None: proc.kill()
            try: os.killpg(parent, signal.SIGKILL)
            except ProcessLookupError: pass

    def test_api_image_pipeline(self):
        source = Path(__file__).resolve().parent.parent.joinpath('hooks', 'register.ts').read_text()
        array = source.split('const IMAGE_PIPELINE = [', 1)[1].split('].join', 1)[0]
        lines, current = [], ''
        for line in array.splitlines():
            line = line.strip()
            if not line or line.startswith('//'): continue
            continued = line.endswith('+')
            literal = line[:-1].strip() if continued else line.rstrip(',')
            current += ast.literal_eval(literal)
            if not continued:
                lines.append(current)
                current = ''
        pipeline = '\n'.join(lines)
        bindir = self.root / 'bin'
        bindir.mkdir()
        curl = bindir / 'curl'
        curl.write_text('#!/bin/sh\nprintf "{\\\"data\\\":[{\\\"b64_json\\\":\\\"aGVsbG8=\\\"}]}"\nexit "${FAKE_EXIT:-0}"\n')
        curl.chmod(0o755)
        env = dict(os.environ, PATH=str(bindir) + os.pathsep + os.environ['PATH'], MODEL_MOD_KEY='fake')
        def run(path, code='0'):
            return subprocess.run(['bash', '-c', pipeline, 'bash', '', 'http://example.invalid', str(path), str(self.repo)],
                                  input='{}', text=True, capture_output=True, env=dict(env, FAKE_EXIT=code), timeout=10)
        out = self.repo / 'new' / 'image.png'
        self.assertEqual(run(out).returncode, 0)
        self.assertEqual(out.read_bytes(), b'hello')
        self.assertNotEqual(run(out).returncode, 0)
        self.assertEqual(out.read_bytes(), b'hello')
        outside = self.root / 'outside'
        outside.mkdir()
        (self.repo / 'link').symlink_to(outside, target_is_directory=True)
        self.assertNotEqual(run(self.repo / 'link' / 'escape.png').returncode, 0)
        self.assertEqual(list(outside.iterdir()), [])
        failed = self.repo / 'new' / 'failed.png'
        self.assertNotEqual(run(failed, '22').returncode, 0)
        self.assertFalse(failed.exists())
        self.assertEqual(sorted(p.name for p in out.parent.iterdir()), ['image.png'])
        ln = bindir / 'ln'
        ln.write_text('#!/bin/sh\nexit 1\n')
        ln.chmod(0o755)
        fallback = self.repo / 'new' / 'fallback.png'
        self.assertEqual(run(fallback).returncode, 0)
        self.assertEqual(fallback.read_bytes(), b'hello')
        existing = run(fallback)
        self.assertNotEqual(existing.returncode, 0)
        self.assertIn('file already exists', existing.stdout)
        self.assertEqual(fallback.read_bytes(), b'hello')
        cannot_create = run(self.repo / 'new' / ('x' * 300 + '.png'))
        self.assertNotEqual(cannot_create.returncode, 0)
        self.assertIn('cannot create image file', cannot_create.stdout)
        self.assertNotIn('file already exists', cannot_create.stdout)

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

    def test_write_policy_and_approvals(self):
        self.mode('delegate_approval')
        root = os.path.realpath(self.repo)
        request = dict(self.request, options={'text': 'test', 'write': True}, writeRoot=root)
        self.assertEqual(delegate.execute(request), 'hello')
        records = self.records()
        thread = next(r['params'] for r in records if r.get('method') == 'thread/start')
        turn = next(r['params'] for r in records if r.get('method') == 'turn/start')
        self.assertEqual(thread, {'serviceName': 'model_mod', 'model': 'chat', 'cwd': root, 'sandbox': 'workspace-write',
                                  'approvalPolicy': 'never', 'ephemeral': True,
                                  'config': {'sandbox_workspace_write': {'writable_roots': [root], 'network_access': False,
                                                                         'exclude_tmpdir_env_var': True, 'exclude_slash_tmp': True}}})
        self.assertEqual(turn, {'threadId': '12345678-1234-4234-8234-123456789abc', 'model': 'chat', 'effort': None,
                                'sandboxPolicy': {'type': 'workspaceWrite', 'writableRoots': [root], 'networkAccess': False,
                                                  'excludeTmpdirEnvVar': True, 'excludeSlashTmp': True},
                                'input': [{'type': 'text', 'text': 'test', 'text_elements': []}]})
        self.assertEqual([r['result'] for r in records if r.get('id') in ('approval1', 'approval2')],
                         [{'decision': 'decline'}, {'decision': 'decline'}])
        self.log.unlink()
        self.mode('delegate_bad_sandbox')
        with self.assertRaisesRegex(delegate.Failure, 'sandbox'): delegate.execute(dict(request))
        self.assertFalse(any(r.get('method') == 'turn/start' for r in self.records()))
        self.mode('delegate_approval')
        with self.assertRaisesRegex(delegate.Failure, 'Working directory'): delegate.execute(dict(request, writeRoot='/'))
        codex_home = self.root / 'envcodex'
        (codex_home / 'sub').mkdir(parents=True)
        with patch.dict(os.environ, {'CODEX_HOME': str(codex_home)}):
            for unsafe in ('/', os.path.expanduser('~'), str(self.account_dir), str(self.account_dir.parent),
                           str(codex_home), str(codex_home / 'sub')):
                with self.assertRaises(delegate.Failure):
                    delegate.validate_write_root(unsafe, str(self.account_dir.parent), 'test')
        alias = str(self.account_dir.parent).replace('accounts', 'ACCOUNTS')
        if os.path.isdir(alias):
            with self.assertRaises(delegate.Failure): delegate.validate_write_root(alias, str(self.account_dir.parent), 'test')

    def test_transfer(self):
        projects = self.root / '.claude' / 'projects'
        projects.mkdir(parents=True)
        transcript = projects / 'fake.jsonl'
        transcript.write_text('{"message":"synthetic"}\n')
        request = dict(self.request, kind='transfer', transcript=str(transcript))
        def mode(name):
            (self.account_dir / 'fake_config.json').write_text(json.dumps({'mode': name, 'log': str(self.log), 'session_path': str(transcript), 'session_cwd': str(self.repo)}))
        with patch.dict(os.environ, {'HOME': str(self.root)}):
            mode('transfer')
            output = delegate.transfer(request)
            self.assertIn('codex resume 12345678-1234-4234-8234-123456789abc', output)
            calls = [r for r in self.records() if r.get('method') == 'externalAgentConfig/import']
            items = calls[0]['params']['migrationItems']
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]['itemType'], 'SESSIONS')
            self.assertEqual(items[0]['details']['sessions'], [{'path': os.path.realpath(transcript), 'cwd': str(self.repo), 'title': None}])
            self.assertTrue(all(not v for k, v in items[0]['details'].items() if k != 'sessions'))
            mode('transfer_invalid_id')
            with self.assertRaisesRegex(delegate.Failure, 'not confirmed'): delegate.transfer(request)
            mode('transfer_exit')
            with self.assertRaisesRegex(delegate.Failure, 'not confirmed'): delegate.transfer(request)
            mode('transfer_timeout')
            with patch.object(delegate, 'IDLE_SECONDS', .1):
                with self.assertRaisesRegex(delegate.Failure, 'not confirmed'): delegate.transfer(request)
            outside = self.root / 'outside'
            outside.write_text('synthetic')
            link = projects / 'escape'
            link.symlink_to(outside)
            for invalid in (str(outside), str(link), str(projects)):
                with self.assertRaises(delegate.Failure): delegate.transcript_path(invalid)
            with transcript.open('wb') as f: f.truncate(20 * 1024 * 1024 + 1)
            with self.assertRaises(delegate.Failure): delegate.transcript_path(str(transcript))

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
        with patch.dict(os.environ, {'GIT_DIR': str(other / '.git'), 'GIT_WORK_TREE': str(other),
                                    'GIT_EXTERNAL_DIFF': str(script), 'SECRET_TOKEN': 'secret'}):
            diff = delegate.diff_for(str(self.repo), None)
            self.assertNotIn('SECRET_TOKEN', delegate.git_env())
            self.assertNotIn('GIT_DIR', delegate.git_env())
        self.assertIn(b'expected diff', diff)
        self.assertNotIn(b'wrong repository', diff)
        self.assertFalse(flag.exists())

        with patch.dict(os.environ, {'GIT_EXTERNAL_DIFF': str(script)}):
            diff = delegate.diff_for(str(self.repo), None)
        self.assertIn(b'expected diff', diff)
        self.assertFalse(flag.exists())

        for key in ('diff.external', 'diff.x.command'):
            subprocess.run(['git', '-C', str(self.repo), 'config', key, str(script)], check=True)
            (self.repo / '.gitattributes').write_text('* filter=x diff=x\n')
            self.assertIn(b'expected diff', delegate.diff_for(str(self.repo), None))
            self.assertFalse(flag.exists())
            subprocess.run(['git', '-C', str(self.repo), 'config', '--unset', key], check=True)

        subprocess.run(['git', '-C', str(self.repo), 'config', 'filter.a.clean\x0bfilter.b.clean', str(script)], check=True)
        (self.repo / '.gitattributes').write_text('* filter=a.clean\x0bfilter.b\n')
        with self.assertRaisesRegex(delegate.Failure, 'Unsupported Git filter name'):
            delegate.diff_for(str(self.repo), None)
        self.assertFalse(flag.exists())

        version = subprocess.check_output(['git', '--version'], text=True).split()[2].split('.')
        if tuple(map(int, version[:2])) >= (2, 54):
            hook_repo = self.root / 'hook-repo'
            subprocess.run(['git', 'clone', '-q', str(self.repo), str(hook_repo)], check=True)
            subprocess.run(['git', '-C', str(hook_repo), 'config', 'hook.x.command', str(script)], check=True)
            subprocess.run(['git', '-C', str(hook_repo), 'config', 'hook.x.event', 'post-index-change'], check=True)
            os.utime(hook_repo / 'file', (1, 1))
            (hook_repo / 'changed').write_text('real change\n')
            subprocess.run(['git', '-C', str(hook_repo), 'add', 'changed'], check=True)
            if flag.exists(): flag.unlink()
            diff = delegate.diff_for(str(hook_repo), None)
            self.assertIn(b'real change', diff)
            self.assertNotIn(b'diff --git a/file', diff)
            self.assertFalse(flag.exists())
            os.utime(hook_repo / 'file', (2, 2))
            self.mode('text')
            req = dict(self.request, cwd=str(hook_repo), kind='review', options={'adversarial': True})
            self.assertEqual(delegate.execute(req), 'hello')
            self.assertFalse(flag.exists())
        else:
            print('Git < 2.54: config hook assertion skipped')

        super_repo = self.root / 'super'
        subprocess.run(['git', 'init', '-q', str(super_repo)], check=True)
        def super_git(*args):
            subprocess.run(['git', '-C', str(super_repo), *args], check=True, stdout=subprocess.DEVNULL)
        super_git('config', 'user.name', 'Test')
        super_git('config', 'user.email', 'test@example.invalid')
        super_git('commit', '--allow-empty', '-qm', 'initial')
        super_git('-c', 'protocol.file.allow=always', 'submodule', 'add', '-q', str(other), 'sub')
        super_git('commit', '-qm', 'add submodule')
        sub = super_repo / 'sub'
        subprocess.run(['git', '-C', str(sub), 'config', 'user.name', 'Test'], check=True)
        subprocess.run(['git', '-C', str(sub), 'config', 'user.email', 'test@example.invalid'], check=True)
        (sub / 'file').write_text('committed\n')
        subprocess.run(['git', '-C', str(sub), 'commit', '-qam', 'change'], check=True)
        super_git('add', 'sub')
        subprocess.run(['git', '-C', str(sub), 'config', 'filter.x.clean', str(script)], check=True)
        (sub / '.gitattributes').write_text('* filter=x\n')
        (sub / 'file').write_text('different\n')
        for setting in ('clean', 'smudge', 'process'):
            subprocess.run(['git', '-C', str(sub), 'config', '--unset-all', 'filter.x.clean'], check=False)
            subprocess.run(['git', '-C', str(sub), 'config', 'filter.x.' + setting, str(script)], check=True)
            subprocess.run(['git', '-C', str(super_repo), 'diff', 'HEAD'], stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=5)
            self.assertEqual(flag.exists(), setting != 'smudge', setting)
            if flag.exists(): flag.unlink()
            self.assertIn(b'Subproject commit', delegate.diff_for(str(super_repo), None))
            self.assertFalse(flag.exists())
            subprocess.run(['git', '-C', str(sub), 'config', '--unset-all', 'filter.x.' + setting], check=True)
        super_git('branch', 'baseline')
        super_git('config', 'diff.submodule', 'diff')
        for key in ('diff.external', 'diff.x.textconv'):
            subprocess.run(['git', '-C', str(sub), 'config', key, str(script)], check=True)
            (sub / '.gitattributes').write_text('* diff=x\n')
            super_git('diff', 'HEAD')
            self.assertTrue(flag.exists(), key)
            flag.unlink()
            self.assertIn(b'Subproject commit', delegate.diff_for(str(super_repo), None))
            self.assertFalse(flag.exists())
            subprocess.run(['git', '-C', str(sub), 'config', '--unset', key], check=True)
        super_git('commit', '-qm', 'update submodule')
        (sub / '.gitattributes').write_text('* filter=x\n')
        for setting in ('clean', 'smudge', 'process'):
            subprocess.run(['git', '-C', str(sub), 'config', 'filter.x.' + setting, str(script)], check=True)
            super_git('diff', 'baseline...HEAD')
            self.assertFalse(flag.exists())
            self.assertIn(b'Subproject commit', delegate.diff_for(str(super_repo), 'baseline'))
            self.assertFalse(flag.exists())
            subprocess.run(['git', '-C', str(sub), 'config', '--unset-all', 'filter.x.' + setting], check=True)
        (sub / '.gitattributes').write_text('* diff=x\n')
        for key in ('diff.external', 'diff.x.textconv'):
            subprocess.run(['git', '-C', str(sub), 'config', key, str(script)], check=True)
            super_git('diff', 'baseline...HEAD')
            self.assertTrue(flag.exists(), key)
            flag.unlink()
            self.assertIn(b'Subproject commit', delegate.diff_for(str(super_repo), 'baseline'))
            self.assertFalse(flag.exists())
            subprocess.run(['git', '-C', str(sub), 'config', '--unset', key], check=True)

    def test_git_configuration_matrix(self):
        def command(repo, *args, env=None):
            return subprocess.run(['git', '-C', str(repo), *args], env=env, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, check=True)

        (self.repo / 'stable').write_text('stable\n')
        (self.repo / 'staged').write_text('original staged\n')
        command(self.repo, 'add', 'stable', 'staged')
        command(self.repo, 'commit', '-qm', 'add stable')
        command(self.repo, 'branch', 'baseline')
        (self.repo / 'file').write_text('committed change\n')
        command(self.repo, 'commit', '-qam', 'change')
        (self.repo / 'file').write_text('unstaged change\n')
        (self.repo / 'staged').write_text('staged change\n')
        command(self.repo, 'add', 'staged')
        branch = command(self.repo, 'branch', '--show-current').stdout.decode().strip()
        version = tuple(map(int, subprocess.check_output(['git', '--version'], text=True).split()[2].split('.')[:2]))
        rows = [
            ('diff.external', 'config', True, True), ('diff.x.command', 'config', True, True),
            ('diff.x.textconv', 'config', True, True), ('filter.x.clean', 'config', True, False),
            ('filter.x.smudge', 'config', False, False), ('filter.x.process', 'config', True, False),
            ('core.fsmonitor', 'config', True, False), ('core.hooksPath', 'hookpath', True, False),
            ('hooks/post-index-change', 'hook', True, False),
            ('core.pager', 'config', False, False), ('pager.diff', 'config', False, False),
            ('core.sshCommand', 'config', False, False), ('core.editor', 'config', False, False),
            ('core.askPass', 'config', False, False), ('credential.helper', 'config', False, False),
            ('gpg.program', 'config', False, False), ('gpg.openpgp.program', 'config', False, False),
            ('merge.x.driver', 'config', False, False), ('alias.example', 'config', False, False),
            ('submodule.x.update', 'config', False, False), ('submodule.x.ignore', 'ignore', False, False),
            ('diff.submodule', 'submodule', False, False),
            ('info/attributes', 'info', True, False), ('core.attributesFile', 'attributes', True, False),
            ('include.path', 'include', True, False), ('includeIf.onbranch', 'onbranch', True, False),
            ('includeIf.gitdir', 'gitdir', True, False), ('config.worktree', 'worktree', True, False),
            ('GIT_CONFIG_COUNT', 'env', True, True), ('GIT_CONFIG_PARAMETERS', 'env', True, True),
            ('GIT_EXTERNAL_DIFF', 'env', True, True), ('GIT_PAGER', 'env', False, False),
            ('GIT_SSH_COMMAND', 'env', False, False), ('GIT_DIR', 'env', False, False),
            ('GIT_WORK_TREE', 'env', False, False), ('GIT_INDEX_FILE', 'env', False, False),
            ('GIT_ATTR_SOURCE', 'env', False, False), ('GIT_ATTR_NOSYSTEM', 'env', False, False),
            ('diff=x', 'attribute', True, True), ('filter=x', 'attribute', True, False),
            ('merge=x', 'attribute', False, False), ('export-subst', 'attribute', False, False),
            ('ident', 'attribute', False, False), ('text', 'attribute', False, False),
            ('eol=lf', 'attribute', False, False), ('working-tree-encoding=UTF-8', 'attribute', False, False),
        ]
        if version >= (2, 54):
            rows.append(('hook.x.command', 'config-hook', True, False))
        else:
            print('Git < 2.54: configured hook control skipped')
        for number, (key, fixture, head_control, base_control) in enumerate(rows):
            with self.subTest(key=key):
                repo = self.root / ('matrix-%d' % number)
                shutil.copytree(self.repo, repo, symlinks=True)
                flag = self.root / ('matrix-flag-%d' % number)
                script = self.root / ('matrix-script-%d' % number)
                script.write_text('#!/bin/sh\nprintf marker > "' + str(flag) + '"\n')
                script.chmod(0o755)
                (repo / '.gitattributes').write_text('* diff=x filter=x merge=x\n')
                marker = str(script)
                env = dict(os.environ)
                if fixture in ('config', 'ignore', 'submodule', 'config-hook'):
                    value = 'none' if fixture == 'ignore' else 'diff' if fixture == 'submodule' else marker
                    if key in ('alias.example', 'submodule.x.update'): value = '!' + marker
                    command(repo, 'config', key, value)
                    if fixture == 'config-hook': command(repo, 'config', 'hook.x.event', 'post-index-change')
                elif fixture in ('hookpath', 'hook'):
                    hooks = self.root / ('hooks-%d' % number) if fixture == 'hookpath' else repo / '.git' / 'hooks'
                    hooks.mkdir(exist_ok=True)
                    hook = hooks / 'post-index-change'
                    hook.write_text(script.read_text()); hook.chmod(0o755)
                    if fixture == 'hookpath': command(repo, 'config', 'core.hooksPath', str(hooks))
                elif fixture in ('info', 'attributes', 'include', 'onbranch', 'gitdir', 'worktree'):
                    if fixture == 'info':
                        (repo / '.git' / 'info' / 'attributes').write_text('* filter=x\n')
                        (repo / '.gitattributes').unlink()
                        command(repo, 'config', 'filter.x.clean', marker)
                    elif fixture == 'attributes':
                        attrs = self.root / ('attributes-%d' % number)
                        attrs.write_text('* filter=x\n')
                        (repo / '.gitattributes').unlink()
                        command(repo, 'config', 'core.attributesFile', str(attrs))
                        command(repo, 'config', 'filter.x.clean', marker)
                    else:
                        included = self.root / ('include-%d' % number)
                        included.write_text('[filter "x"]\n clean = ' + marker + '\n')
                        if fixture == 'worktree':
                            command(repo, 'config', 'extensions.worktreeConfig', 'true')
                            (repo / '.git' / 'config.worktree').write_text(included.read_text())
                        else:
                            name = {'include': 'include.path', 'onbranch': 'includeIf.onbranch:' + branch + '.path',
                                    'gitdir': 'includeIf.gitdir:' + os.path.realpath(repo / '.git') + '.path'}[fixture]
                            command(repo, 'config', name, str(included))
                elif fixture == 'env':
                    if key == 'GIT_CONFIG_COUNT':
                        env.update(GIT_CONFIG_COUNT='1', GIT_CONFIG_KEY_0='diff.external', GIT_CONFIG_VALUE_0=marker)
                    elif key == 'GIT_CONFIG_PARAMETERS': env[key] = "'diff.external=" + marker + "'"
                    elif key in ('GIT_EXTERNAL_DIFF', 'GIT_PAGER', 'GIT_SSH_COMMAND'): env[key] = marker
                    elif key == 'GIT_DIR': env[key] = str(repo / '.git')
                    elif key == 'GIT_WORK_TREE': env[key] = str(repo)
                    elif key == 'GIT_INDEX_FILE': env[key] = str(repo / '.git' / 'index')
                    elif key == 'GIT_ATTR_SOURCE': env[key] = 'HEAD'
                    else: env[key] = '1'
                else:
                    (repo / '.gitattributes').write_text('* ' + key + '\n')
                    if key == 'diff=x': command(repo, 'config', 'diff.x.command', marker)
                    if key == 'filter=x': command(repo, 'config', 'filter.x.clean', marker)
                    if key == 'merge=x': command(repo, 'config', 'merge.x.driver', marker)
                for base, expected_control, expected_diff in ((None, head_control, b'unstaged change'),
                                                               ('baseline', base_control, b'committed change')):
                    os.utime(repo / 'stable', (1, 1))
                    control = subprocess.run(['git', '-C', str(repo), 'diff', 'HEAD' if base is None else 'baseline...HEAD', '--'],
                                             env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                    self.assertEqual(flag.exists(), expected_control, (key, base, control.stderr))
                    if flag.exists(): flag.unlink()
                    os.utime(repo / 'stable', (2, 2))
                    index_before = (repo / '.git' / 'index').read_bytes()
                    with patch.dict(os.environ, env, clear=True):
                        result = delegate.diff_for(str(repo), base)
                    self.assertIn(expected_diff, result)
                    if base is None: self.assertIn(b'staged change', result)
                    self.assertFalse(flag.exists(), (key, base))
                    if fixture == 'config-hook' and base is None:
                        self.assertEqual(index_before, (repo / '.git' / 'index').read_bytes())
                if fixture == 'hook' and version >= (2, 36):
                    command(repo, 'hook', 'run', 'post-index-change')
                    self.assertTrue(flag.exists())
                    flag.unlink()
                    delegate.git(str(repo), ['hook', 'run', '--ignore-missing', 'post-index-change'])
                    self.assertFalse(flag.exists())
                if fixture == 'config-hook':
                    events = ('applypatch-msg', 'pre-applypatch', 'post-applypatch', 'pre-commit', 'pre-merge-commit',
                              'prepare-commit-msg', 'commit-msg', 'post-commit', 'pre-rebase', 'post-checkout',
                              'post-merge', 'pre-push', 'pre-receive', 'update', 'proc-receive', 'post-receive',
                              'post-update', 'reference-transaction', 'push-to-checkout', 'pre-auto-gc', 'post-rewrite',
                              'sendemail-validate', 'fsmonitor-watchman', 'p4-changelist', 'p4-prepare-changelist',
                              'p4-post-changelist', 'p4-pre-submit', 'post-index-change')
                    for event_index, event in enumerate(events):
                        command(repo, 'config', '--replace-all', 'hook.x.event', event)
                        for base, expected_diff in ((None, b'unstaged change'), ('baseline', b'committed change')):
                            os.utime(repo / 'stable', (100 + event_index, 100 + event_index))
                            command(repo, 'diff', 'HEAD' if base is None else 'baseline...HEAD', '--')
                            self.assertEqual(flag.exists(), event == 'post-index-change' and base is None, (event, base))
                            if flag.exists(): flag.unlink()
                            os.utime(repo / 'stable', (200 + event_index, 200 + event_index))
                            self.assertIn(expected_diff, delegate.diff_for(str(repo), base))
                            self.assertFalse(flag.exists(), (event, base))

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

    def test_gate_verdict_and_protocol(self):
        valid = {'verdict': 'pass', 'findings': [], 'needsHuman': False}
        blocking = {'severity': 'blocking', 'file': 'file', 'line': 1, 'summary': 'issue'}
        for verdict in ('pass', 'block', 'unknown'):
            value = dict(valid, verdict=verdict, findings=[blocking] if verdict == 'block' else [], needsHuman=verdict == 'unknown')
            self.assertEqual(delegate.gate_verdict(json.dumps(value))['verdict'], verdict)
        invalid = [dict(valid, extra=1), {'verdict': 'pass'}, dict(valid, needsHuman='false'),
                   dict(valid, findings=[dict(blocking, summary='x' * 501)]), dict(valid, findings=[blocking]),
                   dict(valid, findings=[blocking] * 21), dict(valid, needsHuman=True)]
        for value in invalid:
            self.assertEqual(delegate.gate_verdict(json.dumps(value))['verdict'], 'unknown')
        for text in ('invalid', '{"verdict":"pass","verdict":"pass","findings":[],"needsHuman":false}'):
            self.assertEqual(delegate.gate_verdict(text)['verdict'], 'unknown')
        (self.repo / 'file').write_text('changed\n')
        (self.repo / 'new').write_text('untracked\n')
        self.mode('gate')
        req = dict(self.request, kind='review', options={'gate': True}, sessionId='session')
        first = json.loads(delegate.execute(req))
        self.assertEqual(first['verdict'], 'pass')
        (self.repo / 'subdir').mkdir()
        self.assertEqual(first['fingerprint'], delegate.gate_snapshot(str(self.repo / 'subdir'), None, 'session')['fingerprint'])
        records = self.records()
        thread = next(r['params'] for r in records if r.get('method') == 'thread/start')
        self.assertEqual(thread['sandbox'], 'read-only')
        self.assertEqual(thread['approvalPolicy'], 'never')
        turn = next(r['params'] for r in records if r.get('method') == 'turn/start')
        self.assertEqual(turn['outputSchema'], delegate.GATE_SCHEMA)
        self.assertEqual(turn['sandboxPolicy'], {'type': 'readOnly', 'networkAccess': False})
        self.assertIn('untracked', turn['input'][0]['text'])
        (self.repo / 'new').write_text('modified\n')
        self.assertNotEqual(first['fingerprint'], delegate.gate_snapshot(str(self.repo), None, 'session')['fingerprint'])
        self.log.unlink()
        self.mode('gate_approval')
        self.assertEqual(json.loads(delegate.execute(req))['verdict'], 'pass')
        replies = [r for r in self.records() if r.get('id') in ('approval1', 'approval2') and 'result' in r]
        self.assertEqual([r['result'] for r in replies], [{'decision': 'decline'}, {'decision': 'decline'}])
        (self.repo / 'new').write_bytes(b'\x00binary')
        with self.assertRaises(delegate.Failure): delegate.gate_snapshot(str(self.repo), None, 'session')

    def test_gate_rejects_dirty_submodule(self):
        module = self.root / 'module'
        module.mkdir()
        def command(cwd, *args):
            subprocess.run(['git', '-C', str(cwd), *args], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        command(module, 'init', '-q')
        command(module, 'config', 'user.name', 'Test')
        command(module, 'config', 'user.email', 'test@example.invalid')
        (module / 'file').write_text('initial\n')
        command(module, 'add', 'file')
        command(module, 'commit', '-qm', 'initial')
        command(self.repo, '-c', 'protocol.file.allow=always', 'submodule', 'add', '-q', str(module), 'nested')
        command(self.repo, 'commit', '-qm', 'add submodule')
        self.assertFalse(delegate.gate_snapshot(str(self.repo), None, 'session')['changed'])
        (self.repo / 'nested' / 'file').write_text('changed\n')
        with self.assertRaisesRegex(delegate.Failure, 'Dirty submodule'):
            delegate.gate_snapshot(str(self.repo), None, 'session')

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
        prompt = turn['params']['input'][0]['text']
        self.assertIn('+changed', prompt)
        self.assertIn('excludes untracked files', prompt)
        self.assertRegex(prompt, r'<diff_[0-9a-f]{32}>')
        with patch.object(delegate.secrets, 'token_hex', side_effect=['a' * 32, 'b' * 32]):
            bounded = delegate.diff_prompt(('diff_' + 'a' * 32).encode())
        self.assertIn('<diff_' + 'b' * 32 + '>', bounded)
        with self.assertRaisesRegex(delegate.Failure, 'Invalid base ref'): delegate.diff_for(str(self.repo), 'main;touch x')


if __name__ == '__main__': unittest.main()
