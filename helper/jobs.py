"""Private, versioned records for read-only background delegation."""
import contextlib
import fcntl
import hashlib
import json
import math
import os
import re
import secrets
import tempfile
import threading
import time

RETENTION_SECONDS = 7 * 24 * 60 * 60
MAX_JOBS = 50
TERMINAL = frozenset(('completed', 'failed', 'cancelled', 'interrupted', 'unknown'))
TRANSITIONS = {
    'queued': frozenset(('starting', 'cancelled', 'interrupted')),
    'starting': frozenset(('running', 'cancelling', 'failed', 'interrupted', 'unknown')),
    'running': frozenset(('cancelling', 'completed', 'failed', 'interrupted', 'unknown')),
    'cancelling': frozenset(('cancelled', 'completed', 'failed', 'interrupted', 'unknown')),
}
ID = re.compile(r'^[0-9a-f]{32}$')
FIELDS = frozenset(('version', 'id', 'workspaceHash', 'account', 'model', 'effort', 'kind', 'mode',
                    'createdAt', 'updatedAt', 'state', 'phase', 'errorCode', 'resultRef', 'brokerGeneration',
                    'pgid', 'runner', 'appServer'))


class UserError(ValueError):
    pass


def valid_record(record, ident):
    if not isinstance(record, dict) or set(record) != FIELDS: return False
    if record['id'] != ident or type(record['version']) is not int or record['version'] != 1: return False
    if not isinstance(record['state'], str) or record['state'] not in set(TRANSITIONS) | TERMINAL: return False
    if not all(type(record[k]) is int or (type(record[k]) is float and math.isfinite(record[k]))
               for k in ('createdAt', 'updatedAt')): return False
    if not isinstance(record['account'], str) or not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,31}', record['account']): return False
    if not isinstance(record['workspaceHash'], str) or not re.fullmatch(r'[0-9a-f]{16}', record['workspaceHash']): return False
    if not all(isinstance(record[k], str) for k in ('model', 'kind', 'mode', 'phase', 'brokerGeneration')): return False
    if not all(record[k] is None or isinstance(record[k], str) for k in ('effort', 'errorCode', 'resultRef')): return False
    if record['resultRef'] not in (None, ident + '.result'): return False
    def positive(value): return type(value) is int and value > 0
    if record['pgid'] is not None and not positive(record['pgid']): return False
    for key in ('runner', 'appServer'):
        member = record[key]
        if member is not None and (not isinstance(member, dict) or set(member) != {'pid', 'started'} or
                                   not positive(member['pid']) or
                                   (member['started'] is not None and not isinstance(member['started'], str))): return False
    return True


def workspace_hash(cwd):
    return hashlib.sha256(os.fsencode(os.path.realpath(cwd))).hexdigest()[:16]


def atomic_write(path, data):
    directory = os.path.dirname(path)
    fd, temp = tempfile.mkstemp(prefix='.pending-', dir=directory)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'wb') as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temp, path)
        dirfd = os.open(directory, os.O_RDONLY)
        try: os.fsync(dirfd)
        finally: os.close(dirfd)
    finally:
        if os.path.exists(temp): os.unlink(temp)


