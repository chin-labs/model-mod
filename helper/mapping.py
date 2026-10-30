"""Pure conversions between Messages and app-server structures."""
import base64
import hashlib
import json
import re


class InvalidRequest(Exception):
    pass


def names(tools):
    forward, reverse = {}, {}
    for tool in tools:
        name = tool.get('name')
        if not isinstance(name, str) or not name or name in forward:
            raise InvalidRequest('invalid or duplicate tool name')
        encoded = name if re.fullmatch(r'[a-zA-Z0-9_-]{1,64}', name) else 'bridge_' + hashlib.sha256(name.encode()).hexdigest()[:57]
        if encoded in reverse:
            raise InvalidRequest('tool name mapping collision')
        forward[name], reverse[encoded] = encoded, name
    return forward, reverse


def image(block):
    source = block.get('source', {})
    if source.get('type') == 'base64' and isinstance(source.get('data'), str) and isinstance(source.get('media_type'), str):
        try:
            base64.b64decode(source['data'], validate=True)
        except ValueError:
            raise InvalidRequest('invalid image data')
        return {'type': 'input_image', 'image_url': 'data:' + source['media_type'] + ';base64,' + source['data']}
    if source.get('type') == 'url' and isinstance(source.get('url'), str):
        return {'type': 'input_image', 'image_url': source['url']}
    raise InvalidRequest('unsupported image source')


def blocks(content):
    if isinstance(content, str):
        return [{'type': 'text', 'text': content}]
    if not isinstance(content, list) or not all(isinstance(b, dict) for b in content):
        raise InvalidRequest('invalid content')
    return content


def prepare(body, model_map):
    if not isinstance(body, dict) or not isinstance(body.get('model'), str) or body['model'] not in model_map:
        raise InvalidRequest('unknown model')
    msgs, tools = body.get('messages'), body.get('tools', [])
    if not isinstance(msgs, list) or not msgs or not isinstance(tools, list) or not all(isinstance(t, dict) for t in tools):
        raise InvalidRequest('invalid messages or tools')
    if not isinstance(body.get('stream', False), bool):
        raise InvalidRequest('invalid stream')
    forward, reverse = names(tools)
    # Historical tools may not be offered in the current turn.
    history_names = []
    for msg in msgs:
        if isinstance(msg, dict) and isinstance(msg.get('content'), list):
            for block in msg['content']:
                if isinstance(block, dict) and block.get('type') == 'tool_use':
                    name = block.get('name')
                    if not isinstance(name, str) or not name: raise InvalidRequest('invalid historical tool name')
                    if name not in forward and name not in history_names: history_names.append(name)
    forward, reverse = names(tools + [{'name': name} for name in history_names])
    dynamic = []
    for t in tools:
        if not isinstance(t.get('input_schema'), dict) or not isinstance(t.get('description', ''), str):
            raise InvalidRequest('invalid tool schema')
        dynamic.append({'type': 'function', 'name': forward[t['name']], 'description': t.get('description', ''), 'inputSchema': t['input_schema']})
    system = body.get('system', '')
    if isinstance(system, list):
        if any(not isinstance(x, dict) or x.get('type') != 'text' or not isinstance(x.get('text'), str) for x in system):
            raise InvalidRequest('invalid system')
        system = '\n\n'.join(x['text'] for x in system)
    if not isinstance(system, str):
        raise InvalidRequest('invalid system')
    ignored = set(k for k in ('max_tokens', 'tool_choice', 'temperature', 'top_p', 'stop_sequences', 'thinking') if k in body)
    def scan(v):
        if isinstance(v, dict):
            if 'cache_control' in v: ignored.add('cache_control')
            if 'signature' in v: ignored.add('signature')
            for child in v.values(): scan(child)
        elif isinstance(v, list):
            for child in v: scan(child)
    scan(body)
    history, dropped = [], 0
    for msg in msgs:
        if not isinstance(msg, dict) or msg.get('role') not in ('user', 'assistant'):
            raise InvalidRequest('invalid message role')
        role = msg['role']
        for b in blocks(msg.get('content')):
            kind = b.get('type')
            if kind == 'text' and isinstance(b.get('text'), str):
                history.append({'type': 'message', 'role': role, 'content': [{'type': 'input_text' if role == 'user' else 'output_text', 'text': b['text']}]})
            elif kind == 'image' and role == 'user':
                history.append({'type': 'message', 'role': role, 'content': [image(b)]})
            elif kind == 'tool_use' and role == 'assistant':
                if b.get('name') not in forward or not isinstance(b.get('id'), str) or not isinstance(b.get('input'), dict):
                    raise InvalidRequest('invalid historical tool use')
                history.append({'type': 'function_call', 'name': forward[b['name']], 'call_id': b['id'], 'arguments': json.dumps(b['input'], ensure_ascii=False)})
            elif kind == 'tool_result' and role == 'user':
                if not isinstance(b.get('tool_use_id'), str): raise InvalidRequest('invalid tool result')
                content = blocks(b.get('content', ''))
                result = []
                for part in content:
                    if part.get('type') == 'text' and isinstance(part.get('text'), str): result.append({'type': 'input_text', 'text': part['text']})
                    elif part.get('type') == 'image': result.append(image(part))
                    else: raise InvalidRequest('invalid tool result content')
                if b.get('is_error'): result.insert(0, {'type': 'input_text', 'text': 'ERROR: '})
                output = ''.join(p['text'] for p in result) if all(p['type'] == 'input_text' for p in result) else result
                history.append({'type': 'function_call_output', 'call_id': b['tool_use_id'], 'output': output})
            elif kind in ('thinking', 'redacted_thinking'):
                dropped += 1
            else:
                raise InvalidRequest('unsupported content block')
    last = msgs[-1]
    last_blocks = blocks(last['content'])
    if last['role'] == 'user' and all(b.get('type') in ('text', 'image') for b in last_blocks):
        count = len(last_blocks)
        history = history[:-count] if count else history
        turn_input = [({'type': 'text', 'text': b['text'], 'text_elements': []} if b['type'] == 'text' else {'type': 'image', 'url': image(b)['image_url']}) for b in last_blocks]
    else:
        turn_input = [{'type': 'text', 'text': 'Continue based on the conversation and tool results.', 'text_elements': []}]
    if not turn_input: raise InvalidRequest('empty turn input')
    return {'model': model_map[body['model']], 'client_model': body['model'], 'system': system, 'tools': dynamic, 'history': history, 'input': turn_input, 'reverse': reverse, 'ignored': sorted(ignored), 'dropped': dropped, 'stream': body.get('stream', False)}


def usage_delta(before, after):
    def delta(key): return max(0, after.get(key, 0) - before.get(key, 0))
    total, cached, written = delta('inputTokens'), delta('cachedInputTokens'), delta('cacheWriteInputTokens')
    return {'input_tokens': max(0, total - cached - written), 'output_tokens': delta('outputTokens'), 'cache_read_input_tokens': cached, 'cache_creation_input_tokens': written}


def classify(error):
    if not isinstance(error, dict): return 500, 'api_error'
    code = error.get('code')
    info = error.get('codexErrorInfo')
    kind = info if isinstance(info, str) else next(iter(info), None) if isinstance(info, dict) else None
    message = error.get('message')
    if code == 429 or kind in ('rateLimit', 'usageLimit', 'sessionBudgetExceeded') or message == 'rate limit':
        return 429, 'rate_limit_error'
    if code == 400 or kind in ('badRequest', 'modelNotFound', 'cyberPolicy', 'misalignmentPolicyViolation') or message == 'invalid request':
        return 400, 'invalid_request_error'
    return 500, 'api_error'
