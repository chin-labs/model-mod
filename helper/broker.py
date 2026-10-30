"""Local supervisor and private IPC for read-only background delegation."""
import errno
import fcntl
import hmac
import json
import os
import re
import secrets
import signal
import socket
import socketserver
import struct
import subprocess
import sys
import threading
import time

import job_process
import jobs
from bridge import BridgeError, account_home

MAX_REQUEST = 256_000
IDLE_SECONDS = 30 * 60
CLEANUP_INTERVAL = 60 * 60
HELPER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'delegate.py')


def root_path():
    return os.path.join(os.environ.get('XDG_STATE_HOME') or os.path.join(os.path.expanduser('~'), '.' + 'local', 'state'),
                        'model-mod', 'delegate', 'v1')


def account_root():
    return os.path.join(os.path.expanduser('~'), '.config', 'model-mod', 'accounts')


def paths(root):
    return (os.path.join(root, 'model-mod.sock'), os.path.join(root, 'token.json'),
            os.path.join(root, 'broker.pid'), os.path.join(root, '.broker.lock'))


def minimal_env():
    return {key: os.environ[key] for key in ('HOME', 'XDG_STATE_HOME', 'PATH', 'TMPDIR', 'LANG') if key in os.environ}


def peer_uid(conn):
    if hasattr(conn, 'getpeereid'):
        return conn.getpeereid()[0]
    if hasattr(socket, 'SO_PEERCRED'):
        return struct.unpack('3i', conn.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))[1]
    if sys.platform == 'darwin':
        # xucred begins with version, uid, ngroups; LOCAL_PEERCRED is 1 at SOL_LOCAL (0).
        try: return struct.unpack_from('=II', conn.getsockopt(0, 1, 76))[1]
        except OSError as exc:
            if exc.errno in (errno.ENOPROTOOPT, errno.EOPNOTSUPP): return None
            raise
    return None


def connect(root, method, payload=None, timeout=1):
    sockpath, tokenpath, _, _ = paths(root)
    with open(tokenpath, encoding='utf-8') as source: credentials = json.load(source)
    request = {'method': method, 'token': credentials['token'], 'generation': credentials['generation']}
    if payload: request.update(payload)
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
        conn.settimeout(timeout)
        conn.connect(sockpath)
        conn.sendall(json.dumps(request, ensure_ascii=False).encode('utf-8') + b'\n')
        data = bytearray()
        while not data.endswith(b'\n'):
            chunk = conn.recv(65536)
            if not chunk or len(data) + len(chunk) > 1_100_000: raise ValueError('Invalid broker response.')
            data.extend(chunk)
    return json.loads(data)


