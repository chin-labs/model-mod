#!/usr/bin/env python3
"""Isolated Codex app-server Messages bridge.

Exit codes: 0 success, 1 request failure, 65 incompatible protocol,
66 codex unavailable, 67 codex too old, 68 not logged in, 69 invalid home,
78 Python too old. Before updating MIN_TESTED_VERSION, run the manual live
contract test against that version and update the tested version record.
"""
import argparse
import json
import os
import queue
import re
import select
import shutil
import time
import signal
import subprocess
import sys
import tempfile
import threading
import uuid

from mapping import InvalidRequest, classify, prepare, usage_delta

# Last live-tested version: codex-cli 0.165.0.
MIN_TESTED_VERSION = (0, 165, 0)
# These item types were observed in the live contract test; MCP is restricted separately.
ALLOWED_ITEMS = frozenset(('userMessage', 'agentMessage', 'reasoning', 'dynamicToolCall'))
ALLOWED_MCP_TOOLS = frozenset(('list_mcp_resources', 'list_mcp_resource_templates'))
NOT_CHAT = re.compile(r'claude|anthropic|image|auto-review|embed|tts|whisper|moderation', re.I)
FEATURES = ('apps', 'multi_agent', 'shell_tool', 'view_image', 'image_generation', 'browser_use', 'in_app_browser', 'goals',
            'sleep_tool', 'computer_use', 'tool_suggest', 'skill_search', 'plugins', 'remote_plugin', 'hooks', 'guardian_approval',
            'incremental_tools', 'browser_annotation_api', 'browser_use_external', 'browser_use_full_cdp_access', 'plugin_sharing', 'skill_mcp_dependency_install')


class BridgeError(Exception):
    def __init__(self, message, status=500, kind='api_error', retry_after=None, code='bridge_error'):
        super().__init__(message)
        self.status, self.kind, self.retry_after, self.code = status, kind, retry_after, code


class Cancelled(Exception):
    pass


def cancel(signum, frame):
    raise Cancelled()


def note(text):
    print('model-mod-note:' + text, file=sys.stderr, flush=True)


def env(home):
    keys = ('PATH', 'HOME', 'TMPDIR', 'LANG', 'TERM')
    if os.name == 'nt': keys += ('USERPROFILE', 'SYSTEMROOT', 'TEMP', 'TMP')
    result = {key: value for key, value in os.environ.items() if (key in keys or key.startswith('LC_')) and not key.endswith(('_KEY', '_TOKEN'))}
    result['CODEX_HOME'] = home
    return result


def incompatible(field):
    return BridgeError('Codex login: incompatible codex app-server protocol (' + field + ')', 502, code='protocol')


def verify_version(args):
    try:
        result = subprocess.run([args.codex_bin, '--version'], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=10, env=env(args.codex_home))
    except (OSError, subprocess.TimeoutExpired):
        raise BridgeError('Codex login: codex unavailable', code='codex_unavailable')
    match = re.fullmatch(r'codex-cli (0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-([0-9A-Za-z.-]+))?(?:\+([0-9A-Za-z.-]+))?', result.stdout.strip())
    if result.returncode or not match:
        raise BridgeError('Codex login: codex unavailable', code='codex_unavailable')
    version = tuple(map(int, match.group(1, 2, 3)))
    text = result.stdout.strip().split(' ', 1)[1]
    if version < MIN_TESTED_VERSION or (version == MIN_TESTED_VERSION and match.group(4)):
        error = BridgeError('Codex login: codex version is too old', code='codex_too_old')
        error.version = text
        raise error
    return text, 'tested' if version == MIN_TESTED_VERSION and not match.group(4) and not match.group(5) else 'untested'


def retry_seconds(error):
    if not isinstance(error, dict): return None
    for key in ('retryAfter', 'retry_after', 'retryAfterSeconds'):
        value = error.get(key)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0: return value
    return None


def warnings(home):
    found = []
    for name in ('AGENTS.md', 'AGENTS.override.md', 'config.toml', '.mcp.json', 'mcp.json'):
        if os.path.exists(os.path.join(home, name)):
            message = 'Codex login: inspect account home file ' + name + ' for instructions or MCP settings'
            found.append(message)
            note(message)
    return found


