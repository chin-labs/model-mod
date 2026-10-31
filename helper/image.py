#!/usr/bin/env python3
"""Generate one image in an isolated Codex app-server session."""
import base64
import binascii
import json
import os
import signal
import stat
import sys
import time
from types import SimpleNamespace

from bridge import FEATURES, account_home, note, verify_version
from delegate import App, Cancelled, Failure, cancel, checked_project_layers

MAX_IMAGE = 20 * 1024 * 1024
MAX_LINE = (MAX_IMAGE + 2) // 3 * 4 + 65536
IMAGE_DISABLED = tuple(f for f in FEATURES if f != 'image_generation') + ('memories',)


def remove_generated(home, path):
    """Unlink only a regular file below the literal generated_images directory."""
    root = os.path.join(home, 'generated_images')
    try:
        if not isinstance(path, str) or not os.path.isabs(path) or os.path.islink(root):
            raise OSError('invalid path')
        root = os.path.realpath(root)
        if os.path.commonpath((root, os.path.realpath(path))) != root:
            raise OSError('outside generated images')
        relative = os.path.relpath(path, root)
        parts = relative.split(os.sep)
        if any(p in ('', '.', '..') for p in parts): raise OSError('invalid path')
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        fd = os.open(root, flags)
        try:
            for part in parts[:-1]:
                newfd = os.open(part, flags, dir_fd=fd)
                os.close(fd)
                fd = newfd
            info = os.stat(parts[-1], dir_fd=fd, follow_symlinks=False)
            if not stat.S_ISREG(info.st_mode): raise OSError('not a regular file')
            os.unlink(parts[-1], dir_fd=fd)
        finally:
            os.close(fd)
    except (OSError, ValueError, AttributeError):
        note('Could not remove the Codex generated image; remove it manually from generated_images.')


def check_platform():
    if os.name != 'posix' or not hasattr(os, 'O_DIRECTORY') or not hasattr(os, 'O_NOFOLLOW'):
        raise Failure('Image output requires POSIX no-follow directory support; use a supported platform.')


def execute(request):
    check_platform()
    started = time.monotonic()
    prompt = request.get('prompt')
    if not isinstance(prompt, str) or not 1 <= len(prompt.strip()) <= 4000:
        raise Failure('Prompt must be 1–4000 characters.')
    size, quality = request.get('size'), request.get('quality')
    if size not in ('1024x1024', '1536x1024', '1024x1536', 'auto') or quality not in ('low', 'medium', 'high', 'auto'):
        raise Failure('Unsupported size or quality.')
    cwd = request['cwd']
    if not os.path.isabs(cwd) or not os.path.isdir(cwd): raise Failure('Working directory is unavailable.')
    home, _ = account_home(request['accountsDir'], request['account'])
    if not os.path.isdir(home) or os.path.realpath(request['directory']) != home: raise Failure('Invalid Codex account directory.')
    verify_version(SimpleNamespace(codex_bin=request['codexBin'], codex_home=home))
    request['directory'] = home
    app = App(request, features=IMAGE_DISABLED, enable_image=True, max_line=MAX_LINE)
    app.deadline = started + 300
    try:
        init = app.request('initialize', {'clientInfo': {'name': 'model-mod-image', 'version': '0.2.0'}, 'capabilities': {'experimentalApi': True}})
        if not isinstance(init.get('codexHome'), str) or os.path.realpath(init['codexHome']) != home: raise Failure('Codex account directory mismatch.')
        app.send({'method': 'initialized', 'params': {}})
        result = app.request('config/read', {'includeLayers': True, 'cwd': cwd})
        checked_project_layers(result)
        config = result.get('config', {})
        flags = config.get('features', {})
        if config.get('web_search') != 'disabled' or config.get('mcp_servers') != {} or flags.get('image_generation') is not True or any(flags.get(f) is not False for f in IMAGE_DISABLED):
            raise Failure('Image generation is unavailable or Codex isolation could not be verified; update Codex and check its configuration.')
        account = app.request('account/read', {'refreshToken': False}).get('account')
        if not account: raise Failure('Codex is not logged in; sign in to the selected account.')
        start = app.request('thread/start', {'serviceName': 'model_mod', 'model': request['model'], 'cwd': cwd, 'sandbox': 'read-only', 'approvalPolicy': 'never', 'ephemeral': True})
        sandbox = start.get('sandbox')
        if start.get('approvalPolicy') != 'never' or not isinstance(sandbox, dict) or sandbox.get('type') != 'readOnly' or sandbox.get('networkAccess') is not False: raise Failure('Codex sandbox or approval policy mismatch.')
        app.thread = start.get('thread', {}).get('id')
        if not isinstance(app.thread, str) or not app.thread: raise Failure('Invalid Codex thread.')
        text = prompt.strip() + '\nRequested image size: ' + size + '; requested quality: ' + quality + '. Generate an image.'
        turn = app.request('turn/start', {'threadId': app.thread, 'model': request['model'], 'sandboxPolicy': {'type': 'readOnly', 'networkAccess': False}, 'input': [{'type': 'text', 'text': text, 'text_elements': []}]})
        app.turn = turn.get('turn', {}).get('id') or app.turn
        if not app.turn: raise Failure('Invalid Codex turn.')
        result = None
        while True:
            obj = app.pending.pop(0) if app.pending else app.next()
            method, params = obj.get('method'), obj.get('params') or {}
            if method == 'item/completed':
                item = params.get('item', {})
                kind = item.get('type')
                if kind == 'imageGeneration':
                    if item.get('status') != 'completed' or item.get('failure'): raise Failure('Image generation failed; check your Codex quota and try again.')
                    data = item.get('result')
                    if not isinstance(data, str) or len(data) > (MAX_IMAGE + 2) // 3 * 4: raise Failure('Image exceeds the 20 MB limit or has no inline result; request a smaller image or update Codex.')
                    try: raw = base64.b64decode(data, validate=True)
                    except (ValueError, binascii.Error): raise Failure('Codex returned an invalid image result.')
                    if not raw or len(raw) > MAX_IMAGE: raise Failure('Image exceeds the 20 MB limit; request a smaller image.')
                    if item.get('savedPath') is not None: remove_generated(home, item['savedPath'])
                    result = {'ok': True, 'bytes_b64': data, 'mime': 'image/png', 'size': len(raw)}
                elif kind not in ('userMessage', 'agentMessage', 'reasoning', 'contextCompaction'):
                    raise Failure('Unexpected Codex item; image generation stopped.')
            elif method == 'turn/completed':
                app.turn = None
                if params.get('turn', {}).get('status') != 'completed': raise Failure('Image generation failed; check your Codex quota and try again.')
                if not result: raise Failure('Codex returned no image; check that image generation is enabled and try again.')
                return result
            elif method == 'error' and not params.get('willRetry'):
                raise Failure('Codex image generation failed; check your login and quota and try again.')
    finally:
        app.close()


