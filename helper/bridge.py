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

for stream in (sys.stdin, sys.stdout, sys.stderr):
    stream.reconfigure(encoding='utf-8')

from mapping import InvalidRequest, classify, prepare, usage_delta

# Last live-tested version: codex-cli 0.165.0.
MIN_TESTED_VERSION = (0, 165, 0)
# These item types were observed in the live contract test; MCP is restricted separately.
ALLOWED_ITEMS = frozenset(('userMessage', 'agentMessage', 'reasoning', 'dynamicToolCall', 'contextCompaction'))
TOOL_BATCH_SECONDS = 0.2
DEFAULT_CONTEXT_WINDOW = 128_000
WAIT_ITEMS = frozenset(('collabAgentToolCall', 'sleep'))
ALLOWED_MCP_TOOLS = frozenset(('list_mcp_resources', 'list_mcp_resource_templates'))
TOOL_INSTRUCTIONS = ('Use only the provided function tools. Do not use built-in sleep, wait, collaboration, or subagent tools. '
                     'To wait for background work, end this turn; the client will notify you when it completes.')
NOT_CHAT = re.compile(r'claude|anthropic|image|auto-review|embed|tts|whisper|moderation', re.I)
FEATURES = ('apps', 'multi_agent', 'unified_exec', 'shell_tool', 'view_image', 'image_generation', 'browser_use', 'in_app_browser', 'goals',
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
    if kind == 'contextCompaction': note('Codex login: context compaction observed')
    if kind in WAIT_ITEMS: return True
    if kind not in ALLOWED_ITEMS and not (kind == 'mcpToolCall' and value.get('tool') in ALLOWED_MCP_TOOLS):
        safe_kind = kind if re.fullmatch(r'[A-Za-z0-9_]{1,64}', kind) else 'unknown'
        note('Codex login: unsupported codex behavior: ' + safe_kind)
        raise BridgeError('Codex login: unsupported codex behavior: ' + safe_kind, 502, code='unsupported_item')


def check_turn(value):
    if not isinstance(value, dict): return
    if 'items' in value:
        if not isinstance(value['items'], list): raise incompatible('turn.items')
        waiting = False
        for item in value['items']:
            if check_item(item): waiting = True
        return waiting


def catalog_windows(home):
    try:
        with open(os.path.join(home, 'models_cache.json'), encoding='utf-8') as f: models = json.load(f)['models']
        result = {}
        for model in models:
            if not isinstance(model, dict): continue
            slug, window, percent = model.get('slug'), model.get('context_window'), model.get('effective_context_window_percent')
            if isinstance(slug, str) and type(window) is int and window > 0 and type(percent) in (int, float) and 0 < percent <= 100:
                effective = int(window * percent / 100)
                if effective > 0: result[slug] = effective
        return result
    except (OSError, ValueError, TypeError, KeyError, AttributeError, OverflowError): return {}


class App:
    def __init__(self, args, cwd):
        argv = [args.codex_bin, 'app-server', '-c', 'web_search="disabled"', '-c', 'include_permissions_instructions=false', '-c', 'include_environment_context=false']
        window = getattr(args, 'compact_window', None)
        if window is not None:
            argv.extend(['-c', 'model_auto_compact_token_limit=' + str((window * 11 + 9) // 10)])
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
        self.wait_interrupted = False
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

    def next(self, until=None):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0: raise BridgeError('Codex login: app-server maximum timeout', 504, code='timeout')
        batch_remaining = until - time.monotonic() if until is not None else None
        if batch_remaining is not None and batch_remaining <= 0: raise queue.Empty()
        timeout = min(self.idle_seconds, remaining, batch_remaining if batch_remaining is not None else remaining)
        try: item = self.queue.get(timeout=timeout)
        except queue.Empty:
            if time.monotonic() >= self.deadline: raise BridgeError('Codex login: app-server maximum timeout', 504, code='timeout')
            if until is not None and time.monotonic() >= until: raise
            raise BridgeError('Codex login: app-server timeout', 504, code='timeout')
        if item is None:
            if not self.initialized: raise incompatible('app-server flags or startup')
            raise BridgeError('Codex login: app-server exited unexpectedly', 502)
        if isinstance(item, Exception): raise item
        if not isinstance(item, dict): raise incompatible('response')
        if self.wait_interrupted: return item
        waiting = False
        if item.get('method') in ('item/started', 'item/completed'):
            params = item.get('params')
            waiting = bool(check_item(params.get('item') if isinstance(params, dict) else None))
        for container in (item.get('params'), item.get('result')):
            if isinstance(container, dict):
                if check_turn(container.get('turn')): waiting = True
                thread = container.get('thread')
                if isinstance(thread, dict) and isinstance(thread.get('turns'), list):
                    for turn in thread['turns']:
                        if check_turn(turn): waiting = True
        if waiting: item['_model_mod_wait'] = True
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
    result = app.request('thread/start', {'model': p['model'], 'cwd': cwd, 'sandbox': 'read-only', 'approvalPolicy': 'never', 'ephemeral': True, 'baseInstructions': p['system'], 'developerInstructions': TOOL_INSTRUCTIONS, 'dynamicTools': p['tools']})
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
    batch_deadline, call_ids = None, set()
    if check_turn(result.get('turn')):
        app.wait_interrupted = True
        app.interrupt()
    while True:
        if batch_deadline is not None and time.monotonic() >= batch_deadline:
            app.interrupt()
            batch_deadline = None
        try:
            obj = app.pending.pop(0) if app.pending else app.next(batch_deadline)
        except queue.Empty:
            app.interrupt()
            batch_deadline = None
            continue
        method, params = obj.get('method'), obj.get('params', {})
        if obj.get('_model_mod_wait') and not app.wait_interrupted:
            app.wait_interrupted = True
            app.interrupt()
        if app.wait_interrupted and method not in ('turn/completed', 'thread/tokenUsage/updated') and not (method == 'item/tool/call' and params.get('tool') in p['reverse']):
            continue
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
            if not isinstance(block['id'], str) or not block['id'] or block['id'] in call_ids or not isinstance(block['input'], dict): raise BridgeError('Codex login: invalid dynamic tool call')
            call_ids.add(block['id'])
            calls.append(block); content.append(block)
            if batch_deadline is None and not app.interrupted: batch_deadline = time.monotonic() + TOOL_BATCH_SECONDS
            if p['stream']:
                idx = len(content)-1
                emit('content_block_start', {'type': 'content_block_start', 'index': idx, 'content_block': {'type': 'tool_use', 'id': block['id'], 'name': name, 'input': {}}})
                emit('content_block_delta', {'type': 'content_block_delta', 'index': idx, 'delta': {'type': 'input_json_delta', 'partial_json': json.dumps(block['input'], ensure_ascii=False)}})
                emit('content_block_stop', {'type': 'content_block_stop', 'index': idx})
        elif method == 'thread/tokenUsage/updated':
            token_usage = params.get('tokenUsage', {})
            latest = token_usage.get('total', {})
            reported = token_usage.get('modelContextWindow')
            if isinstance(reported, int) and reported != args.context_window:
                note('Codex login: reported model context window differs from client window')
        elif method == 'turn/completed' and params.get('turn', {}).get('id') == app.turn_id:
            status = params['turn'].get('status')
            if status != 'completed' and not ((calls or app.wait_interrupted) and status == 'interrupted'):
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


def account_home(root, account, create=False):
    if not os.path.isabs(root) or '..' in root.replace('\\', '/').split('/') or not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,31}', account):
        raise BridgeError('Codex login: invalid account directory', code='invalid_home')
    if create: os.makedirs(root, mode=0o700, exist_ok=True)
    base = os.path.realpath(root)
    target = os.path.join(base, account)
    if os.path.islink(target) or os.path.commonpath((base, os.path.realpath(target))) != base or os.path.realpath(target) == base:
        raise BridgeError('Codex login: invalid account directory', code='invalid_home')
    created = False
    if create:
        try:
            os.mkdir(target, 0o700)
            created = True
        except FileExistsError:
            if os.path.islink(target) or not os.path.isdir(target): raise BridgeError('Codex login: invalid account directory', code='invalid_home')
    return target, created


DEVICE_CODE_LIFETIME = 15 * 60
DEVICE_LOGIN_TIMEOUT = 16 * 60  # Allow the CLI time to finish after the code expires.


def device_login(args):
    proc = subprocess.Popen([args.codex_bin, 'login', '--device-auth'], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            env=env(args.codex_home), start_new_session=(os.name == 'posix'))
    lines = queue.Queue()
    def read_output():
        try:
            for line in proc.stdout: lines.put(line.decode('utf-8', 'replace'))
        finally: lines.put(None)
    threading.Thread(target=read_output, daemon=True).start()
    started = time.monotonic()
    deadline = started + DEVICE_LOGIN_TIMEOUT
    url = code = None
    expecting_url = expecting_code = False
    try:
        while time.monotonic() < deadline:
            try: line = lines.get(timeout=min(1, max(0.01, deadline - time.monotonic())))
            except queue.Empty:
                if proc.poll() is not None: break
                continue
            if line is None: break
            line = re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', line).strip()
            if expecting_url and re.fullmatch(r'https://[A-Za-z0-9.-]+(?::[0-9]+)?/[A-Za-z0-9/_-]+', line): url, expecting_url = line, False
            elif expecting_code and re.fullmatch(r'[A-Z0-9]{4}-[A-Z0-9]{4,8}', line): code, expecting_code = line, False
            if 'Open this link' in line: expecting_url = True
            if 'Enter this one-time code' in line: expecting_code = True
            if url and code:
                print(json.dumps({'url': url, 'code': code}), flush=True)
                break
        if not url or not code:
            if time.monotonic() >= deadline:
                raise BridgeError('Codex login: device code expired; run /model-mod:setup again', code='device_expired')
            return False
        expired_output = False
        while time.monotonic() < deadline:
            try: line = lines.get(timeout=min(1, max(0.01, deadline - time.monotonic())))
            except queue.Empty:
                if proc.poll() is not None: break
                continue
            if line is None: break
            if re.search(r'\bexpir(?:ed|ation)\b', line, re.IGNORECASE): expired_output = True
        try: result = proc.wait(timeout=max(0.01, deadline - time.monotonic()))
        except subprocess.TimeoutExpired: result = None
        if result == 0: return True
        if result is None or expired_output or time.monotonic() - started >= DEVICE_CODE_LIFETIME:
            raise BridgeError('Codex login: device code expired; run /model-mod:setup again', code='device_expired')
        return False
    finally:
        if os.name == 'posix':
            try: os.killpg(proc.pid, signal.SIGTERM)
            except ProcessLookupError: pass
        elif proc.poll() is None:
            subprocess.run(['taskkill', '/PID', str(proc.pid), '/T', '/F'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        try: proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            if os.name == 'posix':
                try: os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError: pass
            else: proc.kill()
            proc.wait()
        if os.name == 'posix':
            try: os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError: pass
        proc.stdout.close()


def main():
    if sys.version_info < (3, 9):
        print('model-mod-note:Codex login: Python 3.9 or newer required', file=sys.stderr)
        return 78
    parser = argparse.ArgumentParser(prog='bridge')
    subs = parser.add_subparsers(dest='command', required=True)
    for name in ('messages', 'rate-limits', 'check', 'models', 'windows', 'prepare-home', 'validate-home', 'can-remove-home', 'device-login', 'logout', 'remove-home', 'cleanup-home'):
        sub = subs.add_parser(name)
        sub.add_argument('--codex-home', required=True)
        sub.add_argument('--codex-bin', default='codex')
        if name in ('prepare-home', 'validate-home', 'can-remove-home', 'remove-home', 'cleanup-home', 'device-login', 'logout'):
            sub.add_argument('--accounts-dir', required=True)
            sub.add_argument('--account', required=True)
        if name == 'messages':
            sub.add_argument('--model-map', action='append', default=[])
            sub.add_argument('--idle-seconds', type=float, default=300)
            sub.add_argument('--max-seconds', type=float, default=900)
            sub.add_argument('--context-window', type=int)
            sub.add_argument('--catalog-window', type=int)
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
        if args.command in ('prepare-home', 'validate-home', 'can-remove-home', 'remove-home', 'cleanup-home'):
            if ('..' in args.codex_home.replace('\\', '/').split('/') or
                    os.path.normcase(os.path.abspath(args.codex_home)) != os.path.normcase(os.path.abspath(os.path.join(args.accounts_dir, args.account)))):
                raise BridgeError('Codex login: invalid account directory', code='invalid_home')
            target, created = account_home(args.accounts_dir, args.account, args.command == 'prepare-home')
            if os.path.normcase(os.path.realpath(args.codex_home)) != os.path.normcase(target):
                raise BridgeError('Codex login: invalid account directory', code='invalid_home')
            if args.command in ('validate-home', 'can-remove-home', 'remove-home') and not os.path.isdir(target):
                raise BridgeError('Codex login: invalid account directory', code='invalid_home')
            if args.command in ('can-remove-home', 'remove-home') and os.path.lexists(os.path.join(target, 'auth.json')):
                raise BridgeError('Codex login: account credentials remain; directory retained', code='credentials_remain')
            if args.command == 'remove-home':
                if os.name == 'posix':
                    fd = os.open(os.path.dirname(target), os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
                    try:
                        if sys.version_info >= (3, 11): shutil.rmtree(args.account, dir_fd=fd)
                        else:
                            os.fchdir(fd)
                            shutil.rmtree(args.account)
                    finally: os.close(fd)
                else: shutil.rmtree(target)
            elif args.command == 'cleanup-home':
                # Never remove files or nonempty directories on cancellation.
                for name in ('log', 'tmp'):
                    path = os.path.join(target, name)
                    if os.path.isdir(path) and not os.path.islink(path):
                        try: os.rmdir(path)
                        except OSError: pass
                try: os.rmdir(target)
                except OSError: pass
            print(json.dumps({'created': created}), flush=True)
            return 0
        if args.command in ('device-login', 'logout'):
            target, _ = account_home(args.accounts_dir, args.account)
            if ('..' in args.codex_home.replace('\\', '/').split('/') or
                    os.path.normcase(os.path.abspath(args.codex_home)) != os.path.normcase(os.path.abspath(os.path.join(args.accounts_dir, args.account))) or
                    os.path.normcase(os.path.realpath(args.codex_home)) != os.path.normcase(target)):
                raise BridgeError('Codex login: invalid account directory', code='invalid_home')
        if not os.path.isabs(args.codex_home) or not os.path.isdir(args.codex_home):
            raise BridgeError('Codex login: account home must be an existing absolute directory', code='invalid_home')
        if args.command == 'windows':
            print(json.dumps({'windows': catalog_windows(args.codex_home)}), flush=True)
            return 0
        if args.command == 'messages':
            if args.idle_seconds <= 0 or args.max_seconds <= 0: raise InvalidRequest('invalid timeout')
            if any(value is not None and not 1 <= value <= 4_000_000 for value in (args.context_window, args.catalog_window)): raise InvalidRequest('invalid context window')
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
            catalog_window = args.catalog_window if args.catalog_window is not None else catalog_windows(args.codex_home).get(prepared['model'], DEFAULT_CONTEXT_WINDOW)
            if args.context_window is None: args.context_window = catalog_window
            args.compact_window = max(args.context_window, catalog_window)
        clean_old_directories()
        version, version_status = verify_version(args)
        home_warnings = warnings(args.codex_home)
        if args.command == 'device-login':
            if not device_login(args): raise BridgeError('Codex login: device login failed', code='codex_not_logged_in')
        elif args.command == 'logout':
            try: r = subprocess.run([args.codex_bin, 'logout'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15, env=env(args.codex_home))
            except (OSError, subprocess.TimeoutExpired): raise BridgeError('Codex login: logout failed', code='codex_unavailable')
            if r.returncode: raise BridgeError('Codex login: logout failed', code='codex_unavailable')
            print(json.dumps({'ok': True}), flush=True)
        elif args.command == 'check':
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
        exit_code = {'protocol': 65, 'codex_unavailable': 66, 'codex_too_old': 67, 'codex_not_logged_in': 68, 'invalid_home': 69, 'credentials_remain': 70}.get(e.code, 1)
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