def check_item(value):
    if not isinstance(value, dict) or not isinstance(value.get('type'), str): raise incompatible('item.type')
    kind = value['type']
    if kind not in ALLOWED_ITEMS and not (kind == 'mcpToolCall' and value.get('tool') in ALLOWED_MCP_TOOLS):
        safe_kind = kind if re.fullmatch(r'[A-Za-z0-9_]{1,64}', kind) else 'unknown'
        note('Codex login: unsupported codex behavior: ' + safe_kind)
        raise BridgeError('Codex login: unsupported codex behavior: ' + safe_kind, 502, code='unsupported_item')


def check_turn(value):
    if not isinstance(value, dict): return
    if 'items' in value:
        if not isinstance(value['items'], list): raise incompatible('turn.items')
        for item in value['items']: check_item(item)


class App:
    def __init__(self, args, cwd):
        argv = [args.codex_bin, 'app-server', '-c', 'web_search="disabled"', '-c', 'include_permissions_instructions=false', '-c', 'include_environment_context=false']
        for feature in FEATURES: argv.extend(['--disable', feature])
        self.cwd = cwd
        self.deadline = time.monotonic() + getattr(args, 'max_seconds', 900)
        self.idle_seconds = getattr(args, 'idle_seconds', 300)
        try:
            self.proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1, cwd=cwd, env=env(args.codex_home), start_new_session=(os.name == 'posix'))
        except OSError:
            raise BridgeError('Codex login: codex unavailable', code='codex_unavailable')
        self.stderr_tail = b''
        def stderr_reader():
            while True:
                data = os.read(self.proc.stderr.fileno(), 4096)
                if not data: break
                self.stderr_tail = (self.stderr_tail + data)[-4096:]
        self.stderr_thread = threading.Thread(target=stderr_reader, daemon=True)
        self.stderr_thread.start()
        self.queue = queue.Queue()
        self.pending = []
        self.counter = 0
        self.thread_id = None
        self.turn_id = None
        self.interrupted = False
        self.interrupt_id = None
        self.initialized = False
        def reader():
            try:
                for line in self.proc.stdout:
                    try: self.queue.put(json.loads(line))
                    except ValueError: self.queue.put(BridgeError('Codex login: invalid app-server JSON'))
            finally: self.queue.put(None)
        threading.Thread(target=reader, daemon=True).start()

    def send(self, obj):
        try:
            self.proc.stdin.write(json.dumps(obj, ensure_ascii=False) + '\n')
            self.proc.stdin.flush()
        except (BrokenPipeError, OSError):
            raise incompatible('app-server flags or startup')

    def next(self):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0: raise BridgeError('Codex login: app-server maximum timeout', 504, code='timeout')
        try: item = self.queue.get(timeout=min(self.idle_seconds, remaining))
        except queue.Empty: raise BridgeError('Codex login: app-server timeout', 504, code='timeout')
        if item is None:
            if not self.initialized: raise incompatible('app-server flags or startup')
            raise BridgeError('Codex login: app-server exited unexpectedly', 502)
        if isinstance(item, Exception): raise item
        if not isinstance(item, dict): raise incompatible('response')
        if item.get('method') in ('item/started', 'item/completed'):
            params = item.get('params')
            check_item(params.get('item') if isinstance(params, dict) else None)
        for container in (item.get('params'), item.get('result')):
            if isinstance(container, dict):
                check_turn(container.get('turn'))
                thread = container.get('thread')
                if isinstance(thread, dict) and isinstance(thread.get('turns'), list):
                    for turn in thread['turns']: check_turn(turn)
        return item

    def request(self, method, params):
        self.counter += 1
        ident = self.counter
        self.send({'id': ident, 'method': method, 'params': params})
        while True:
            obj = self.next()
            if obj.get('id') == ident and 'method' not in obj:
                if 'error' in obj:
                    status, kind = classify(obj['error'])
                    if method == 'initialize': raise incompatible('experimentalApi')
                    if isinstance(obj['error'], dict) and obj['error'].get('code') in (-32600, -32602):
                        raise BridgeError('Codex login: request rejected by Codex', 400, 'invalid_request_error', code='codex_rejected_request')
                    raise BridgeError('Codex login: app-server request failed', status, kind, retry_seconds(obj['error']))
                return obj.get('result', {})
            self.pending.append(obj)

    def interrupt(self):
        if self.thread_id and self.turn_id and not self.interrupted:
            self.interrupted = True
            self.counter += 1
            self.interrupt_id = self.counter
            self.send({'id': self.counter, 'method': 'turn/interrupt', 'params': {'threadId': self.thread_id, 'turnId': self.turn_id}})

    def close(self):
        try:
            try:
                signal.signal(signal.SIGTERM, signal.SIG_IGN)
                signal.signal(signal.SIGINT, signal.SIG_IGN)
                if hasattr(signal, 'SIGHUP'): signal.signal(signal.SIGHUP, signal.SIG_IGN)
                if self.proc.poll() is None:
                    try:
                        self.interrupt()
                        if self.interrupt_id is not None:
                            deadline = time.monotonic() + 1
                            while True:
                                remaining = deadline - time.monotonic()
                                if remaining <= 0: break
                                response = self.queue.get(timeout=remaining)
                                if response is None or response.get('id') == self.interrupt_id: break
                    except (OSError, ValueError, queue.Empty, AttributeError, BridgeError): pass
            finally:
                try:
                    if os.name == 'posix':
                        try: os.killpg(self.proc.pid, signal.SIGTERM)
                        except ProcessLookupError: pass
                    elif self.proc.poll() is None: self.proc.terminate()
                finally:
                    try: self.proc.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        try:
                            if os.name == 'posix':
                                try: os.killpg(self.proc.pid, signal.SIGKILL)
                                except ProcessLookupError: pass
                            else: self.proc.kill()
                        finally:
                            try: self.proc.wait(timeout=3)
                            except subprocess.TimeoutExpired: pass
            self.stderr_thread.join(timeout=1)
        finally:
            for stream in (self.proc.stdin, self.proc.stdout, self.proc.stderr):
                if stream:
                    try: stream.close()
                    except OSError: pass

    def initialize(self):
        result = self.request('initialize', {'clientInfo': {'name': 'model-mod-bridge', 'version': '0.1.0'}, 'capabilities': {'experimentalApi': True}})
        if not isinstance(result, dict) or not all(isinstance(result.get(key), str) and result[key] for key in ('userAgent', 'codexHome', 'platformFamily', 'platformOs')): raise incompatible('initialize')
        self.send({'method': 'initialized', 'params': {}})
        config = self.request('config/read', {'includeLayers': False, 'cwd': self.cwd})
        config = config.get('config') if isinstance(config, dict) else None
        if not isinstance(config, dict) or config.get('web_search') != 'disabled': raise incompatible('web_search')
        features = config.get('features')
        if not isinstance(features, dict): raise incompatible('features')
        for feature in FEATURES:
            if features.get(feature) is not False: raise incompatible(feature)
        self.initialized = True


