"""Private, best-effort parent thread registry for the Messages bridge."""
import fcntl
import hashlib
import json
import os
import re
import tempfile
import time
import uuid

TTL_SECONDS = 6 * 60 * 60
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
        if set(data) != {'key', 'thread', 'account', 'created', 'used', 'state'}: return None
        if not all(isinstance(data[k], str) for k in ('key', 'thread', 'account', 'state')): return None
        if not re.fullmatch(r'[0-9a-f]{64}', data['key']) or not re.fullmatch(r'[0-9a-f]{64}', data['account']): return None
        if not re.fullmatch(r'[0-9a-f-]{36}', data['thread']) or data['state'] not in ('active', 'pending-delete'): return None
        if not all(type(data[k]) in (int, float) for k in ('created', 'used')): return None
        return data
    except (OSError, ValueError, TypeError): return None


def delete(app, path, record):
    record['state'] = 'pending-delete'
    write(path, record)
    try:
        app.request('thread/delete', {'threadId': record['thread']})
    except Exception:
        return False
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
        group = digest([session, account, params['model']])
        settings = dict(params)
        settings.pop('cwd', None)  # Per-request empty temporary working directory.
        if FORK_OVERRIDE_INSTRUCTIONS:
            settings.pop('baseInstructions', None)
        key = digest([session, account, settings, getattr(app, 'launch_args', []), app.web_search, args.no_keep_reasoning, args.service_tier, args.compact_window])
        path = os.path.join(root, group + '-' + key + '.json')
        now = time.time()
        for name in os.listdir(root):
            if not re.fullmatch(r'[0-9a-f]{64}-[0-9a-f]{64}\.json', name): continue
            item_path = os.path.join(root, name)
            item = record_at(item_path)
            if not item or item['account'] != account: continue
            if item['state'] == 'pending-delete' or now - item['used'] >= TTL_SECONDS or (name.startswith(group + '-') and item_path != path):
                delete(app, item_path, item)
        record = record_at(path)
        if record is None and os.path.lexists(path): return None
        if record and record['state'] != 'active': return None
        if not record:
            parent = dict(params, ephemeral=False)
            if FORK_OVERRIDE_INSTRUCTIONS:
                parent['baseInstructions'] = PARENT_INSTRUCTIONS
            result = app.request('thread/start', parent)
            thread = result['thread']['id']
            if str(uuid.UUID(thread)) != thread.lower(): return None
            record = {'key': key, 'thread': thread, 'account': account, 'created': now, 'used': now, 'state': 'pending-delete'}
            try:
                write(path, record)
            except OSError:
                try: app.request('thread/delete', {'threadId': thread})
                except Exception: pass
                raise
            try:
                if result.get('approvalPolicy') != 'never' or result.get('sandbox', {}).get('type') != 'readOnly':
                    raise ValueError('invalid parent sandbox')
                turn = app.request('turn/start', {'threadId': thread, 'model': params['model'], 'effort': 'low', 'input': [{'type': 'text', 'text': SYNTHETIC_INPUT}]})
                turn_id = turn['turn']['id']
                while True:
                    obj = app.pending.pop(0) if app.pending else app.next()
                    if obj.get('method') == 'turn/completed' and obj.get('params', {}).get('turn', {}).get('id') == turn_id:
                        if obj['params']['turn'].get('status') != 'completed': raise ValueError('parent turn failed')
                        break
                app.pending.clear()
                record['state'] = 'active'
                write(path, record)
            except Exception:
                app.pending.clear()
                delete(app, path, record)
                app.pending.clear()
                return None
        fork_params = {'threadId': record['thread'], 'ephemeral': True, 'excludeTurns': True, 'cwd': params['cwd']}
        if FORK_OVERRIDE_INSTRUCTIONS:
            fork_params['baseInstructions'] = params['baseInstructions']
        try:
            result = app.request('thread/fork', fork_params)
            child = result['thread']['id']
            if (str(uuid.UUID(child)) != child.lower() or child == record['thread'] or
                    result['thread'].get('forkedFromId', record['thread']) != record['thread'] or
                    result.get('approvalPolicy') != 'never' or result.get('sandbox', {}).get('type') != 'readOnly'):
                raise ValueError('invalid fork response')
        except Exception:
            delete(app, path, record)
            return None
        record['used'] = now
        write(path, record)
        return result
    finally:
        os.close(fd)
