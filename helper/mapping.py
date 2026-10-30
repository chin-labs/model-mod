"""Pure conversions between Messages and app-server structures."""
import base64
import hashlib
import json
import re


class InvalidRequest(Exception):
    pass


REASONING_PREFIX = 'mmcx1:'
REASONING_ITEM_LIMIT = 256 * 1024
REASONING_RESPONSE_LIMIT = 1024 * 1024
METADATA_FIELD = 'internal_chat_message_' + 'metadata_passthrough'


def valid_reasoning(item):
    def valid_text(value):
        if not isinstance(value, str): return False
        try: value.encode('utf-8')
        except UnicodeError: return False
        return True
    if not isinstance(item, dict) or set(item) - {'type', 'id', 'summary', 'content', 'encrypted_content', METADATA_FIELD}:
        return False
    if item.get('type') != 'reasoning' or not isinstance(item.get('summary'), list): return False
    for field in ('id', 'encrypted_content'):
        if field in item and item[field] is not None and not valid_text(item[field]): return False
    def text_items(value, allowed):
        return isinstance(value, list) and all(isinstance(x, dict) and set(x) == {'type', 'text'} and x['type'] in allowed and valid_text(x['text']) for x in value)
    if not text_items(item['summary'], ('summary_text',)): return False
    if item.get('content') is not None and not text_items(item['content'], ('text', 'reasoning_text')): return False
    metadata = item.get(METADATA_FIELD)
    if metadata is not None and (not isinstance(metadata, dict) or set(metadata) - {'turn_id'} or (metadata.get('turn_id') is not None and not valid_text(metadata['turn_id']))): return False
    return True


def encode_reasoning(item):
    if not valid_reasoning(item): return None
    try:
        raw = json.dumps(item, ensure_ascii=True, separators=(',', ':')).encode('ascii')
        signature = REASONING_PREFIX + base64.urlsafe_b64encode(raw).decode('ascii').rstrip('=')
    except (ValueError, TypeError, UnicodeError, RecursionError): return None
    return signature if len(signature) <= REASONING_ITEM_LIMIT else None


def decode_reasoning(signature):
    if not isinstance(signature, str) or not signature.startswith(REASONING_PREFIX) or len(signature) > REASONING_ITEM_LIMIT: return None
    encoded = signature[len(REASONING_PREFIX):]
    if not encoded or not re.fullmatch(r'[A-Za-z0-9_-]+', encoded): return None
    try:
        raw = base64.b64decode(encoded + '=' * (-len(encoded) % 4), altchars=b'-_', validate=True)
        if base64.urlsafe_b64encode(raw).decode('ascii').rstrip('=') != encoded: return None
        def unique(pairs):
            obj = {}
            for key, value in pairs:
                if key in obj: raise ValueError('duplicate key')
                obj[key] = value
            return obj
        item = json.loads(raw.decode('utf-8'), object_pairs_hook=unique)
        return item if valid_reasoning(item) else None
    except (ValueError, UnicodeError, RecursionError): return None


def names(tools):
    forward, reverse = {}, {}
    for tool in tools:
        name = tool.get('name')
        if not isinstance(name, str) or not name or name in forward:
            raise InvalidRequest('invalid or duplicate tool name')
        encoded = name if not name.startswith('mcp__') and re.fullmatch(r'[a-zA-Z0-9_-]{1,64}', name) else 'bridge_' + hashlib.sha256(name.encode()).hexdigest()[:57]
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


def prepare(body, model_map, keep_reasoning=True):
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
        reasoning_bytes = 0
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
                previous_reference = False
                for part in content:
                    if part.get('type') == 'text' and isinstance(part.get('text'), str): result.append({'type': 'input_text', 'text': ('\n' if previous_reference and part['text'] and not part['text'].startswith('\n') else '') + part['text']})
                    elif part.get('type') == 'image': result.append(image(part))
                    elif part.get('type') == 'tool_reference' and isinstance(part.get('tool_name'), str) and part['tool_name']:
                        result.append({'type': 'input_text', 'text': ('\n' if result and result[-1]['type'] == 'input_text' and result[-1]['text'] and not result[-1]['text'].endswith('\n') else '') + 'Loaded tool: ' + part['tool_name']})
                    else:
                        part_type = ''.join(c for c in str(part.get('type')) if c.isprintable())[:64]
                        raise InvalidRequest('invalid tool result content (' + part_type + ')')
                    previous_reference = part.get('type') == 'tool_reference'
                if b.get('is_error'): result.insert(0, {'type': 'input_text', 'text': 'ERROR: '})
                output = ''.join(p['text'] for p in result) if all(p['type'] == 'input_text' for p in result) else result
                history.append({'type': 'function_call_output', 'call_id': b['tool_use_id'], 'output': output})
            elif kind in ('thinking', 'redacted_thinking'):
                signature = b.get('signature')
                item = decode_reasoning(signature) if keep_reasoning and role == 'assistant' and kind == 'thinking' else None
                if item is not None and reasoning_bytes + len(signature) <= REASONING_RESPONSE_LIMIT:
                    history.append(item)
                    reasoning_bytes += len(signature)
                else:
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
    details = info.get(kind) if isinstance(info, dict) else None
    status = details.get('httpStatusCode') if isinstance(details, dict) else None
    if code == 429 or status == 429 or kind in ('rateLimit', 'usageLimit', 'rateLimitExceeded', 'usageLimitExceeded', 'sessionBudgetExceeded') or message == 'rate limit':
        return 429, 'rate_limit_error'
    if code == 400 or status == 400 or kind in ('badRequest', 'modelNotFound', 'cyberPolicy', 'misalignmentPolicyViolation') or message == 'invalid request':
        return 400, 'invalid_request_error'
    return 500, 'api_error'
