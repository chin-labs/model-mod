"""Private, best-effort parent thread registry for the Messages bridge."""
import fcntl
import hashlib
import json
import math
import os
import re
import tempfile
import time
import uuid

from cancellation import Cancelled

TTL_SECONDS = 6 * 60 * 60
MAX_SESSION_PARENTS = 4
USAGE_FIELDS = ('inputTokens', 'cachedInputTokens', 'outputTokens', 'cacheWriteInputTokens')
FORK_OVERRIDE_INSTRUCTIONS = True
PARENT_INSTRUCTIONS = 'Respond briefly.'
SYNTHETIC_INPUT = 'Reply with ok.'


def digest(value):
    data = json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(',', ':')).encode()
    return hashlib.sha256(data).hexdigest()


def root_path():
    return os.path.join(os.environ.get('XDG_STATE_HOME') or os.path.join(os.path.expanduser('~'), '.' + 'local', 'state'), 'model-mod', 'threads', 'v1')


def write(path, record):
    fd, tmp = tempfile.mkstemp(prefix='.entry-', dir=os.path.dirname(path))
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(record, stream, separators=(',', ':'))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)


def record_at(path):
    try:
        with open(path, encoding='utf-8') as stream: data = json.load(stream)
        old_fields = {'key', 'thread', 'account', 'created', 'used', 'state'}
        if set(data) not in (old_fields, old_fields | {'session', 'tools', 'usage'}): return None
        if 'session' in data:
            if not all(isinstance(data[k], str) and re.fullmatch(r'[0-9a-f]{64}', data[k]) for k in ('session', 'tools')): return None
            if not isinstance(data['usage'], dict) or set(data['usage']) - set(USAGE_FIELDS): return None
            if not all(type(v) is int and v >= 0 for v in data['usage'].values()): return None
            if data['state'] == 'active' and not all(k in data['usage'] for k in USAGE_FIELDS[:3]): return None
        if not all(isinstance(data[k], str) for k in ('key', 'thread', 'account', 'state')): return None
        if not re.fullmatch(r'[0-9a-f]{64}', data['key']) or not re.fullmatch(r'[0-9a-f]{64}', data['account']): return None
        if str(uuid.UUID(data['thread'])) != data['thread'] or data['state'] not in ('active', 'pending-delete'): return None
        if not all(type(data[k]) in (int, float) and math.isfinite(data[k]) for k in ('created', 'used')): return None
        if not os.path.basename(path).endswith('-' + data['key'] + '.json'): return None
        return data
    except (OSError, ValueError, TypeError, RecursionError): return None


def delete(app, path, record):
    record['state'] = 'pending-delete'
    write(path, record)
    idle = getattr(app, 'idle_seconds', None)
    deadline = getattr(app, 'deadline', None)
    if idle is not None: app.idle_seconds = min(idle, 3)
    if deadline is not None: app.deadline = min(deadline, time.monotonic() + 3)
    try:
        app.request('thread/delete', {'threadId': record['thread']})
    except Cancelled:
        raise
    except Exception as error:
        if getattr(error, 'code', None) == 'thread_not_found':
            os.unlink(path)
            return True
        if getattr(error, 'code', None) == 'timeout': app.reuse_broken = True
        return False
    finally:
        if idle is not None: app.idle_seconds = idle
        if deadline is not None: app.deadline = deadline
    os.unlink(path)
    return True


def end_session(app, args, session):
    root = root_path()
    if not os.path.isdir(root): return
    fd = os.open(os.path.join(root, '.lock'), os.O_CREAT | os.O_RDWR, 0o600)
    try:
        try: fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError: return
        account = digest(os.path.realpath(args.codex_home))
        for name in os.listdir(root):
            if not re.fullmatch(r'[0-9a-f]{64}-[0-9a-f]{64}\.json', name): continue
            path = os.path.join(root, name)
            record = record_at(path)
            # The group includes the model, which is intentionally not retained.
            # Session cleanup is performed with the model supplied by the hook.
            if record and record['account'] == account and name.startswith(digest([session, account, args.cleanup_model]) + '-'):
                delete(app, path, record)
    finally:
        os.close(fd)