def check_output(request):
    check_platform()
    cwd, path = request['cwd'], request['path']
    if not isinstance(path, str) or path.startswith('/') or not path.endswith('.png') or any(p in ('', '.', '..') for p in path.split('/')):
        raise Failure('Invalid output path.')
    fd = os.open(os.path.realpath(cwd), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        parts = path.split('/')
        for part in parts[:-1]:
            try: newfd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            except FileNotFoundError: return {'ok': True}
            os.close(fd)
            fd = newfd
        try: os.stat(parts[-1], dir_fd=fd, follow_symlinks=False)
        except FileNotFoundError: return {'ok': True}
        raise Failure('Could not save image; the output path already exists.')
    finally:
        os.close(fd)


def write_image(request):
    check_platform()
    cwd, path, data = request['cwd'], request['path'], request['bytes_b64']
    if not isinstance(path, str) or path.startswith('/') or not path.endswith('.png') or any(p in ('', '.', '..') for p in path.split('/')):
        raise Failure('Invalid output path.')
    if not isinstance(data, str) or len(data) > (MAX_IMAGE + 2) // 3 * 4: raise Failure('Image exceeds the 20 MB limit.')
    try: raw = base64.b64decode(data, validate=True)
    except (ValueError, binascii.Error): raise Failure('Invalid image data.')
    if len(raw) > MAX_IMAGE or not raw.startswith(b'\x89PNG\r\n\x1a\n'): raise Failure('Invalid PNG image.')
    root = os.path.realpath(cwd)
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    fd = os.open(root, flags)
    try:
        parts = path.split('/')
        for part in parts[:-1]:
            try: os.mkdir(part, 0o700, dir_fd=fd)
            except FileExistsError: pass
            newfd = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = newfd
        out = os.open(parts[-1], os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
        try:
            with os.fdopen(out, 'wb') as stream: stream.write(raw)
        except BaseException:
            try: os.unlink(parts[-1], dir_fd=fd)
            except OSError: pass
            raise
        return {'ok': True, 'size': len(raw)}
    finally:
        os.close(fd)


def main():
    signal.signal(signal.SIGTERM, cancel)
    signal.signal(signal.SIGINT, cancel)
    try:
        writing = sys.argv[1:] == ['--write']
        checking = sys.argv[1:] == ['--check']
        limit = MAX_LINE if writing else 65536
        raw = sys.stdin.buffer.read(limit + 1)
        if len(raw) > limit: raise Failure('Image request is too large.')
        request = json.loads(raw)
        if not isinstance(request, dict): raise Failure('Invalid image request.')
        result = check_output(request) if checking else write_image(request) if writing else execute(request)
    except Cancelled:
        result = {'ok': False, 'code': 'cancelled', 'message': 'Image generation was cancelled.'}
    except Exception as exc:
        message = str(exc) if isinstance(exc, Failure) else ('Could not save image; check the path and ensure the file does not already exist.' if writing or checking else 'Image generation failed; check your Codex installation and login.')
        if getattr(exc, 'code', '') == 'codex_too_old': message = 'Codex is too old; update Codex to 0.165.0 or newer.'
        result = {'ok': False, 'code': 'image_error', 'message': message}
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == '__main__': main()
