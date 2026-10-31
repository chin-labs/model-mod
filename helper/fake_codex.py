#!/usr/bin/env python3
"""Fake app-server for offline JSONL contract tests."""
import json
import os
import signal
import subprocess
import sys
import time
import threading


def send(value):
    print(json.dumps(value), flush=True)


try:
    with open(os.path.join(os.environ['CODEX_HOME'], 'fake_config.json'), encoding='utf-8') as f: config = json.load(f)
except (OSError, KeyError): config = {}


def record(value):
    path = config.get('log')
    if path:
        with open(path, 'a', encoding='utf-8') as f: f.write(json.dumps(value) + '\n')


def event(method, params):
    send({'method': method, 'params': params})


if '--version' in sys.argv:
    print('codex-cli ' + config.get('version', '0.0.0' if config.get('mode') == 'version' else '0.165.0'))
    sys.exit(0)
if 'logout' in sys.argv:
    sys.exit(1 if config.get('mode') == 'logout_fail' else 0)
if 'login' in sys.argv and '--device-auth' in sys.argv:
    child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
    record({'pid': os.getpid(), 'child': child.pid})
    if config.get('mode') != 'no_device_url':
        print('1. Open this link in your browser and sign in to your account', flush=True)
        print('   \x1b[94mhttps://example.test/device\x1b[0m', flush=True)
        print('2. Enter this one-time code \x1b[90m(expires in 15 minutes)\x1b[0m', flush=True)
        print('   \x1b[94mABCD-EFGHI\x1b[0m', flush=True)
        time.sleep(config.get('login_delay', 60))
        if config.get('mode') == 'login_success':
            with open(os.path.join(os.environ['CODEX_HOME'], 'auth.json'), 'w', encoding='utf-8') as f: f.write('{}')
            sys.exit(0)
        if config.get('mode') == 'login_expired': print('Device code expired', flush=True)
    sys.exit(1)
if 'status' in sys.argv:
    print('Logged in using ChatGPT')
    sys.exit(1 if config.get('mode') == 'logged_out' else 0)
mode = config.get('mode', 'text')
interrupted = threading.Event()
if mode == 'startup_fail':
    print('unknown option --disable', file=sys.stderr, flush=True)
    sys.exit(2)
