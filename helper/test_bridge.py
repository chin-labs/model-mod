import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from mapping import InvalidRequest, classify, names, prepare, usage_delta

ROOT = Path(__file__).resolve().parent
BRIDGE = ROOT / 'bridge.py'
FAKE = ROOT / 'fake_codex.py'
BASE = {'model': 'test', 'max_tokens': 64, 'messages': [{'role': 'user', 'content': 'hello'}], 'stream': True}
TOOLS = [{'name': 'one', 'input_schema': {'type': 'object'}}, {'name': 'two', 'input_schema': {'type': 'object'}}]


class Contract(unittest.TestCase):
    def run_bridge(self, body=BASE, mode='text', log=None, extra=()):
        with tempfile.TemporaryDirectory() as home:
            Path(home, 'fake_config.json').write_text(json.dumps({'mode': mode, 'log': str(log) if log else None}))
            return subprocess.run([sys.executable, str(BRIDGE), 'messages', '--codex-home', home, '--codex-bin', str(FAKE), '--model-map', 'test=gpt-6.1-terra', *extra], input=json.dumps(body), text=True, capture_output=True, timeout=15)

    def test_text_and_usage(self):
        r = self.run_bridge()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual([x[7:] for x in r.stdout.splitlines() if x.startswith('event: ')], ['message_start', 'content_block_start', 'content_block_delta', 'content_block_stop', 'message_delta', 'message_stop'])
        self.assertIn('"input_tokens": 60', r.stdout)
        self.assertIn('"cache_read_input_tokens": 40', r.stdout)
        self.assertEqual(usage_delta({'inputTokens': 30, 'cachedInputTokens': 10, 'outputTokens': 3}, {'inputTokens': 100, 'cachedInputTokens': 40, 'outputTokens': 9}), {'input_tokens': 40, 'output_tokens': 6, 'cache_read_input_tokens': 30, 'cache_creation_input_tokens': 0})
        self.assertIn('model-mod-http:200', r.stderr)
        nonstream = self.run_bridge(dict(BASE, stream=False))
        self.assertEqual(json.loads(nonstream.stdout)['content'], [{'type': 'text', 'text': 'hello'}])
        self.assertEqual(nonstream.returncode, 0)

    def test_parallel_tools_and_interrupt(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / 'log'
            r = self.run_bridge(dict(BASE, tools=TOOLS), 'tools', log)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(r.stdout.count('"type": "tool_use", "id"'), 2)
            self.assertIn('"stop_reason": "tool_use"', r.stdout)
            calls = [json.loads(x) for x in log.read_text().splitlines()]
            self.assertFalse({'OPENAI_API_KEY', 'CODEX_API_KEY', 'ANTHROPIC_API_KEY'} & set(calls[0]['env_keys']))
            for setting in ('include_permissions_instructions=false', 'include_environment_context=false'):
                self.assertIn(setting, calls[0]['argv'])
                self.assertEqual(calls[0]['argv'][calls[0]['argv'].index(setting) - 1], '-c')
            self.assertEqual(sum(c.get('method') == 'turn/interrupt' for c in calls), 1)

    def test_history_and_names(self):
        literal = prepare(dict(BASE, messages=[{'role': 'user', 'content': '__THREAD_ID__'}]), {'test': 'gpt-6.1-terra'})
        self.assertEqual(literal['input'][0]['text'], '__THREAD_ID__')
        name = 'tool name'
        tools = [{'name': name, 'input_schema': {'type': 'object'}}]
        request = dict(BASE, tools=tools, system=[{'type': 'text', 'text': 'a', 'cache_control': {}}, {'type': 'text', 'text': 'b'}], messages=[{'role': 'assistant', 'content': [{'type': 'thinking', 'signature': 'x'}, {'type': 'tool_use', 'name': name, 'id': 't', 'input': {}}]}, {'role': 'user', 'content': [{'type': 'tool_result', 'tool_use_id': 't', 'is_error': True, 'content': [{'type': 'image', 'source': {'type': 'base64', 'media_type': 'image/png', 'data': 'aGk='}}]}]}])
        p = prepare(request, {'test': 'gpt-6.1-terra'})
        self.assertEqual(p['system'], 'a\n\nb')
        self.assertEqual(p['dropped'], 1)
        self.assertEqual(p['reverse'][p['history'][0]['name']], name)
        self.assertEqual(p['history'][1]['output'][0]['text'], 'ERROR: ')
        self.assertEqual(p['history'][1]['output'][1]['image_url'], 'data:image/png;base64,aGk=')
        self.assertEqual(p['ignored'], ['cache_control', 'max_tokens', 'signature'])
        encoded = names(tools)[0][name]
        self.assertLessEqual(len(encoded), 64)
        long_name = 'x' * 100
        forward, reverse = names([{'name': long_name}])
        self.assertLessEqual(len(forward[long_name]), 64)
        self.assertEqual(reverse[forward[long_name]], long_name)
        reserved = 'mcp__model-mod__web_fetch'
        forward, reverse = names([{'name': reserved}])
        self.assertNotEqual(forward[reserved], reserved)
        self.assertLessEqual(len(forward[reserved]), 64)
        self.assertEqual(reverse[forward[reserved]], reserved)
        with self.assertRaises(InvalidRequest): names([{'name': reserved}, {'name': forward[reserved]}])
        history = prepare(dict(BASE, tools=[{'name': reserved, 'input_schema': {}}], messages=[{'role': 'assistant', 'content': [{'type': 'tool_use', 'name': reserved, 'id': 'u', 'input': {}}]}, {'role': 'user', 'content': [{'type': 'tool_result', 'tool_use_id': 'u', 'content': 'ok'}]}]), {'test': 'gpt-6.1-terra'})
        self.assertEqual(history['history'][0]['name'], forward[reserved])
        self.assertEqual(history['reverse'][history['history'][0]['name']], reserved)
        self.assertEqual(history['history'][1]['call_id'], 'u')
        with self.assertRaises(InvalidRequest): names(tools + [{'name': encoded, 'input_schema': {}}])

    def test_errors_and_version(self):
        self.assertEqual(classify({'message': 'not a rate limit; 429 in user input'}), (500, 'api_error'))
        self.assertEqual(classify({'codexErrorInfo': 'usageLimit'}), (429, 'rate_limit_error'))
        self.assertEqual(classify({'code': -32602}), (500, 'api_error'))
        for mode in ('rejected_request', 'rejected_params'):
            r = self.run_bridge(mode=mode)
            self.assertIn('model-mod-http:400', r.stderr)
            self.assertEqual(json.loads(r.stdout)['error']['code'], 'codex_rejected_request')
            self.assertNotIn('untrusted details', r.stdout)
        for mode, code, kind in [('bad', '400', 'invalid_request_error'), ('rate', '429', 'rate_limit_error'), ('version', '500', 'api_error')]:
            r = self.run_bridge(mode=mode)
            self.assertNotEqual(r.returncode, 0)
            self.assertIn('model-mod-http:' + code, r.stderr)
            self.assertIn(kind, r.stdout)
            self.assertNotIn('event: message_start', r.stdout)
            if mode in ('bad', 'rate'):
                self.assertIn('model-mod-note:Codex login: app-server stderr: synthetic app-server failure <redacted>', r.stderr)
                self.assertNotIn('A' * 32, r.stderr)
            if mode == 'rate': self.assertIn('model-mod-retry-after:7', r.stderr)
        r = self.run_bridge(mode='invalid_uuid')
        self.assertEqual(r.returncode, 65)
        self.assertNotIn('event: message_start', r.stdout)
        r = self.run_bridge(mode='miderror')
        self.assertIn('event: error', r.stdout)
        self.assertNotIn('event: message_stop', r.stdout)
        self.assertIn('model-mod-http:500', r.stderr)

    def test_cancel_kills_child(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / 'log'
            Path(tmp, 'fake_config.json').write_text(json.dumps({'mode': 'abort', 'log': str(log)}))
            env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1')
            p = subprocess.Popen([sys.executable, str(BRIDGE), 'messages', '--codex-home', tmp, '--codex-bin', str(FAKE), '--model-map', 'test=gpt-6.1-terra'], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
            p.stdin.write(json.dumps(BASE)); p.stdin.close()
            while True:
                line = p.stdout.readline()
                if not line: self.fail('stream ended before cancellation')
                if line.startswith('event: content_block_delta'): break
            p.stdout.close()
            p.wait(timeout=10)
            p.stderr.close()
            records = [json.loads(x) for x in log.read_text().splitlines()]
            pid = records[0]['pid']
            with self.assertRaises(ProcessLookupError): os.kill(pid, 0)
            self.assertTrue(any(c.get('method') == 'turn/interrupt' for c in records))
            log.unlink()
            Path(tmp, 'fake_config.json').write_text(json.dumps({'mode': 'stubborn', 'log': str(log)}))
            p = subprocess.Popen([sys.executable, str(BRIDGE), 'messages', '--codex-home', tmp, '--codex-bin', str(FAKE), '--model-map', 'test=gpt-6.1-terra'], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
            p.stdin.write(json.dumps(BASE)); p.stdin.close()
            while True:
                line = p.stdout.readline()
                if not line: self.fail('stream ended before SIGTERM')
                if line.startswith('event: content_block_delta'): break
            p.send_signal(getattr(signal, 'SIGHUP', signal.SIGTERM))
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                records = [json.loads(x) for x in log.read_text().splitlines()]
                if any(c.get('method') == 'turn/interrupt' for c in records): break
                time.sleep(0.01)
            pid = records[0]['pid']
            try:
                self.assertTrue(any(c.get('method') == 'turn/interrupt' for c in records))
                p.send_signal(signal.SIGTERM)
                p.wait(timeout=10)
                with self.assertRaises(ProcessLookupError): os.killpg(pid, 0)
            finally:
                if p.poll() is None: p.kill(); p.wait()
                try: os.killpg(pid, signal.SIGKILL)
                except ProcessLookupError: pass
                p.stdout.close(); p.stderr.close()

    def test_timeout(self):
        for extra in (['--idle-seconds', '0.2'], ['--idle-seconds', '5', '--max-seconds', '0.2']):
            r = self.run_bridge(mode='abort', extra=extra)
            self.assertNotEqual(r.returncode, 0)
            self.assertIn('event: error', r.stdout)
            self.assertNotIn('message_stop', r.stdout)
            self.assertIn('model-mod-http:504', r.stderr)
        started = time.monotonic()
        r = self.run_bridge(mode='chatty', extra=['--idle-seconds', '0.2'])
        self.assertIn('model-mod-http:504', r.stderr)
        self.assertLess(time.monotonic() - started, 4)

    def test_effort_and_environment(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / 'log'
            old = dict(os.environ)
            try:
                os.environ.update(ANTHROPIC_SECRET='fake', OPENAI_SECRET='fake', OTHER_KEY='fake', OTHER_TOKEN='fake', LC_SECRET_KEY='fake', TERM='test', LC_NUMERIC='C')
                r = self.run_bridge(dict(BASE, model='test(max)'), log=log)
            finally:
                os.environ.clear(); os.environ.update(old)
            self.assertEqual(r.returncode, 0, r.stderr)
            records = [json.loads(x) for x in log.read_text().splitlines()]
            self.assertFalse({'ANTHROPIC_SECRET', 'OPENAI_SECRET', 'OTHER_KEY', 'OTHER_TOKEN', 'LC_SECRET_KEY'} & set(records[0]['env_keys']))
            self.assertIn('TERM', records[0]['env_keys'])
            self.assertIn('LC_NUMERIC', records[0]['env_keys'])
            turn = next(x for x in records if x.get('method') == 'turn/start')
            self.assertEqual(turn['params']['effort'], 'max')

    def test_check_and_home(self):
        with tempfile.TemporaryDirectory() as home:
            argv = [sys.executable, str(BRIDGE), 'check', '--codex-home', home, '--codex-bin', str(FAKE)]
            r = subprocess.run(argv, text=True, capture_output=True)
            self.assertTrue(json.loads(r.stdout)['loggedIn'])
            Path(home, 'fake_config.json').write_text(json.dumps({'mode': 'logged_out'}))
            r = subprocess.run(argv, text=True, capture_output=True)
            self.assertEqual(r.returncode, 68)
            self.assertFalse(json.loads(r.stdout)['ok'])
            r = subprocess.run(argv[:4] + ['relative'] + argv[5:], text=True, capture_output=True)
            self.assertEqual(r.returncode, 69)

    def test_version_policy(self):
        with tempfile.TemporaryDirectory() as home:
            for version, code, status in [('0.164.9', 67, 'too_old'), ('0.165.0', 0, 'tested'), ('0.166.0', 0, 'untested'), ('0.165.0-beta.1', 67, 'too_old')]:
                Path(home, 'fake_config.json').write_text(json.dumps({'version': version}))
                r = subprocess.run([sys.executable, str(BRIDGE), 'check', '--codex-home', home, '--codex-bin', str(FAKE)], text=True, capture_output=True)
                self.assertEqual(r.returncode, code, r.stderr)
                self.assertEqual(json.loads(r.stdout)['versionStatus'], status)
                self.assertEqual(json.loads(r.stdout)['codexVersion'], version)
                if status == 'untested':
                    self.assertIn('untested codex version', json.loads(r.stdout)['warnings'])
                    self.assertNotIn('untested', r.stderr)
            Path(home, 'fake_config.json').write_text(json.dumps({'version': '0.166.0'}))
            r = subprocess.run([sys.executable, str(BRIDGE), 'messages', '--codex-home', home, '--codex-bin', str(FAKE), '--model-map', 'test=gpt-6.1-terra'], input=json.dumps(BASE), text=True, capture_output=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertNotIn('untested', r.stderr)

    def test_item_and_protocol(self):
        for mode, streamed in [('forbidden_before', False), ('forbidden_after', True)]:
            r = self.run_bridge(mode=mode)
            self.assertNotEqual(r.returncode, 0)
            self.assertIn('model-mod-http:502', r.stderr)
            self.assertIn('unsupported codex behavior', r.stdout)
            self.assertEqual('event: error' in r.stdout, streamed)
            self.assertNotIn('message_stop', r.stdout)
        for mode in ('missing_init', 'bad_flag', 'startup_fail'):
            r = self.run_bridge(mode=mode)
            self.assertEqual(r.returncode, 65)
            self.assertIn('incompatible codex app-server protocol', r.stdout)
        r = self.run_bridge(mode='forbidden_response')
        self.assertIn('unsupported codex behavior: fileChange', r.stdout)
        self.assertIn('model-mod-http:502', r.stderr)


if __name__ == '__main__': unittest.main()