def fork(app, args, session, params):
    """Return a fork response or None; caller retains the one-shot fallback."""
    if not session or os.name != 'posix': return None
    root = root_path()
    os.makedirs(root, mode=0o700, exist_ok=True)
    os.chmod(root, 0o700)
    fd = os.open(os.path.join(root, '.lock'), os.O_CREAT | os.O_RDWR, 0o600)
    try:
        try: fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError: return None
        account = digest(os.path.realpath(args.codex_home))
        session_key = digest([session, account])
        group = digest([session, account, params['model']])
        tools_key = digest(params.get('dynamicTools', []))
        settings = dict(params)
        settings.pop('cwd', None)  # Per-request empty temporary working directory.
        if FORK_OVERRIDE_INSTRUCTIONS:
            settings.pop('baseInstructions', None)
        key = digest([session, account, settings, getattr(app, 'launch_args', []), app.web_search, args.no_keep_reasoning, args.service_tier, args.compact_window])
        path = os.path.join(root, group + '-' + key + '.json')
        now = time.time()
        candidates = []
        for name in os.listdir(root):
            if not re.fullmatch(r'[0-9a-f]{64}-[0-9a-f]{64}\.json', name): continue
            item_path = os.path.join(root, name)
            item = record_at(item_path)
            if not item or item['account'] != account: continue
            if (item['state'] == 'pending-delete' or now - item['used'] >= TTL_SECONDS or
                    (name.startswith(group + '-') and (not item.get('usage') or (item_path != path and item.get('tools') == tools_key)))):
                delete(app, item_path, item)
                if getattr(app, 'reuse_broken', False): return None
            elif item.get('session') == session_key and item['state'] == 'active':
                candidates.append((item['used'], item_path, item))
        record = record_at(path)
        if record is None and os.path.lexists(path): return None
        if record and (record['state'] != 'active' or record['account'] != account or record['key'] != key): return None
        if not record:
            while len(candidates) >= MAX_SESSION_PARENTS:
                _, old_path, old = min(candidates, key=lambda candidate: candidate[0])
                candidates = [candidate for candidate in candidates if candidate[1] != old_path]
                if not delete(app, old_path, old): return None
            parent = dict(params, ephemeral=False)
            if FORK_OVERRIDE_INSTRUCTIONS:
                parent['baseInstructions'] = PARENT_INSTRUCTIONS
            result = app.request('thread/start', parent)
            thread = result['thread']['id']
            if not isinstance(thread, str) or str(uuid.UUID(thread)) != thread.lower(): return None
            record = {'key': key, 'thread': thread, 'account': account, 'created': now, 'used': now, 'state': 'pending-delete', 'session': session_key, 'tools': tools_key, 'usage': {}}
            try:
                write(path, record)
            except OSError:
                try: app.request('thread/delete', {'threadId': thread})
                except Cancelled: raise
                except Exception: pass
                raise
            idle = getattr(app, 'idle_seconds', None)
            deadline = getattr(app, 'deadline', None)
            if idle is not None: app.idle_seconds = min(idle, 30)
            if deadline is not None: app.deadline = min(deadline, time.monotonic() + 30)
            try:
                if result.get('approvalPolicy') != 'never' or result.get('sandbox', {}).get('type') != 'readOnly':
                    raise ValueError('invalid parent sandbox')
                turn = app.request('turn/start', {'threadId': thread, 'model': params['model'], 'effort': 'low', 'input': [{'type': 'text', 'text': SYNTHETIC_INPUT}]})
                turn_id = turn['turn']['id']
                while True:
                    obj = app.pending.pop(0) if app.pending else app.next()
                    if obj.get('method') == 'thread/tokenUsage/updated':
                        usage = obj.get('params', {}).get('tokenUsage', {}).get('total', {})
                        if isinstance(usage, dict) and all(type(usage.get(k)) is int and usage[k] >= 0 for k in USAGE_FIELDS[:3]):
                            record['usage'] = {k: usage.get(k, 0) for k in USAGE_FIELDS if type(usage.get(k, 0)) is int and usage.get(k, 0) >= 0}
                    if obj.get('method') == 'turn/completed' and obj.get('params', {}).get('turn', {}).get('id') == turn_id:
                        if obj['params']['turn'].get('status') != 'completed': raise ValueError('parent turn failed')
                        break
                app.pending.clear()
                if not all(k in record['usage'] for k in USAGE_FIELDS[:3]): raise ValueError('parent usage unavailable')
                record['state'] = 'active'
                write(path, record)
            except Cancelled:
                raise
            except Exception:
                app.reuse_broken = True
                app.pending.clear()
                delete(app, path, record)
                app.pending.clear()
                return None
            finally:
                if idle is not None: app.idle_seconds = idle
                if deadline is not None: app.deadline = deadline
        fork_params = {'threadId': record['thread'], 'ephemeral': True, 'excludeTurns': True, 'cwd': params['cwd']}
        if FORK_OVERRIDE_INSTRUCTIONS:
            fork_params['baseInstructions'] = params['baseInstructions']
        try:
            result = app.request('thread/fork', fork_params)
            child = result['thread']['id']
            if (not isinstance(child, str) or str(uuid.UUID(child)) != child.lower() or child == record['thread'] or
                    result['thread'].get('forkedFromId', record['thread']) != record['thread'] or
                    result.get('approvalPolicy') != 'never' or result.get('sandbox', {}).get('type') != 'readOnly'):
                raise ValueError('invalid fork response')
        except Cancelled:
            record['state'] = 'pending-delete'
            try: write(path, record)
            except OSError: pass
            raise
        except Exception:
            app.reuse_broken = True
            delete(app, path, record)
            return None
        record['used'] = now
        write(path, record)
        result['_parent_usage'] = record['usage']
        return result
    finally:
        os.close(fd)
