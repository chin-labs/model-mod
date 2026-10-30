import json
import base64
import argparse
import contextlib
import io
from unittest.mock import patch

import bridge
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from mapping import (InvalidRequest, classify, names, prepare, usage_delta, encode_reasoning, decode_reasoning,
                     REASONING_ITEM_LIMIT, REASONING_RESPONSE_LIMIT)

ROOT = Path(__file__).resolve().parent
BRIDGE = ROOT / 'bridge.py'
FAKE = ROOT / 'fake_codex.py'
BASE = {'model': 'test', 'max_tokens': 64, 'messages': [{'role': 'user', 'content': 'hello'}], 'stream': True}
TOOLS = [{'name': 'one', 'input_schema': {'type': 'object'}}, {'name': 'two', 'input_schema': {'type': 'object'}}]


class Contract(unittest.TestCase):
    def test_reasoning_validation_and_order(self):
        item = {'type': 'reasoning', 'id': 'id', 'summary': [{'type': 'summary_text', 'text': 'summary'}],
                'content': None, 'encrypted_content': 'opaque'}
        signature = encode_reasoning(item)
        self.assertEqual(decode_reasoning(signature), item)
        for invalid in ('gAAAAx', 'mmcx2:eyJ0eXBlIjoicmVhc29uaW5nIn0', 'mmcx1:!', 'mmcx1:e30',
                        'mmcx1:' + 'A' * REASONING_ITEM_LIMIT, signature + '='):
            self.assertIsNone(decode_reasoning(invalid))
        def raw_signature(raw): return 'mmcx1:' + base64.urlsafe_b64encode(raw.encode()).decode().rstrip('=')
        for raw in ('[]', '{"type":"reasoning","summary":[],"extra":1}',
                    '{"type":"reasoning","type":"message","summary":[]}', '{"type":"message","summary":[]}'):
            self.assertIsNone(decode_reasoning(raw_signature(raw)))
        self.assertIsNone(decode_reasoning(raw_signature('{"type":"reasoning","summary":[],"id":"\\ud800"}')))
        self.assertIsNone(encode_reasoning(dict(item, encrypted_content='\ud800')))
        self.assertIsNone(encode_reasoning(dict(item, extra='no')))
        self.assertIsNone(encode_reasoning(dict(item, summary=[{'type': 'bad', 'text': 'no'}])))
        self.assertIsNone(encode_reasoning(dict(item, encrypted_content='x' * REASONING_ITEM_LIMIT)))
        body = dict(BASE, messages=[{'role': 'user', 'content': 'hello'},
            {'role': 'assistant', 'content': [{'type': 'thinking', 'thinking': '', 'signature': signature},
                {'type': 'tool_use', 'id': 'call1', 'name': 'one', 'input': {}}]},
            {'role': 'user', 'content': [{'type': 'tool_result', 'tool_use_id': 'call1', 'content': 'done'}]}])
        history = prepare(body, {'test': 'model'})['history']
        self.assertEqual([part['type'] for part in history], ['message', 'reasoning', 'function_call', 'function_call_output'])
        self.assertEqual(history[1], item)
        self.assertNotIn('reasoning', [part['type'] for part in prepare(body, {'test': 'model'}, False)['history']])
        body['messages'][1]['content'][0]['signature'] = 'gAAAAx'
        self.assertNotIn('reasoning', [part['type'] for part in prepare(body, {'test': 'model'})['history']])
        large = encode_reasoning(dict(item, encrypted_content='x' * 140000))
        count = REASONING_RESPONSE_LIMIT // len(large)
        body['messages'][1]['content'] = [{'type': 'thinking', 'thinking': '', 'signature': large} for _ in range(count + 1)]
        limited = prepare(body, {'test': 'model'})
        self.assertEqual(sum(part['type'] == 'reasoning' for part in limited['history']), count)
        self.assertEqual(limited['dropped'], 1)

    def test_reasoning_stream_and_retry(self):
        body = dict(BASE, stream=False, tools=TOOLS)
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / 'log'
            result = self.run_bridge(body, mode='reasoning_tool', log=log)
            self.assertEqual(result.returncode, 0, result.stderr)
            content = json.loads(result.stdout)['content']
            self.assertEqual(content[0]['type'], 'thinking')
            self.assertEqual(content[2]['type'], 'tool_use')
            self.assertEqual(decode_reasoning(content[0]['signature'])['encrypted_content'], 'x' * 16)
            self.assertNotIn(content[0]['signature'], result.stderr)
            self.assertNotIn('xxxxxxxxxxxxxxxx', result.stderr)
            records = [json.loads(line) for line in log.read_text().splitlines()]
            self.assertTrue(next(row for row in records if row.get('method') == 'thread/start')['params']['experimentalRawEvents'])
            streamed = self.run_bridge(dict(body, stream=True), mode='reasoning_tool')
            self.assertEqual(streamed.returncode, 0)
            self.assertLess(streamed.stdout.index('signature_delta'), streamed.stdout.index('tool_use'))
            self.assertNotIn('xxxxxxxxxxxxxxxx', streamed.stderr)
            interleaved = self.run_bridge(body, mode='reasoning_interleaved')
            self.assertEqual(interleaved.returncode, 0, interleaved.stderr)
            blocks = json.loads(interleaved.stdout)['content']
            kept = [decode_reasoning(block['signature'])['id'] for block in blocks if block['type'] == 'thinking']
            self.assertEqual(kept, ['reason1', 'reason2'])
            self.assertLess(max(i for i, block in enumerate(blocks) if block['type'] == 'thinking'),
                            min(i for i, block in enumerate(blocks) if block['type'] == 'tool_use'))
            self.assertIn('discarded reasoning items: 2', interleaved.stderr)
            for leak in ('RAW-SECRET', 'after-call'):
                self.assertNotIn(leak, interleaved.stdout + interleaved.stderr)
            text_interleaved = self.run_bridge(body, mode='reasoning_text_interleaved')
            self.assertEqual(text_interleaved.returncode, 0, text_interleaved.stderr)
            blocks = json.loads(text_interleaved.stdout)['content']
            self.assertEqual([decode_reasoning(b['signature'])['id'] for b in blocks if b['type'] == 'thinking'], ['reason1'])
            self.assertIn('discarded reasoning items: 1', text_interleaved.stderr)
            many = self.run_bridge(body, mode='reasoning_many')
            self.assertEqual(many.returncode, 0, many.stderr)
            signatures = [b['signature'] for b in json.loads(many.stdout)['content'] if b['type'] == 'thinking']
            self.assertEqual(len(signatures), 5)
            self.assertLessEqual(sum(map(len, signatures)), REASONING_RESPONSE_LIMIT)
            self.assertIn('discarded reasoning items: 1', many.stderr)
            self.assertNotIn('140000', many.stderr)
            off = self.run_bridge(body, mode='reasoning_tool', extra=['--no-keep-reasoning'])
            self.assertNotIn('thinking', [block['type'] for block in json.loads(off.stdout)['content']])
            unavailable = self.run_bridge(body, mode='reasoning_start_error')
            self.assertEqual(unavailable.returncode, 0)
            self.assertIn('raw reasoning unavailable', unavailable.stderr)
            for mode in ('reasoning_invalid_shape', 'reasoning_large'):
                discarded = self.run_bridge(body, mode=mode)
                self.assertEqual(discarded.returncode, 0)
                self.assertNotIn('thinking', [block['type'] for block in json.loads(discarded.stdout)['content']])
                self.assertIn('discarded reasoning items: 1', discarded.stderr)
                self.assertNotIn('private', discarded.stderr)
            signature = content[0]['signature']
            replay = dict(body, messages=[{'role': 'user', 'content': 'hello'},
                {'role': 'assistant', 'content': [content[0], {'type': 'tool_use', 'id': 'call1', 'name': 'one', 'input': {}}]},
                {'role': 'user', 'content': [{'type': 'tool_result', 'tool_use_id': 'call1', 'content': 'done'}]}])
            for mode, success in [('reasoning_invalid_once', True), ('reasoning_invalid_always', False), ('reasoning_inject_error', True)]:
                path = Path(tmp) / (mode + '.log')
                response = self.run_bridge(replay, mode=mode, log=path)
                self.assertEqual(response.returncode == 0, success, response.stderr)
                rows = [json.loads(line) for line in path.read_text().splitlines()]
                injected = [row['params']['items'] for row in rows if row.get('method') == 'thread/inject_items']
                self.assertEqual(len(injected), 2)
                self.assertEqual([item['type'] for item in injected[0]], ['message', 'reasoning', 'function_call', 'function_call_output'])
                self.assertNotIn('reasoning', [item['type'] for item in injected[1]])
                self.assertEqual(response.stderr.count('reasoning discarded; retrying once'), 1)
                self.assertNotIn(signature, response.stderr)
            streaming_retry = self.run_bridge(dict(replay, stream=True), mode='reasoning_invalid_once')
            self.assertEqual(streaming_retry.returncode, 0, streaming_retry.stderr)
            self.assertEqual(streaming_retry.stdout.count('event: message_start'), 1)
            self.assertEqual(streaming_retry.stderr.count('reasoning discarded; retrying once'), 1)

    def test_account_home_boundaries(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp, 'accounts')
            outside = Path(tmp, 'outside')
            outside.mkdir()
            root.mkdir()
            def run(command, account, home):
                return subprocess.run([sys.executable, str(BRIDGE), command, '--codex-home', str(home), '--accounts-dir', str(root), '--account', account], text=True, capture_output=True)
            self.assertEqual(run('prepare-home', 'main', root / 'main').returncode, 0)
            self.assertEqual((root / 'main').stat().st_mode & 0o777, 0o700)
            (root / 'link').symlink_to(outside, target_is_directory=True)
            for account, home in [('link', root / 'link'), ('main', outside), ('main', root), ('../outside', root / '../outside'), ('Bad', root / 'Bad')]:
                self.assertEqual(run('remove-home', account, home).returncode, 69)
            self.assertTrue(outside.is_dir())
            (root / 'main' / 'auth.json').touch()
            self.assertEqual(run('remove-home', 'main', root / 'main').returncode, 70)
            self.assertTrue((root / 'main' / 'auth.json').exists())
            (root / 'main' / 'auth.json').unlink()
            self.assertEqual(run('remove-home', 'main', root / 'main').returncode, 0)
            self.assertFalse((root / 'main').exists())

    def test_device_login_cancel(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp, 'home')
            home.mkdir()
            log = Path(tmp, 'log')
            (home / 'fake_config.json').write_text(json.dumps({'log': str(log)}))
            proc = subprocess.Popen([sys.executable, str(BRIDGE), 'device-login', '--codex-home', str(home), '--codex-bin', str(FAKE), '--accounts-dir', tmp, '--account', 'home'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                data = json.loads(proc.stdout.readline())
                self.assertEqual(data, {'url': 'https://example.test/device', 'code': 'ABCD-EFGHI'})
                records = json.loads(log.read_text().splitlines()[0])
                proc.terminate()
                proc.communicate(timeout=10)
                for pid in records.values():
                    for _ in range(50):
                        try: os.kill(pid, 0)
                        except ProcessLookupError: break
                        time.sleep(.02)
                    else: self.fail('login process survived cancellation')
            finally:
                if proc.poll() is None: proc.kill(); proc.wait()
            (home / 'fake_config.json').write_text(json.dumps({'mode': 'no_device_url'}))
            failed = subprocess.run([sys.executable, str(BRIDGE), 'device-login', '--codex-home', str(home), '--codex-bin', str(FAKE), '--accounts-dir', tmp, '--account', 'home'], capture_output=True, text=True, timeout=10)
            self.assertNotEqual(failed.returncode, 0)
            self.assertNotIn('https://', failed.stdout)

    def test_device_login_lifetime_and_expiry(self):
        self.assertGreater(bridge.DEVICE_LOGIN_TIMEOUT, 15 * 60)
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp, 'home')
            home.mkdir()
            args = argparse.Namespace(codex_bin=str(FAKE), codex_home=str(home))
            config = home / 'fake_config.json'
            config.write_text(json.dumps({'mode': 'login_success', 'login_delay': .2}))
            with patch.object(bridge, 'DEVICE_LOGIN_TIMEOUT', .5), contextlib.redirect_stdout(io.StringIO()):
                self.assertTrue(bridge.device_login(args))
            self.assertTrue((home / 'auth.json').exists())
            config.write_text(json.dumps({'login_delay': 60, 'log': str(Path(tmp, 'log'))}))
            with patch.object(bridge, 'DEVICE_LOGIN_TIMEOUT', .3), contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(bridge.BridgeError, 'expired.*setup'):
                    bridge.device_login(args)
            records = json.loads(Path(tmp, 'log').read_text().splitlines()[0])
            for pid in records.values():
                for _ in range(50):
                    try: os.kill(pid, 0)
                    except ProcessLookupError: break
                    time.sleep(.02)
                else: self.fail('login process survived expiry')
            config.write_text(json.dumps({'mode': 'login_expired', 'login_delay': .01}))
            with contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(bridge.BridgeError, 'expired.*setup'):
                    bridge.device_login(args)

    def run_bridge(self, body=BASE, mode='text', log=None, extra=()):
        with tempfile.TemporaryDirectory() as home:
            Path(home, 'fake_config.json').write_text(json.dumps({'mode': mode, 'log': str(log) if log else None}))
            return subprocess.run([sys.executable, str(BRIDGE), 'messages', '--codex-home', home, '--codex-bin', str(FAKE), '--model-map', 'test=gpt-6.1-terra', *extra], input=json.dumps(body), text=True, capture_output=True, timeout=15)

    def test_web_search_config(self):
        for enabled in (False, True):
            extra = ['--web-search'] if enabled else []
            with self.subTest(enabled=enabled), tempfile.TemporaryDirectory() as tmp:
                log = Path(tmp) / 'log'
                result = self.run_bridge(log=log, extra=extra)
                self.assertEqual(result.returncode, 0, result.stderr)
                argv = json.loads(log.read_text().splitlines()[0])['argv']
                self.assertIn('web_search="' + ('live' if enabled else 'disabled') + '"', argv)
                records = [json.loads(line) for line in log.read_text().splitlines()]
                instructions = next(row['params']['developerInstructions'] for row in records if row.get('method') == 'thread/start')
                self.assertEqual('native web search' in instructions, enabled)
                mismatch = self.run_bridge(mode='bad_web_search', extra=extra)
                self.assertEqual(mismatch.returncode, 65)
                self.assertIn('incompatible codex app-server protocol (web_search)', mismatch.stdout)
        for mode in ('forbidden_unknown', 'forbidden_mcp', 'forbidden_before', 'forbidden_response'):
            with self.subTest(mode=mode):
                result = self.run_bridge(mode=mode, extra=['--web-search'])
                self.assertEqual(result.returncode, 1)
                self.assertIn('unsupported_item', result.stdout)

    def test_web_search_summaries(self):
        for stream in (False, True):
            result = self.run_bridge(dict(BASE, stream=stream), mode='web_search', extra=['--web-search'])
            self.assertEqual(result.returncode, 0, result.stderr)
            if stream:
                frames = [json.loads(line[6:]) for line in result.stdout.splitlines() if line.startswith('data: ')]
                texts = [frame['delta']['text'] for frame in frames if frame.get('delta', {}).get('type') == 'text_delta']
            else:
                texts = [block['text'] for block in json.loads(result.stdout)['content'] if block['type'] == 'text']
            self.assertEqual(texts[0], 'hello')
            self.assertEqual(texts[1], '\nSearched: ' + ('hello world ' + 'x' * 200)[:120] + '\n')
            self.assertEqual(texts[2:], ['\nOpened page\n', '\nSearched within page\n', '\nUsed web search\n', 'done'])
            self.assertNotIn('opaque secret', result.stdout)
            self.assertNotIn('example.test', result.stdout)
        disabled = self.run_bridge(mode='web_search')
        self.assertIn('unsupported_item', disabled.stdout)

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

    def test_wait_items_end_turn(self):
        for mode in ('wait_started', 'wait_completed', 'wait_response', 'wait_turn'):
            for stream in (True, False):
                with self.subTest(mode=mode, stream=stream), tempfile.TemporaryDirectory() as tmp:
                    log = Path(tmp) / 'log'
                    r = self.run_bridge(dict(BASE, stream=stream, system='client system'), mode, log)
                    self.assertEqual(r.returncode, 0, r.stderr)
                    self.assertNotIn('event: error', r.stdout)
                    self.assertNotIn('model-mod-http:502', r.stderr)
                    self.assertIn('"stop_reason": "end_turn"', r.stdout)
                    self.assertNotIn('discarded', r.stdout)
                    self.assertIn('"input_tokens": 60', r.stdout)
                    if mode != 'wait_response': self.assertIn('hello', r.stdout)
                    records = [json.loads(x) for x in log.read_text().splitlines()]
                    start = next(x for x in records if x.get('method') == 'thread/start')
                    self.assertEqual(start['params']['baseInstructions'], 'client system')
                    self.assertIn('provided function tools', start['params']['developerInstructions'])
                    self.assertEqual(sum(x.get('method') == 'turn/interrupt' for x in records), 1)
                    with self.assertRaises(ProcessLookupError): os.kill(records[0]['pid'], 0)

        for stream in (True, False):
            r = self.run_bridge(dict(BASE, stream=stream, tools=TOOLS), 'wait_tool')
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn('"type": "tool_use", "id": "call1"', r.stdout)
            self.assertIn('"stop_reason": "tool_use"', r.stdout)
            self.assertIn('"input_tokens": 60', r.stdout)
            r = self.run_bridge(dict(BASE, stream=stream), 'wait_forbidden')
            self.assertIn('model-mod-http:502', r.stderr)
            self.assertIn('unsupported_item', r.stdout)

    def test_parallel_tools_and_interrupt(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / 'log'
            r = self.run_bridge(dict(BASE, tools=TOOLS), 'tools', log)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(r.stdout.count('"type": "tool_use", "id"'), 2)
            self.assertIn('"stop_reason": "tool_use"', r.stdout)
            calls = [json.loads(x) for x in log.read_text().splitlines()]
            self.assertFalse({'OPENAI_API_KEY', 'CODEX_API_KEY', 'ANTHROPIC_API_KEY'} & set(calls[0]['env_keys']))
            for feature in ('unified_exec', 'sleep_tool', 'computer_use', 'tool_suggest', 'skill_search', 'plugins', 'remote_plugin', 'hooks', 'guardian_approval', 'incremental_tools', 'browser_annotation_api', 'browser_use_external', 'browser_use_full_cdp_access', 'plugin_sharing', 'skill_mcp_dependency_install'):
                self.assertIn(feature, calls[0]['argv'])
                self.assertEqual(calls[0]['argv'][calls[0]['argv'].index(feature) - 1], '--disable')
            self.assertNotIn('code_mode_host', calls[0]['argv'])
            for setting in ('include_permissions_instructions=false', 'include_environment_context=false'):
                self.assertIn(setting, calls[0]['argv'])
                self.assertEqual(calls[0]['argv'][calls[0]['argv'].index(setting) - 1], '-c')
            self.assertEqual(sum(c.get('method') == 'turn/interrupt' for c in calls), 1)
            self.assertIn('model_auto_compact_token_limit=140800', calls[0]['argv'])

    def test_parallel_batch(self):
        for mode in ('parallel_zero', 'parallel_50'):
            for stream in (False, True):
                r = self.run_bridge(dict(BASE, tools=TOOLS, stream=stream), mode)
                self.assertEqual(r.returncode, 0, r.stderr)
                if stream:
                    frames = [json.loads(line[6:]) for line in r.stdout.splitlines() if line.startswith('data: ')]
                    uses = [f for f in frames if f.get('content_block', {}).get('type') == 'tool_use']
                    self.assertEqual([f['index'] for f in uses], [1, 2, 3])
                    self.assertEqual([f['content_block']['id'] for f in uses], ['call1', 'call2', 'call3'])
                    self.assertEqual(frames[-2]['delta']['stop_reason'], 'tool_use')
                    self.assertEqual(frames[-1]['type'], 'message_stop')
                else:
                    result = json.loads(r.stdout)
                    self.assertEqual([b['id'] for b in result['content'] if b['type'] == 'tool_use'], ['call1', 'call2', 'call3'])
                    self.assertEqual(result['stop_reason'], 'tool_use')

    def test_catalog_windows(self):
        with tempfile.TemporaryDirectory() as home:
            Path(home, 'models_cache.json').write_text(json.dumps({'models': [{'slug': 'gpt-6.1-terra', 'context_window': 500000, 'effective_context_window_percent': 95}]}))
            argv = [sys.executable, str(BRIDGE), 'windows', '--codex-home', home]
            result = subprocess.run(argv, text=True, capture_output=True)
            self.assertEqual(json.loads(result.stdout)['windows'], {'gpt-6.1-terra': 475000})
            Path(home, 'models_cache.json').unlink()
            result = subprocess.run(argv, text=True, capture_output=True)
            self.assertEqual(json.loads(result.stdout)['windows'], {})
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / 'log'
            result = self.run_bridge(mode='compaction', log=log, extra=['--context-window', '272000', '--catalog-window', '475000'])
            records = [json.loads(line) for line in log.read_text().splitlines()]
            self.assertIn('model_auto_compact_token_limit=522500', records[0]['argv'])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('context compaction observed', result.stderr)
        self.assertIn('reported model context window differs', result.stderr)
        self.assertNotIn('context compaction observed', result.stdout)

    def test_history_and_names(self):
        parallel = prepare(dict(BASE, tools=TOOLS, messages=[
            {'role': 'assistant', 'content': [{'type': 'tool_use', 'name': 'one', 'id': 'c' + str(n), 'input': {'n': n}} for n in range(3)]},
            {'role': 'user', 'content': [{'type': 'tool_result', 'tool_use_id': 'c' + str(n), 'content': 'result' + str(n)} for n in range(3)]},
        ]), {'test': 'gpt-6.1-terra'})
        self.assertEqual([(item['type'], item['call_id']) for item in parallel['history']],
                         [('function_call', 'c0'), ('function_call', 'c1'), ('function_call', 'c2'),
                          ('function_call_output', 'c0'), ('function_call_output', 'c1'), ('function_call_output', 'c2')])
        self.assertEqual([item['output'] for item in parallel['history'][3:]], ['result0', 'result1', 'result2'])
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
        request['messages'][1]['content'][0]['content'] = [{'type': 'tool_reference', 'tool_name': reserved}]
        history = prepare(request, {'test': 'gpt-6.1-terra'})
        self.assertEqual(history['history'][1]['output'], 'ERROR: Loaded tool: ' + reserved)
        request['messages'][1]['content'][0]['content'].append({'type': 'tool_reference', 'tool_name': 'other'})
        history = prepare(request, {'test': 'gpt-6.1-terra'})
        self.assertEqual(history['history'][1]['output'], 'ERROR: Loaded tool: ' + reserved + '\nLoaded tool: other')
        request['messages'][1]['content'][0]['content'] = [{'type': 'text', 'text': 'before'}, {'type': 'tool_reference', 'tool_name': 'a'}, {'type': 'text', 'text': 'after'}]
        history = prepare(request, {'test': 'gpt-6.1-terra'})
        self.assertEqual(history['history'][1]['output'], 'ERROR: before\nLoaded tool: a\nafter')
        request['messages'][1]['content'][0]['content'] = [{'type': 'text', 'text': 'before\n'}, {'type': 'tool_reference', 'tool_name': 'a'}, {'type': 'text', 'text': '\nafter'}]
        history = prepare(request, {'test': 'gpt-6.1-terra'})
        self.assertEqual(history['history'][1]['output'], 'ERROR: before\nLoaded tool: a\nafter')
        request['messages'][1]['content'][0]['content'] = [{'type': 'unknown\n' + 'x' * 70}]
        r = self.run_bridge(request)
        self.assertIn('model-mod-http:400', r.stderr)
        self.assertIn('invalid tool result content (unknown' + 'x' * 57 + ')', json.loads(r.stdout)['error']['message'])
        request['messages'][1]['content'][0]['content'] = [{'type': 'tool_reference', 'tool_name': ''}]
        with self.assertRaisesRegex(InvalidRequest, r'invalid tool result content \(tool_reference\)'):
            prepare(request, {'test': 'gpt-6.1-terra'})
        with self.assertRaises(InvalidRequest): names(tools + [{'name': encoded, 'input_schema': {}}])

    def test_errors_and_version(self):
        self.assertEqual(classify({'message': 'not a rate limit; 429 in user input'}), (500, 'api_error'))
        self.assertEqual(classify({'codexErrorInfo': 'rateLimitExceeded'}), (429, 'rate_limit_error'))
        self.assertEqual(classify({'codexErrorInfo': 'usageLimitExceeded'}), (429, 'rate_limit_error'))
        for status, expected in ((429, (429, 'rate_limit_error')), (400, (400, 'invalid_request_error')), (503, (500, 'api_error'))):
            self.assertEqual(classify({'codexErrorInfo': {'httpConnectionFailed': {'httpStatusCode': status}}}), expected)
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
        # A rebuilt app-server must still be cancellable.
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, 'fake_config.json').write_text(json.dumps({'mode': 'reasoning_invalid_once', 'hang': True}))
            reasoning = {'type': 'thinking', 'thinking': '', 'signature': encode_reasoning({'type': 'reasoning', 'id': 'r', 'summary': [], 'content': None, 'encrypted_content': 'opaque'})}
            replay = dict(BASE, tools=TOOLS, messages=[{'role': 'user', 'content': 'hello'},
                {'role': 'assistant', 'content': [reasoning, {'type': 'tool_use', 'id': 'call1', 'name': 'one', 'input': {}}]},
                {'role': 'user', 'content': [{'type': 'tool_result', 'tool_use_id': 'call1', 'content': 'done'}]}])
            p = subprocess.Popen([sys.executable, str(BRIDGE), 'messages', '--codex-home', tmp, '--codex-bin', str(FAKE), '--model-map', 'test=gpt-6.1-terra', '--max-seconds', '30'], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
            try:
                p.stdin.write(json.dumps(replay)); p.stdin.close()
                while True:
                    line = p.stdout.readline()
                    if not line: self.fail('stream ended before the rebuilt turn')
                    if line.startswith('event: content_block_delta'): break
                p.send_signal(signal.SIGTERM)
                p.wait(timeout=5)
                stderr = p.stderr.read()
                self.assertIn('reasoning discarded; retrying once', stderr)
                self.assertIn('model-mod-http:499', stderr)
            finally:
                if p.poll() is None: p.kill(); p.wait()
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

    def test_catalog_and_account_data(self):
        with tempfile.TemporaryDirectory() as home:
            log = Path(home, 'log')
            config = Path(home, 'fake_config.json')
            model = {'id': 'gpt-6.1-terra', 'displayName': 'Terra',
                     'supportedReasoningEfforts': [{'reasoningEffort': x, 'description': ''} for x in ('minimal', 'medium', 'xhigh')],
                     'defaultReasoningEffort': 'medium'}
            limits = {'ordinaryUsageAllowed': False, 'rateLimits': {'primary': {'usedPercent': 38, 'resetsAt': 123, 'windowDurationMins': 300},
                      'credits': {'hasCredits': True, 'balance': '5', 'unlimited': False}, 'rateLimitReachedType': 'weekly'}}
            config.write_text(json.dumps({'log': str(log), 'models': [model], 'rate_limits': limits}))
            def run(command, *args, body=None):
                return subprocess.run([sys.executable, str(BRIDGE), command, '--codex-home', home, '--codex-bin', str(FAKE), *args], input=json.dumps(body) if body else None, text=True, capture_output=True, timeout=15)
            for suffix, expected in [('(low)', 'medium'), ('(high)', 'medium'), ('(max)', 'xhigh'), ('', 'medium')]:
                r = run('messages', '--model-map', 'test=gpt-6.1-terra', body=dict(BASE, model='test' + suffix))
                self.assertEqual(r.returncode, 0, r.stderr)
                turn = [json.loads(x) for x in log.read_text().splitlines() if '"method": "turn/start"' in x][-1]
                self.assertEqual(turn['params']['effort'], expected)
                self.assertNotIn('serviceTier', turn['params'])
            r = run('messages', '--model-map', 'test=gpt-6.1-terra', '--service-tier', 'priority', body=BASE)
            self.assertEqual(r.returncode, 0, r.stderr)
            turn = [json.loads(x) for x in log.read_text().splitlines() if '"method": "turn/start"' in x][-1]
            self.assertEqual(turn['params']['serviceTier'], 'priority')
            Path(home, 'models_cache.json').write_text(json.dumps({'models': [{'slug': 'gpt-6.1-terra', 'supported_reasoning_levels': [{'effort': 'high'}], 'default_reasoning_level': 'high'}]}))
            before = len(log.read_text().splitlines())
            cached = run('messages', '--model-map', 'test=gpt-6.1-terra', body=dict(BASE, model='test(max)'))
            self.assertEqual(cached.returncode, 0, cached.stderr)
            requests = [json.loads(x) for x in log.read_text().splitlines()[before:]]
            self.assertFalse(any(row.get('method') == 'model/list' for row in requests))
            self.assertEqual(next(row for row in requests if row.get('method') == 'turn/start')['params']['effort'], 'high')
            self.assertEqual(json.loads(run('models').stdout)['models'][0]['efforts'], ['minimal', 'medium', 'xhigh'])
            result = json.loads(run('rate-limits').stdout)
            self.assertEqual(result['primary'], {'remainingPercent': 62, 'resetsAt': 123, 'windowDurationMins': 300})
            self.assertEqual(result['credits']['balance'], '5')
            self.assertFalse(result['ordinaryUsageAllowed'])
            account = run('account-info')
            self.assertEqual(json.loads(account.stdout), {'loginMethod': 'chatgpt', 'planType': 'plus'})
            self.assertNotIn('private@example.test', account.stdout + account.stderr)

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
        for mode in ('forbidden_mcp', 'forbidden_unknown'):
            r = self.run_bridge(mode=mode)
            self.assertNotEqual(r.returncode, 0)
            self.assertIn('model-mod-http:502', r.stderr)
            self.assertIn('unsupported codex behavior', r.stdout)
        for mode in ('missing_init', 'bad_flag', 'bad_unified_exec', 'startup_fail'):
            r = self.run_bridge(mode=mode)
            self.assertEqual(r.returncode, 65)
            self.assertIn('incompatible codex app-server protocol', r.stdout)
        r = self.run_bridge(mode='forbidden_response')
        self.assertIn('unsupported codex behavior: fileChange', r.stdout)
        self.assertIn('model-mod-http:502', r.stderr)


if __name__ == '__main__': unittest.main()