def emit(event, data):
    sys.stdout.write('event: ' + event + '\ndata: ' + json.dumps(data, ensure_ascii=False) + '\n\n')
    sys.stdout.flush()


def messages(args, app, prepared, cwd):
    p = prepared
    for field in p['ignored']: note('Codex login: ignored field ' + field)
    if p['dropped']: note('Codex login: discarded thinking blocks: ' + str(p['dropped']))
    result = app.request('thread/start', {'model': p['model'], 'cwd': cwd, 'sandbox': 'read-only', 'approvalPolicy': 'never', 'ephemeral': True, 'baseInstructions': p['system'], 'dynamicTools': p['tools']})
    try:
        thread_id = result['thread']['id']
        if not isinstance(thread_id, str) or str(uuid.UUID(thread_id)) != thread_id.lower(): raise ValueError()
    except (KeyError, TypeError, ValueError, AttributeError):
        raise incompatible('thread.id')
    if result.get('approvalPolicy') != 'never' or not isinstance(result.get('sandbox'), dict) or result['sandbox'].get('type') != 'readOnly': raise incompatible('sandbox or approvalPolicy')
    app.thread_id = thread_id
    if p['history']: app.request('thread/inject_items', {'threadId': app.thread_id, 'items': p['history']})
    result = app.request('turn/start', {'threadId': app.thread_id, 'model': p['model'], 'effort': p['effort'], 'input': p['input']})
    try:
        app.turn_id = result['turn']['id']
        if not isinstance(app.turn_id, str) or not app.turn_id: raise ValueError()
    except (KeyError, TypeError, ValueError): raise incompatible('turn.id')
    message = {'id': 'msg_' + uuid.uuid4().hex, 'type': 'message', 'role': 'assistant', 'model': p['client_model'], 'content': [], 'stop_reason': None, 'stop_sequence': None, 'usage': {'input_tokens': 0, 'output_tokens': 0}}
    if p['stream']: emit('message_start', {'type': 'message_start', 'message': message})
    content, opened, calls, latest = [], False, [], {}
    while True:
        obj = app.pending.pop(0) if app.pending else app.next()
        method, params = obj.get('method'), obj.get('params', {})
        if method == 'item/agentMessage/delta':
            if calls: continue
            if not opened:
                content.append({'type': 'text', 'text': ''}); opened = True
                if p['stream']: emit('content_block_start', {'type': 'content_block_start', 'index': len(content)-1, 'content_block': {'type': 'text', 'text': ''}})
            text = params.get('delta', '')
            content[-1]['text'] += text
            if p['stream']: emit('content_block_delta', {'type': 'content_block_delta', 'index': len(content)-1, 'delta': {'type': 'text_delta', 'text': text}})
        elif method == 'item/tool/call':
            name = p['reverse'].get(params.get('tool'))
            if name is None: raise BridgeError('Codex login: unknown dynamic tool')
            if opened:
                if p['stream']: emit('content_block_stop', {'type': 'content_block_stop', 'index': len(content)-1})
                opened = False
            block = {'type': 'tool_use', 'id': params.get('callId'), 'name': name, 'input': params.get('arguments')}
            if not isinstance(block['id'], str) or not isinstance(block['input'], dict): raise BridgeError('Codex login: invalid dynamic tool call')
            calls.append(block); content.append(block)
            app.interrupt()
            if p['stream']:
                idx = len(content)-1
                emit('content_block_start', {'type': 'content_block_start', 'index': idx, 'content_block': {'type': 'tool_use', 'id': block['id'], 'name': name, 'input': {}}})
                emit('content_block_delta', {'type': 'content_block_delta', 'index': idx, 'delta': {'type': 'input_json_delta', 'partial_json': json.dumps(block['input'], ensure_ascii=False)}})
                emit('content_block_stop', {'type': 'content_block_stop', 'index': idx})
        elif method == 'thread/tokenUsage/updated':
            latest = params.get('tokenUsage', {}).get('total', {})
        elif method == 'turn/completed' and params.get('turn', {}).get('id') == app.turn_id:
            status = params['turn'].get('status')
            if status != 'completed' and not (calls and status == 'interrupted'):
                code, kind = classify(params['turn'].get('error'))
                raise BridgeError('Codex login: app-server turn failed', code, kind)
            app.turn_id = None
            app.interrupt_id = None
            break
        elif method == 'error':
            error = params.get('error', params)
            if not params.get('willRetry', False):
                status, kind = classify(error)
                raise BridgeError('Codex login: app-server turn error', status, kind, retry_seconds(error))
        elif method and 'id' in obj:
            app.send({'id': obj['id'], 'error': {'code': -32601, 'message': 'not permitted'}})
    if opened and p['stream']: emit('content_block_stop', {'type': 'content_block_stop', 'index': len(content)-1})
    usage = usage_delta({}, latest)
    if not latest: note('Codex login: usage unavailable; zero is not an accurate count')
    reason = 'tool_use' if calls else 'end_turn'
    if p['stream']:
        emit('message_delta', {'type': 'message_delta', 'delta': {'stop_reason': reason, 'stop_sequence': None}, 'usage': usage})
        emit('message_stop', {'type': 'message_stop'})
    else:
        message.update(content=content, stop_reason=reason, usage=usage)
        print(json.dumps(message, ensure_ascii=False), flush=True)