def ensure():
    if os.name != 'posix': return
    root = root_path()
    try:
        jobs.Store(root)
        sockpath, tokenpath, pidpath, lockpath = paths(root)
        fd = os.open(lockpath, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            deadline = time.monotonic() + 1.5
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline: return
                    time.sleep(.02)
            instance = os.open(os.path.join(root, '.instance.lock'), os.O_CREAT | os.O_RDWR, 0o600)
            try:
                os.fchmod(instance, 0o600)
                try: fcntl.flock(instance, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError: return
                credentials = {'token': secrets.token_hex(32), 'generation': secrets.token_hex(16)}
                jobs.atomic_write(tokenpath, json.dumps(credentials).encode())
                child_env = dict(minimal_env(), MODEL_MOD_BROKER_LOCK_FD=str(instance))
                proc = subprocess.Popen([sys.executable, HELPER, 'broker'], stdin=subprocess.DEVNULL,
                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                        env=child_env, start_new_session=True, close_fds=True, pass_fds=(instance,))
                jobs.atomic_write(pidpath, str(proc.pid).encode())
            finally:
                os.close(instance)
            while time.monotonic() < deadline:
                try:
                    reply = connect(root, 'ping', timeout=.1)
                    if reply.get('generation') == credentials['generation']: return
                except (OSError, ValueError, KeyError): pass
                if proc.poll() is not None: return
                time.sleep(.02)
        finally:
            os.close(fd)
    except Exception:
        pass


def terminate_group(pgid, proc=None):
    try: os.killpg(pgid, signal.SIGTERM)
    except ProcessLookupError: return True
    except PermissionError: return proc is not None and proc.poll() is not None
    time.sleep(.15)
    try: os.killpg(pgid, signal.SIGKILL)
    except ProcessLookupError: pass
    except PermissionError: return proc is not None and proc.poll() is not None
    return True


class Server(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, root, credentials):
        self.root = root
        self.store = jobs.Store(root)
        self.credentials = credentials
        self.guard = threading.RLock()
        self.pending = {}
        self.children = {}
        self.last_ipc = time.monotonic()
        self.last_cleanup = time.monotonic()
        self.stopping = False
        self.recover()
        self.store.clear(older_than=time.time() - jobs.RETENTION_SECONDS)
        sockpath = paths(root)[0]
        try: os.unlink(sockpath)
        except FileNotFoundError: pass
        super().__init__(sockpath, Handler)
        os.chmod(sockpath, 0o600)
        self.timeout = .2

    def recover(self):
        for record in self.store.records():
            try:
                if record['state'] in jobs.TERMINAL: continue
                members = [m for m in (record.get('runner'), record.get('appServer')) if isinstance(m, dict)]
                pgid = record.get('pgid')
                if (record.get('runner') and record['runner']['pid'] == pgid and
                        job_process.verified_group(pgid, members)):
                    error = 'broker_restarted' if terminate_group(pgid) else 'possible_leftover'
                else:
                    error = 'possible_leftover'
                self.store.transition(record['id'], 'interrupted', error=error)
            except Exception: continue

    def submit(self, req):
        if 'accountsDir' in req or 'directory' in req:
            raise ValueError('Background jobs support only the default account root.')
        cwd, account, model, kind, options, binary = (req.get(k) for k in ('cwd', 'account', 'model', 'kind', 'options', 'codexBin'))
        if not isinstance(cwd, str) or not os.path.isabs(cwd) or not os.path.isdir(cwd): raise ValueError('Invalid working directory.')
        if not isinstance(account, str) or not isinstance(model, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}', model): raise ValueError('Invalid account or model.')
        if kind not in ('review', 'rescue') or not isinstance(options, dict) or not isinstance(binary, str) or not binary: raise ValueError('Invalid job request.')
        if set(options) - {'base', 'adversarial', 'effort', 'text'}: raise ValueError('Invalid job options.')
        if options.get('effort') not in (None, 'low', 'medium', 'high', 'xhigh'): raise ValueError('Invalid effort.')
        if options.get('base') is not None and not isinstance(options['base'], str): raise ValueError('Invalid base.')
        if not isinstance(options.get('text', ''), str) or not isinstance(options.get('adversarial', False), bool): raise ValueError('Invalid job options.')
        if kind == 'rescue' and not options.get('text', '').strip(): raise ValueError('A task is required.')
        if kind == 'review' and not options.get('adversarial') and (options.get('text') or options.get('effort')): raise ValueError('Invalid review options.')
        home, _ = account_home(account_root(), account)
        if not os.path.isdir(home): raise ValueError('Account is unavailable in the default account root.')
        request = {'cwd': cwd, 'account': account, 'model': model, 'kind': kind, 'options': options,
                   'codexBin': binary, 'accountsDir': account_root(), 'directory': home}
        record = self.store.create(cwd, account, model, options.get('effort'), kind, 'read-only', self.credentials['generation'])
        self.pending[record['id']] = request
        self.schedule()
        return {'ok': True, 'job': self.store.resolve(record['id'])}

    def schedule(self):
        for ident, request in list(self.pending.items()):
            try:
                if sum(child['account'] == request['account'] for child in self.children.values()) >= 2: continue
                if not self.store.transition(ident, 'starting'):
                    self.pending.pop(ident, None)
                    continue
                try:
                    proc = subprocess.Popen([sys.executable, HELPER, 'runner', ident, str(os.getpid())], stdin=subprocess.PIPE,
                                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                            env=minimal_env(), start_new_session=True, close_fds=True)
                    self.children[ident] = {'proc': proc, 'account': request['account'], 'cancel': False}
                    self.store.set_process(ident, pgid=proc.pid, runner={'pid': proc.pid, 'started': job_process.start_time(proc.pid)})
                    proc.stdin.write(json.dumps(request, ensure_ascii=False).encode())
                    proc.stdin.close()
                except Exception:
                    child = self.children.pop(ident, None)
                    if child is not None:
                        terminate_group(child['proc'].pid, child['proc'])
                        child['proc'].wait(timeout=2)
                    self.store.transition(ident, 'failed', error='runner_start_failed')
                finally:
                    self.pending.pop(ident, None)
            except Exception: continue

    def dispatch(self, request):
        if not isinstance(request, dict) or not hmac.compare_digest(str(request.get('token', '')), self.credentials['token']) or request.get('generation') != self.credentials['generation']:
            return {'ok': False, 'error': 'Unauthorized.'}
        method = request.get('method')
        with self.guard:
            self.last_ipc = time.monotonic()
            if method == 'ping': return {'ok': True, 'generation': self.credentials['generation']}
            if method == 'submit': return self.submit(request.get('request') or {})
            if method == 'list':
                if request.get('clear'): self.store.clear(workspace=jobs.workspace_hash(request['cwd']))
                records = self.store.records()
                if not request.get('all'): records = [r for r in records if r['workspaceHash'] == jobs.workspace_hash(request['cwd'])]
                return {'ok': True, 'jobs': records}
            if method in ('status', 'result', 'cancel'):
                record = self.store.resolve(request.get('id'))
                ident = record['id']
                if method == 'status': return {'ok': True, 'job': record}
                if method == 'result':
                    if not record['resultRef']: raise jobs.UserError('No result is available.')
                    from delegate import clean
                    with open(self.store.path(ident, '.result'), encoding='utf-8') as source: text = clean(source.read(1_000_001))
                    return {'ok': True, 'job': record, 'text': text}
                if record['state'] == 'queued':
                    self.store.transition(ident, 'cancelled')
                    self.pending.pop(ident, None)
                elif ident in self.children and record['state'] not in jobs.TERMINAL:
                    self.store.transition(ident, 'cancelling')
                    child = self.children[ident]
                    child['cancel'] = True
                    cleaned = terminate_group(child['proc'].pid, child['proc'])
                    self.store.transition(ident, 'cancelled', error=None if cleaned else 'possible_leftover')
                return {'ok': True, 'job': self.store.resolve(ident)}
            if method == 'shutdown':
                self.stopping = True
                return {'ok': True}
            raise ValueError('Unknown broker method.')

    def tick(self):
        with self.guard:
            for ident, child in list(self.children.items()):
                finished = False
                try:
                    finished = child['proc'].poll() is not None
                    if not finished: continue
                    cleaned = terminate_group(child['proc'].pid, child['proc'])
                    record = self.store.resolve(ident)
                    if record['state'] not in jobs.TERMINAL:
                        error = 'possible_leftover' if not cleaned else None if child['cancel'] else 'runner_exited'
                        self.store.transition(ident, 'cancelled' if child['cancel'] else 'interrupted', error=error)
                except Exception:
                    pass
                finally:
                    if finished: self.children.pop(ident, None)
            self.schedule()
            now = time.monotonic()
            if now - self.last_cleanup >= CLEANUP_INTERVAL:
                self.store.clear(older_than=time.time() - jobs.RETENTION_SECONDS)
                self.last_cleanup = now
            if not self.children and not self.pending and now - self.last_ipc >= IDLE_SECONDS: self.stopping = True

    def finish(self):
        try:
            with self.guard:
                for ident, child in list(self.children.items()):
                    try:
                        cleaned = terminate_group(child['proc'].pid, child['proc'])
                        child['proc'].wait(timeout=2)
                        self.store.transition(ident, 'interrupted', error='broker_stopped' if cleaned else 'possible_leftover')
                    except Exception: continue
                for ident in self.pending:
                    try: self.store.transition(ident, 'interrupted', error='broker_stopped')
                    except Exception: continue
        finally:
            try: self.server_close()
            finally:
                for path in paths(self.root)[:3]:
                    try: os.unlink(path)
                    except OSError: pass



class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        self.connection.settimeout(2)
        try:
            uid = peer_uid(self.connection)
            if uid is not None and uid != os.getuid(): return
            line = self.rfile.readline(MAX_REQUEST + 1)
            if len(line) > MAX_REQUEST or not line.endswith(b'\n'): return
            response = self.server.dispatch(json.loads(line))
        except jobs.UserError as exc:
            response = {'ok': False, 'error': str(exc)}
        except BridgeError:
            response = {'ok': False, 'error': 'Invalid account.'}
        except Exception:
            response = {'ok': False, 'error': 'Invalid or unavailable request.'}
        try: self.wfile.write(json.dumps(response, ensure_ascii=False).encode() + b'\n')
        except OSError: pass


def serve():
    root = root_path()
    jobs.Store(root)
    inherited = os.environ.pop('MODEL_MOD_BROKER_LOCK_FD', None)
    instance = int(inherited) if inherited is not None else os.open(os.path.join(root, '.instance.lock'), os.O_CREAT | os.O_RDWR, 0o600)
    os.fchmod(instance, 0o600)
    if inherited is None:
        try: fcntl.flock(instance, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(instance)
            return
    try:
        with open(paths(root)[1], encoding='utf-8') as source: credentials = json.load(source)
        server = Server(root, credentials)
    except BaseException:
        os.close(instance)
        raise
    def stop(signum, frame): server.stopping = True
    signal.signal(signal.SIGTERM, stop)
    try:
        while not server.stopping:
            server.handle_request()
            try: server.tick()
            except Exception: pass
    finally:
        try: server.finish()
        finally: os.close(instance)
