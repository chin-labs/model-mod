#!/usr/bin/env python3
"""Fake app-server for offline JSONL contract tests."""
import json
import os
import sys
import time


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
if 'status' in sys.argv:
    print('Logged in using ChatGPT')
    sys.exit(1 if config.get('mode') == 'logged_out' else 0)
mode = config.get('mode', 'text')
if mode == 'startup_fail':
    print('unknown option --disable', file=sys.stderr, flush=True)
    sys.exit(2)
record({'pid': os.getpid(), 'env_keys': sorted(os.environ), 'argv': sys.argv[1:]})
for line in sys.stdin:
    req = json.loads(line)
    record(req)
    method, ident, params = req.get('method'), req.get('id'), req.get('params', {})
    if method == 'initialize':
        send({'id': ident, 'result': {} if mode == 'missing_init' else {'userAgent': 'fake', 'codexHome': os.environ['CODEX_HOME'], 'platformFamily': 'unix', 'platformOs': 'test'}})
    elif method == 'config/read':
        features = dict.fromkeys(('apps', 'multi_agent', 'unified_exec', 'shell_tool', 'view_image', 'image_generation', 'browser_use', 'in_app_browser', 'goals', 'sleep_tool', 'computer_use', 'tool_suggest', 'skill_search', 'plugins', 'remote_plugin', 'hooks', 'guardian_approval', 'incremental_tools', 'browser_annotation_api', 'browser_use_external', 'browser_use_full_cdp_access', 'plugin_sharing', 'skill_mcp_dependency_install'), False)
        if mode == 'bad_flag': features['shell_tool'] = True
        if mode == 'bad_unified_exec': features['unified_exec'] = True
        send({'id': ident, 'result': {'config': {'web_search': 'disabled', 'features': features}}})
    elif method == 'thread/start':
        if mode in ('rejected_request', 'rejected_params'):
            send({'id': ident, 'error': {'code': -32600 if mode == 'rejected_request' else -32602, 'message': 'untrusted details'}})
        elif mode in ('bad', 'rate'):
            print('synthetic app-server failure ' + 'A' * 80, file=sys.stderr, flush=True)
            send({'id': ident, 'error': {'code': -32000 if mode == 'bad' else 429, 'message': 'invalid request' if mode == 'bad' else 'rate limit', 'retryAfter': 7}})
        else:
            if mode == 'forbidden_before': event('item/started', {'item': {'type': 'commandExecution'}})
            send({'id': ident, 'result': {'thread': {'id': 'invalid' if mode == 'invalid_uuid' else '12345678-1234-4234-8234-123456789abc'}, 'approvalPolicy': 'never', 'sandbox': {'type': 'readOnly'}}})
    elif method == 'thread/inject_items': send({'id': ident, 'result': {}})
    elif method == 'turn/start':
        items = [{'type': 'sleep'}, {'type': 'commandExecution'}] if mode == 'wait_forbidden' else [{'type': 'fileChange'}] if mode == 'forbidden_response' else ([{'type': 'sleep'}] if mode == 'wait_response' else [])
        send({'id': ident, 'result': {'turn': {'id': 'turn1', 'items': items}}})
        event('item/agentMessage/delta', {'delta': 'hello'})
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
        if mode in ('abort', 'chatty', 'stubborn'): continue
        if mode == 'forbidden_after': event('item/started', {'item': {'type': 'webSearch'}}); continue
        if mode in ('forbidden_mcp', 'forbidden_unknown'):
            event('item/completed', {'item': {'type': 'mcpToolCall', 'tool': 'other'} if mode == 'forbidden_mcp' else {'type': 'futureTool'}})
            continue
        if mode == 'miderror':
            event('error', {'error': {'message': 'upstream error'}, 'willRetry': False})
        elif mode == 'tools':
            event('item/tool/call', {'callId': 'call1', 'tool': 'one', 'arguments': {'n': 1}})
            event('item/tool/call', {'callId': 'call2', 'tool': 'two', 'arguments': {'n': 2}})
        else:
            event('thread/tokenUsage/updated', {'tokenUsage': {'total': {'inputTokens': 100, 'cachedInputTokens': 40, 'outputTokens': 9}}})
            event('turn/completed', {'turn': {'id': 'turn1', 'status': 'completed'}})
    elif method == 'turn/interrupt':
        if mode == 'stubborn':
            while True:
                try: event('item/agentMessage/delta', {'delta': 'hello'})
                except BrokenPipeError: pass
                time.sleep(0.05)
        if mode == 'chatty':
            while True:
                event('item/agentMessage/delta', {'delta': 'hello'})
                time.sleep(0.05)
        send({'id': ident, 'result': {}})
        event('thread/tokenUsage/updated', {'tokenUsage': {'total': {'inputTokens': 100, 'cachedInputTokens': 40, 'outputTokens': 9}}})
        event('turn/completed', {'turn': {'id': 'turn1', 'status': 'interrupted'}})
    elif method == 'model/list': send({'id': ident, 'result': {'data': [{'id': 'chat', 'displayName': 'Chat'}, {'id': 'image', 'displayName': 'Image'}], 'nextCursor': None}})
    elif method == 'account/rateLimits/read': send({'id': ident, 'result': {'rateLimits': {'primary': {'usedPercent': 30}, 'ordinaryUsageAllowed': True}}})