def clean_old_directories():
    root = tempfile.gettempdir()
    now = time.time()
    for entry in os.scandir(root):
        if not entry.name.startswith('model-mod-bridge-'): continue
        try:
            if not entry.is_dir(follow_symlinks=False) or now - entry.stat(follow_symlinks=False).st_mtime <= 3600: continue
            if hasattr(os, 'getuid') and entry.stat(follow_symlinks=False).st_uid != os.getuid(): continue
            # Leave live directories alone; SIGKILL leftovers are swept after one hour.
            pid_file = os.path.join(entry.path, '.pid')
            try:
                with open(pid_file, encoding='ascii') as f: pid = int(f.read())
                os.kill(pid, 0)
                continue
            except (ProcessLookupError, FileNotFoundError): pass
            except (OSError, ValueError): continue
            shutil.rmtree(entry.path)
        except OSError: pass


def main():
    if sys.version_info < (3, 9):
        print('model-mod-note:Codex login: Python 3.9 or newer required', file=sys.stderr)
        return 78
    parser = argparse.ArgumentParser(prog='bridge')
    subs = parser.add_subparsers(dest='command', required=True)
    for name in ('messages', 'rate-limits', 'check', 'models'):
        sub = subs.add_parser(name)
        sub.add_argument('--codex-home', required=True)
        sub.add_argument('--codex-bin', default='codex')
        if name == 'messages':
            sub.add_argument('--model-map', action='append', default=[])
            sub.add_argument('--idle-seconds', type=float, default=300)
            sub.add_argument('--max-seconds', type=float, default=900)
    args = parser.parse_args()
    signal.signal(signal.SIGTERM, cancel)
    signal.signal(signal.SIGINT, cancel)
    if hasattr(signal, 'SIGHUP'): signal.signal(signal.SIGHUP, cancel)
    if hasattr(signal, 'SIGPIPE'): signal.signal(signal.SIGPIPE, signal.SIG_IGN)
    app, started, status, exit_code = None, False, 500, 1
    watcher_stop = threading.Event()
    if args.command == 'messages' and hasattr(select, 'poll'):
        def watch_stdout():
            poller = select.poll()
            try:
                poller.register(sys.stdout.fileno(), select.POLLERR | select.POLLHUP)
                while not watcher_stop.is_set():
                    if poller.poll(200):
                        if not watcher_stop.is_set(): os.kill(os.getpid(), signal.SIGTERM)
                        return
            except (OSError, ValueError): pass
        threading.Thread(target=watch_stdout, daemon=True).start()
    try:
        prepared = None
        if not os.path.isabs(args.codex_home) or not os.path.isdir(args.codex_home):
            raise BridgeError('Codex login: account home must be an existing absolute directory', code='invalid_home')
        if args.command == 'messages':
            if args.idle_seconds <= 0 or args.max_seconds <= 0: raise InvalidRequest('invalid timeout')
            model_map = {}
            for entry in args.model_map:
                name, sep, model = entry.partition('=')
                if not sep or not name or not model or name in model_map: raise InvalidRequest('invalid model map')
                model_map[name] = model
            try: body = json.load(sys.stdin)
            except (ValueError, UnicodeError): raise InvalidRequest('invalid JSON')
            client_model = body.get('model') if isinstance(body, dict) else None
            match = re.fullmatch(r'(.+)\((low|medium|high|xhigh|max)\)', client_model or '')
            effort = match.group(2) if match else 'low'
            if match:
                base = match.group(1)
                if base not in model_map and client_model in model_map: model_map[base] = model_map[client_model]
                body = dict(body, model=base)
            prepared = prepare(body, model_map)
            prepared['client_model'] = client_model
            prepared['effort'] = effort
        clean_old_directories()
        version, version_status = verify_version(args)
        home_warnings = warnings(args.codex_home)
        if args.command == 'check':
            try: r = subprocess.run([args.codex_bin, 'login', 'status'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=True, timeout=15, env=env(args.codex_home))
            except (OSError, subprocess.TimeoutExpired): raise BridgeError('Codex login: unable to check login status', code='codex_unavailable')
            if r.returncode: raise BridgeError('Codex login: not logged in', 401, 'authentication_error', code='codex_not_logged_in')
            print(json.dumps({'ok': True, 'codexVersion': version, 'versionStatus': version_status, 'loggedIn': True, 'pythonVersion': sys.version.split()[0], 'warnings': home_warnings + (['untested codex version'] if version_status == 'untested' else [])}))
        else:
            with tempfile.TemporaryDirectory(prefix='model-mod-bridge-') as cwd:
                with open(os.path.join(cwd, '.pid'), 'w', encoding='ascii') as f: f.write(str(os.getpid()))
                app = App(args, cwd)
                try:
                    app.initialize()
                    if args.command == 'models':
                        models, cursor, seen = [], None, set()
                        while True:
                            page = app.request('model/list', {'cursor': cursor, 'includeHidden': False})
                            if not isinstance(page, dict) or not isinstance(page.get('data'), list) or 'nextCursor' not in page: raise incompatible('model/list')
                            for model in page['data']:
                                if not isinstance(model, dict) or not isinstance(model.get('id'), str) or not isinstance(model.get('displayName'), str): raise incompatible('model/list data')
                                if not model.get('hidden') and not NOT_CHAT.search(model['id']): models.append({'id': model['id'], 'displayName': model['displayName']})
                            cursor = page['nextCursor']
                            if cursor is None: break
                            if not isinstance(cursor, str) or cursor in seen: raise incompatible('model/list cursor')
                            seen.add(cursor)
                        print(json.dumps({'models': models}), flush=True)
                    elif args.command == 'rate-limits':
                        limits = app.request('account/rateLimits/read', {})
                        snapshot = limits.get('rateLimits') or {}
                        result = {'ordinaryUsageAllowed': limits.get('ordinaryUsageAllowed')}
                        for key in ('primary', 'secondary'):
                            window = snapshot.get(key)
                            if isinstance(window, dict):
                                used = window.get('usedPercent')
                                result[key] = {'remainingPercent': 100 - used if isinstance(used, (int, float)) else None, 'resetsAt': window.get('resetsAt')}
                            else: result[key] = None
                        print(json.dumps(result, ensure_ascii=False), flush=True)
                    else:
                        # Track whether an SSE response has started.
                        if prepared['stream']:
                            original_emit = globals()['emit']
                            def tracked(event, data):
                                nonlocal started
                                started = True
                                original_emit(event, data)
                            globals()['emit'] = tracked
                        messages(args, app, prepared, cwd)
                finally:
                    watcher_stop.set()
                    app.close()
        status = 200
    except InvalidRequest as e:
        status = 400
        print(json.dumps({'type': 'error', 'error': {'type': 'invalid_request_error', 'message': 'Codex login: ' + str(e)}}, ensure_ascii=False), flush=True)
    except BridgeError as e:
        status = e.status
        exit_code = {'protocol': 65, 'codex_unavailable': 66, 'codex_too_old': 67, 'codex_not_logged_in': 68, 'invalid_home': 69}.get(e.code, 1)
        error = {'type': 'error', 'error': {'type': 'api_error' if started else e.kind, 'message': str(e), 'code': e.code}}
        if started: emit('error', error)
        elif args.command == 'check':
            print(json.dumps({'ok': False, 'codexVersion': getattr(e, 'version', locals().get('version')), 'versionStatus': 'too_old' if e.code == 'codex_too_old' else locals().get('version_status'), 'loggedIn': False, 'pythonVersion': sys.version.split()[0], 'warnings': locals().get('home_warnings', []), 'error': str(e)}), flush=True)
        else: print(json.dumps(error, ensure_ascii=False), flush=True)
        if e.retry_after is not None: print('model-mod-retry-after:' + str(e.retry_after), file=sys.stderr)
    except (BrokenPipeError, Cancelled):
        status = 499
        try: sys.stdout.close()
        except BrokenPipeError: pass
    except (OSError, KeyError, TypeError, ValueError, AttributeError, subprocess.TimeoutExpired) as e:
        status = 500
        if started: emit('error', {'type': 'error', 'error': {'type': 'api_error', 'message': 'Codex login: bridge failure'}})
        else: print(json.dumps({'type': 'error', 'error': {'type': 'api_error', 'message': 'Codex login: bridge failure'}}), flush=True)
        note('Codex login: bridge failure: ' + type(e).__name__)
    finally:
        watcher_stop.set()
        if app and status != 200 and app.stderr_tail:
            redacted = re.sub(r'[A-Za-z0-9_\-.]{32,}', '<redacted>', app.stderr_tail.decode('utf-8', 'replace'))
            remaining = 2048
            for line in redacted.splitlines():
                prefix = 'Codex login: app-server stderr: '
                overhead = len(('model-mod-note:' + prefix + '\n').encode('utf-8'))
                available = remaining - overhead
                if available <= 0: break
                text = line.encode('utf-8')[:available].decode('utf-8', 'ignore')
                if not text: continue
                note(prefix + text)
                remaining -= overhead + len(text.encode('utf-8'))
        print('model-mod-http:' + str(status), file=sys.stderr, flush=True)
    return 0 if status == 200 else exit_code


if __name__ == '__main__':
    sys.exit(main())