class Store:
    def __init__(self, root):
        self.root = root
        self.lock = threading.RLock()
        os.makedirs(root, mode=0o700, exist_ok=True)
        os.chmod(root, 0o700)

    @contextlib.contextmanager
    def locked(self):
        with self.lock:
            fd = os.open(os.path.join(self.root, '.jobs.lock'), os.O_CREAT | os.O_RDWR, 0o600)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX)
                yield
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
                os.close(fd)

    def path(self, ident, suffix):
        if not isinstance(ident, str) or not ID.fullmatch(ident): raise ValueError('Invalid job ID.')
        return os.path.join(self.root, ident + suffix)

    def records(self):
        result = []
        for filename in os.listdir(self.root):
            if not re.fullmatch(r'[0-9a-f]{32}\.json', filename): continue
            try:
                path = os.path.join(self.root, filename)
                if os.stat(path).st_size > 1_000_000: continue
                with open(path, encoding='utf-8') as source:
                    data = source.read(1_000_001)
                if len(data.encode('utf-8')) > 1_000_000: continue
                record = json.loads(data)
                if valid_record(record, filename[:-5]): result.append(record)
            except (OSError, ValueError, TypeError, RecursionError):
                continue
        return result

    def resolve(self, prefix):
        if not isinstance(prefix, str) or not re.fullmatch(r'[0-9a-f]{1,32}', prefix): raise ValueError('Invalid job ID.')
        matches = [record for record in self.records() if record['id'].startswith(prefix)]
        if not matches: raise UserError('Job not found.')
        if len(matches) != 1: raise UserError('Ambiguous job ID; provide more characters.')
        return matches[0]

    def write(self, record):
        if set(record) != FIELDS: raise ValueError('Invalid job record.')
        atomic_write(self.path(record['id'], '.json'), json.dumps(record, ensure_ascii=False, separators=(',', ':')).encode('utf-8'))

    def create(self, cwd, account, model, effort, kind, mode, generation):
        with self.locked():
            records = self.records()
            if sum(r['account'] == account and r['state'] == 'queued' for r in records) >= 5:
                raise UserError('Account queue is full; wait for a job to start.')
            if len(records) >= MAX_JOBS:
                terminal = sorted((r for r in records if r['state'] in TERMINAL),
                                  key=lambda r: (r['errorCode'] == 'possible_leftover', r['createdAt']))
                if not terminal: raise UserError('Job limit reached; clear completed jobs.')
                oldest = terminal[0]
                for suffix in ('.json', '.result'):
                    try: os.unlink(self.path(oldest['id'], suffix))
                    except FileNotFoundError: pass
                records.remove(oldest)
            now = time.time()
            record = {'version': 1, 'id': secrets.token_hex(16), 'workspaceHash': workspace_hash(cwd),
                      'account': account, 'model': model, 'effort': effort, 'kind': kind, 'mode': mode,
                      'createdAt': now, 'updatedAt': now, 'state': 'queued', 'phase': 'queued',
                      'errorCode': None, 'resultRef': None, 'brokerGeneration': generation,
                      'pgid': None, 'runner': None, 'appServer': None}
            self.write(record)
            return record

    def transition(self, ident, state, *, phase=None, error=None, result=None):
        with self.locked():
            record = self.resolve(ident)
            if state not in TRANSITIONS.get(record['state'], ()):
                return False
            if result is not None:
                from delegate import clean
                result = clean(result).encode('utf-8')
                atomic_write(self.path(record['id'], '.result'), result)
                record['resultRef'] = record['id'] + '.result'
            record.update(state=state, phase=phase or state, errorCode=error, updatedAt=time.time())
            self.write(record)
            return True

    def set_process(self, ident, *, pgid=None, runner=None, app_server=None):
        with self.locked():
            record = self.resolve(ident)
            if record['state'] in TERMINAL: return False
            if pgid is not None: record['pgid'] = pgid
            if runner is not None: record['runner'] = runner
            if app_server is not None: record['appServer'] = app_server
            record['updatedAt'] = time.time()
            self.write(record)
            return True

    def clear(self, workspace=None, older_than=None):
        with self.locked():
            removed = 0
            records = self.records()
            valid_ids = {record['id'] for record in records}
            for filename in os.listdir(self.root):
                if older_than is not None and filename.startswith('.pending-'):
                    path = os.path.join(self.root, filename)
                    try:
                        if os.lstat(path).st_mtime < older_than:
                            os.unlink(path)
                            removed += 1
                    except OSError: pass
                    continue
                if not re.fullmatch(r'[0-9a-f]{32}\.json', filename) or filename[:-5] in valid_ids: continue
                path = os.path.join(self.root, filename)
                try:
                    if older_than is not None and os.stat(path).st_mtime >= older_than: continue
                    os.unlink(path)
                    try: os.unlink(self.path(filename[:-5], '.result'))
                    except FileNotFoundError: pass
                    removed += 1
                except OSError: continue
            for record in records:
                if record['state'] not in TERMINAL: continue
                if workspace is not None and record['workspaceHash'] != workspace: continue
                if older_than is not None and record['updatedAt'] >= older_than: continue
                for suffix in ('.json', '.result'):
                    try: os.unlink(self.path(record['id'], suffix))
                    except FileNotFoundError: pass
                removed += 1
            return removed