record({'pid': os.getpid(), 'env_keys': sorted(os.environ), 'argv': sys.argv[1:]})
if mode == 'stubborn':
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    child = subprocess.Popen([sys.executable, '-c', 'import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    record({'child': child.pid})
for line in sys.stdin:
    req = json.loads(line)
    record(req)
    method, ident, params = req.get('method'), req.get('id'), req.get('params', {})
    if method == 'initialize':
        send({'id': ident, 'result': {} if mode == 'missing_init' else {'userAgent': 'fake', 'codexHome': os.environ['CODEX_HOME'], 'platformFamily': 'unix', 'platformOs': 'test'}})
    elif method == 'config/read':
        features = dict.fromkeys(('apps', 'multi_agent', 'unified_exec', 'shell_tool', 'view_image', 'image_generation', 'browser_use', 'in_app_browser', 'goals', 'sleep_tool', 'computer_use', 'tool_suggest', 'skill_search', 'plugins', 'remote_plugin', 'hooks', 'guardian_approval', 'incremental_tools', 'browser_annotation_api', 'browser_use_external', 'browser_use_full_cdp_access', 'plugin_sharing', 'skill_mcp_dependency_install'), False)
        features['memories'] = False
        if '--enable' in sys.argv and 'image_generation' in sys.argv: features['image_generation'] = True
        if mode == 'bad_flag': features['shell_tool'] = True
        if mode == 'bad_unified_exec': features['unified_exec'] = True
        web_search = 'live' if 'web_search="live"' in sys.argv else 'disabled'
        if mode == 'bad_web_search': web_search = 'disabled' if web_search == 'live' else 'live'
        layers = [{'name': {'type': 'user'}, 'disabledReason': None}]
        project = {'name': {'type': 'project', 'dotCodexFolder': os.path.join(params.get('cwd', ''), '.codex')}, 'disabledReason': None}
        if mode == 'delegate_project_active' or (mode == 'delegate_project_after' and os.path.exists(os.path.join(os.environ['CODEX_HOME'], 'started'))):
            layers.append(project)
        elif os.path.isdir(project['name']['dotCodexFolder']):
            layers.append(dict(project, disabledReason='Project is not trusted'))
        if mode == 'delegate_layers_empty': layers = []
        if mode == 'delegate_layers_unknown': layers = [{'name': {'type': 'unknown'}}]
        if mode == 'delegate_layers_boolean': layers = [dict(project, disabledReason=True)]
        if mode == 'delegate_layers_no_reason': layers = [{'name': project['name']}]
        result = {'config': {'web_search': web_search, 'features': features, 'mcp_servers': {}}, 'layers': layers}
        if mode == 'delegate_trust_record' and os.path.exists(os.path.join(os.environ['CODEX_HOME'], 'started')):
            result['config']['projects'] = {params['cwd']: {'trust_level': 'trusted'}}
        if mode == 'delegate_layers_missing' or not params.get('includeLayers'): del result['layers']
        send({'id': ident, 'result': result})
    elif method == 'thread/start':
        if mode == 'reasoning_start_error' and params.get('experimentalRawEvents'):
            send({'id': ident, 'error': {'code': -32000, 'message': 'synthetic'}})
        elif mode in ('rejected_request', 'rejected_params'):
            send({'id': ident, 'error': {'code': -32600 if mode == 'rejected_request' else -32602, 'message': 'untrusted details'}})
        elif mode in ('bad', 'rate'):
            print('synthetic app-server failure ' + 'A' * 80, file=sys.stderr, flush=True)
            send({'id': ident, 'error': {'code': -32000 if mode == 'bad' else 429, 'message': 'invalid request' if mode == 'bad' else 'rate limit', 'retryAfter': 7}})
        else:
            if mode == 'forbidden_before': event('item/started', {'item': {'type': 'commandExecution'}})
            sandbox = {'type': 'workspaceWrite' if mode == 'delegate_bad_sandbox' else 'readOnly', 'networkAccess': False}
            if mode in ('delegate_project_after', 'delegate_trust_record'):
                open(os.path.join(os.environ['CODEX_HOME'], 'started'), 'w').close()
            if params.get('sandbox') == 'workspace-write':
                cwd = params['cwd']
                override = params.get('config', {}).get('projects', {}).get(cwd, {}).get('trust_level')
                if override != 'untrusted':
                    with open(os.path.join(os.environ['CODEX_HOME'], 'config.toml'), 'a', encoding='utf-8') as f:
                        f.write('\n[projects.' + json.dumps(cwd) + ']\ntrust_level = "trusted"\n')
                if mode != 'delegate_bad_sandbox':
                    roots = {'delegate_root_cwd': [cwd], 'delegate_root_extra': [cwd, '/'],
                             'delegate_root_nonstring': [None], 'delegate_root_symlink': [config.get('root_alias', '/')],
                             'delegate_root_relative': [config.get('relative_root', '.')], 'delegate_root_string': cwd}.get(mode, [])
                    sandbox = {'type': 'workspaceWrite', 'writableRoots': roots, 'networkAccess': False, 'excludeTmpdirEnvVar': True, 'excludeSlashTmp': True}
                    if mode == 'delegate_root_missing': del sandbox['writableRoots']
            if mode == 'delegate_network': sandbox['networkAccess'] = True
            send({'id': ident, 'result': {'thread': {'id': 'invalid' if mode == 'invalid_uuid' else '12345678-1234-4234-8234-123456789abc'}, 'approvalPolicy': 'on-request' if mode == 'delegate_approval_mismatch' else 'never', 'sandbox': sandbox}})
    if method == 'thread/start' and mode == 'delegate_no_read':
        while True: time.sleep(1)
    elif method == 'thread/inject_items':
        if mode == 'reasoning_inject_error' and any(item.get('type') == 'reasoning' for item in params['items']):
            send({'id': ident, 'error': {'code': -32602, 'message': 'synthetic'}})
        else: send({'id': ident, 'result': {}})
    elif method == 'externalAgentConfig/detect':
        sessions = [{'path': config['session_path'], 'cwd': config['session_cwd'], 'title': None}]
        if mode == 'transfer_multiple': sessions.append(dict(sessions[0]))
        send({'id': ident, 'result': {'items': [{'itemType': 'CONFIG', 'description': 'ignored'}, {'itemType': 'SESSIONS', 'description': 'sessions', 'cwd': None, 'details': {'sessions': sessions}}]}})
    elif method == 'externalAgentConfig/import':
        send({'id': ident, 'result': {'importId': 'import1'}})
        if mode == 'transfer_exit': sys.exit(0)
        if mode != 'transfer_timeout':
            event('externalAgentConfig/import/completed', {'importId': 'import1', 'itemTypeResults': [{'itemType': 'SESSIONS', 'failures': [], 'successes': [{'itemType': 'SESSIONS', 'source': '/different/session' if mode == 'transfer_wrong_source' else config['session_path'], 'target': 'invalid' if mode == 'transfer_invalid_id' else '12345678-1234-4234-8234-123456789abc'}]}]})
    elif method == 'turn/start':
        items = [{'type': 'sleep'}, {'type': 'commandExecution'}] if mode == 'wait_forbidden' else [{'type': 'fileChange'}] if mode == 'forbidden_response' else ([{'type': 'sleep'}] if mode == 'wait_response' else [])
        send({'id': ident, 'result': {'turn': {'id': 'turn1', 'items': items}}})
        if mode in ('delegate_approval', 'gate_approval'):
            send({'id': 'approval1', 'method': 'item/commandExecution/requestApproval', 'params': {}})
            send({'id': 'approval2', 'method': 'item/fileChange/requestApproval', 'params': {}})
            for _ in range(2):
                response = json.loads(next(sys.stdin))
                record(response)
        if mode in ('delegate_unknown', 'delegate_unknown_number'):
            send({'id': 7 if mode == 'delegate_unknown_number' else 'unknown1', 'method': 'future/unknown', 'params': {}})
            response = json.loads(next(sys.stdin))
            record(response)
            continue
        if mode == 'delegate_filechange':
            event('item/started', {'item': {'type': 'fileChange'}})
            continue
        if mode in ('reasoning_invalid_once', 'reasoning_invalid_always'):
            count_file = os.path.join(os.environ['CODEX_HOME'], 'fake_turn_count')
            try:
                with open(count_file, encoding='utf-8') as f: count = int(f.read())
            except (OSError, ValueError): count = 0
            with open(count_file, 'w', encoding='utf-8') as f: f.write(str(count + 1))
            if mode == 'reasoning_invalid_always' or count == 0:
                event('turn/completed', {'turn': {'id': 'turn1', 'status': 'failed', 'error': {'message': 'invalid_encrypted_content', 'code': 400}}})
                continue
            if config.get('hang'):
                def send_deltas():
                    while not interrupted.is_set():
                        event('item/agentMessage/delta', {'delta': 'hello'})
                        time.sleep(0.05)
                threading.Thread(target=send_deltas, daemon=True).start()
                continue
        if mode in ('reasoning_tool', 'reasoning_interleaved', 'reasoning_text_interleaved', 'reasoning_invalid_shape', 'reasoning_large', 'reasoning_many'):
            reasoning = {'type': 'reasoning', 'id': 'reason1', 'summary': [], 'content': None,
                         'encrypted_content': 'x' * (300000 if mode == 'reasoning_large' else 140000 if mode == 'reasoning_many' else 16)}
            if mode == 'reasoning_invalid_shape': reasoning['unexpected'] = 'private'
            event('rawResponseItem/completed', {'item': reasoning, 'threadId': '12345678-1234-4234-8234-123456789abc', 'turnId': 'turn1'})
            if mode == 'search_after_tool':
                event('item/completed', {'item': {'type': 'webSearch', 'id': 'late', 'query': 'late search'}})
            if mode == 'reasoning_interleaved':
                event('rawResponseItem/completed', {'item': {'type': 'message', 'role': 'assistant', 'content': [{'type': 'output_text', 'text': 'RAW-SECRET-message'}]}})
                event('rawResponseItem/completed', {'item': dict(reasoning, id='reason2')})
                event('rawResponseItem/completed', {'item': {'type': 'function_call_output', 'call_id': 'raw1', 'output': 'RAW-SECRET-output'}})
                event('rawResponseItem/completed', {'item': {'type': 'function_call', 'call_id': 'raw1', 'name': 'one', 'arguments': 'RAW-SECRET-call'}})
                event('rawResponseItem/completed', {'item': dict(reasoning, id='after-call')})
            if mode == 'reasoning_many':
                for n in range(2, 7): event('rawResponseItem/completed', {'item': dict(reasoning, id='reason' + str(n))})
        if mode in ('gate', 'gate_approval', 'gate_commentary'):
            text = config.get('gateText', json.dumps({'verdict': 'pass', 'findings': [], 'needsHuman': False}))
            if mode == 'gate_commentary':
                commentary = 'Let me inspect the diff.'
                event('item/agentMessage/delta', {'delta': commentary})
                event('item/completed', {'item': {'type': 'agentMessage', 'phase': 'commentary', 'text': commentary}})
        elif mode == 'delegate_echo':
            text = params['input'][0]['text'] + '\n' + os.environ['CODEX_HOME']
        else:
            text = '\x1b[31mhello\x1b[0m\x01' + 'x' * 65000 if mode == 'delegate_long' else 'hello'
        event('item/agentMessage/delta', {'delta': text})
        if mode == 'gate_commentary': event('item/completed', {'item': {'type': 'agentMessage', 'phase': 'final_answer', 'text': text}})
        if mode == 'reasoning_text_interleaved':
            event('rawResponseItem/completed', {'item': {'type': 'reasoning', 'id': 'after-text', 'summary': [], 'encrypted_content': 'opaque'}})
        if mode == 'wait_tool':
            event('item/started', {'item': {'type': 'sleep'}})
            event('item/tool/call', {'callId': 'call1', 'tool': 'one', 'arguments': {'n': 1}})
            continue
        if mode in ('wait_started', 'wait_completed', 'wait_response', 'wait_turn'):
            if mode in ('wait_started', 'wait_completed'):
                event('item/' + mode.removeprefix('wait_'), {'item': {'type': 'collabAgentToolCall'}})
            elif mode == 'wait_turn':
                event('turn/started', {'turn': {'id': 'turn1', 'items': [{'type': 'sleep'}]}})
            event('item/agentMessage/delta', {'delta': 'discarded'})
            event('item/started', {'item': {'type': 'commandExecution'}})
            continue
        if mode in ('abort', 'chatty', 'stubborn', 'image_wait'): continue
        if mode.startswith('image_'):
            import base64
            raw = b'\x89PNG\r\n\x1a\nimage'
            item = {'type': 'imageGeneration', 'status': 'failed' if mode == 'image_failure' else 'completed',
                    'result': base64.b64encode(raw).decode(), 'savedPath': config.get('savedPath')}
            if mode == 'image_large': item['result'] = 'A' * (28 * 1024 * 1024)
            event('item/completed', {'item': item})
            event('turn/completed', {'turn': {'id': 'turn1', 'status': 'completed'}})
            continue
        if mode == 'forbidden_after': event('item/started', {'item': {'type': 'webSearch'}}); continue
        if mode == 'web_search':
            for i, action in enumerate(('search', 'openPage', 'findInPage', 'other')):
                item = {'type': 'webSearch', 'id': 'web' + str(i), 'query': 'hello\x00\x1bworld ' + 'x' * 200,
                        'action': {'type': action, 'url': 'https://example.test/private'}, 'results': [{'text': 'opaque secret'}]}
                event('item/started', {'item': dict(item, query='')})
                event('item/completed', {'item': item})
                event('item/completed', {'item': item})
            event('item/agentMessage/delta', {'delta': 'done'})
        if mode in ('forbidden_mcp', 'forbidden_unknown'):
            event('item/completed', {'item': {'type': 'mcpToolCall', 'tool': 'other'} if mode == 'forbidden_mcp' else {'type': 'futureTool'}})
            continue
        if mode == 'miderror':
            event('error', {'error': {'message': 'upstream error'}, 'willRetry': False})
        elif mode in ('parallel_zero', 'parallel_50'):
            def send_calls():
                for n in range(1, 4):
                    if n > 1 and mode == 'parallel_50' and interrupted.wait(0.05): break
                    if interrupted.is_set(): break
                    event('item/tool/call', {'callId': 'call' + str(n), 'tool': 'one', 'arguments': {'n': n}})
            threading.Thread(target=send_calls, daemon=True).start()
        elif mode == 'compaction':
            event('item/completed', {'item': {'type': 'contextCompaction'}})
            event('thread/tokenUsage/updated', {'tokenUsage': {'modelContextWindow': 475000, 'total': {'inputTokens': 10}}})
            event('turn/completed', {'turn': {'id': 'turn1', 'status': 'completed'}})
        elif mode in ('tools', 'reasoning_tool', 'reasoning_interleaved', 'reasoning_text_interleaved', 'reasoning_invalid_shape', 'reasoning_large', 'reasoning_many', 'search_after_tool'):
            event('item/tool/call', {'callId': 'call1', 'tool': 'one', 'arguments': {'n': 1}})
            if mode == 'search_after_tool':
                event('item/completed', {'item': {'type': 'webSearch', 'id': 'late', 'query': 'late search'}})
            if mode == 'reasoning_interleaved':
                event('rawResponseItem/completed', {'item': {'type': 'reasoning', 'id': 'reason3', 'summary': [], 'encrypted_content': 'opaque'}})
            event('item/tool/call', {'callId': 'call2', 'tool': 'two', 'arguments': {'n': 2}})
        else:
            if mode == 'delegate_delay': time.sleep(1)
            event('thread/tokenUsage/updated', {'tokenUsage': {'total': {'inputTokens': 100, 'cachedInputTokens': 40, 'outputTokens': 9}}})
            event('turn/completed', {'turn': {'id': 'turn1', 'status': 'completed'}})
    elif method == 'turn/interrupt':
        interrupted.set()
        if mode == 'stubborn':
            while True: time.sleep(1)
        if mode == 'chatty':
            while True:
                event('item/agentMessage/delta', {'delta': 'hello'})
                time.sleep(0.05)
        send({'id': ident, 'result': {}})
        event('thread/tokenUsage/updated', {'tokenUsage': {'total': {'inputTokens': 100, 'cachedInputTokens': 40, 'outputTokens': 9}}})
        event('turn/completed', {'turn': {'id': 'turn1', 'status': 'interrupted'}})
    elif method == 'model/list': send({'id': ident, 'result': {'data': config.get('models', [{'id': 'chat', 'displayName': 'Chat'}, {'id': 'image', 'displayName': 'Image'}]), 'nextCursor': None}})
    elif method == 'account/rateLimits/read': send({'id': ident, 'result': config.get('rate_limits', {'rateLimits': {'primary': {'usedPercent': 30}}, 'ordinaryUsageAllowed': True})})
    elif method == 'account/read': send({'id': ident, 'result': {'account': config.get('account', {'type': 'chatgpt', 'planType': 'plus', 'email': 'private@example.test'})}})

if mode == 'stubborn':
    while True: time.sleep(1)
