"""Private, versioned records for read-only background delegation."""
import contextlib
import fcntl
import hashlib
import json
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
                with open(os.path.join(self.root, filename), encoding='utf-8') as source:
                    record = json.load(source)
                if record.get('id') == filename[:-5] and record.get('version') == 1 and set(record) == FIELDS:
                    result.append(record)
            except (OSError, ValueError, TypeError, AttributeError):
                continue
        return result

    def resolve(self, prefix):
        if not isinstance(prefix, str) or not re.fullmatch(r'[0-9a-f]{1,32}', prefix): raise ValueError('Invalid job ID.')
        matches = [record for record in self.records() if record['id'].startswith(prefix)]
        if not matches: raise ValueError('Job not found.')
        if len(matches) != 1: raise ValueError('Ambiguous job ID; provide more characters.')
        return matches[0]

    def write(self, record):
        if set(record) != FIELDS: raise ValueError('Invalid job record.')
        atomic_write(self.path(record['id'], '.json'), json.dumps(record, ensure_ascii=False, separators=(',', ':')).encode('utf-8'))

    def create(self, cwd, account, model, effort, kind, mode, generation):
        with self.locked():
            records = self.records()
            if len(records) >= MAX_JOBS: raise ValueError('Job limit reached; clear completed jobs.')
            if sum(r['account'] == account and r['state'] == 'queued' for r in records) >= 5:
                raise ValueError('Account queue is full; wait for a job to start.')
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
            for record in self.records():
                if record['state'] not in TERMINAL: continue
                if workspace is not None and record['workspaceHash'] != workspace: continue
                if older_than is not None and record['updatedAt'] >= older_than: continue
                for suffix in ('.json', '.result'):
                    try: os.unlink(self.path(record['id'], suffix))
                    except FileNotFoundError: pass
                removed += 1
            return removed
