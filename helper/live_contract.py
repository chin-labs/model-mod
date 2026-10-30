#!/usr/bin/env python3
"""Manual live protocol contract test; consumes account usage and prints no conversation."""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


BRIDGE = Path(__file__).resolve().with_name('bridge.py')


def run(home, codex_bin, model, body, expected_tool=None, no_sleep=False):
    result = subprocess.run([sys.executable, '-E', '-s', str(BRIDGE), 'messages', '--codex-home', home,
                             '--codex-bin', codex_bin, '--model-map', 'test=' + model],
                            input=json.dumps(body), text=True, capture_output=True, timeout=180)
    if result.returncode:
        raise RuntimeError('messages failed: ' + str(result.returncode))
    frames = [json.loads(line[6:]) for line in result.stdout.splitlines() if line.startswith('data: ')]
    delta = next((frame for frame in frames if frame.get('type') == 'message_delta'), None)
    if not delta or 'event: error' in result.stdout:
        raise RuntimeError('messages did not complete')
    if expected_tool and not any(frame.get('content_block', {}).get('type') == 'tool_use' and frame['content_block'].get('name') == expected_tool for frame in frames):
        raise RuntimeError('expected tool use missing')
    if no_sleep:
        text = ''.join(frame.get('delta', {}).get('text', '') for frame in frames if frame.get('type') == 'content_block_delta')
        tools = [frame['content_block']['name'] for frame in frames if frame.get('content_block', {}).get('type') == 'tool_use']
        if not ((delta['delta']['stop_reason'] == 'end_turn' and text.strip() == 'NO_SLEEP' and not tools) or
                (delta['delta']['stop_reason'] == 'tool_use' and tools and all(name in ('fixture_alpha', 'fixture_beta') for name in tools))):
            raise RuntimeError('sleep probe returned an unexpected response')
    return delta['delta']['stop_reason']


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--codex-home', required=True)
    parser.add_argument('--codex-bin', default='codex')
    parser.add_argument('--model', required=True)
    parser.add_argument('--sleep-only', action='store_true')
    args = parser.parse_args()
    if not os.path.isabs(args.codex_home) or not os.path.isdir(args.codex_home):
        parser.error('account home must be an existing absolute directory')
    base = {'model': 'test(high)', 'stream': True, 'max_tokens': 32}
    sleep = dict(base, tools=[{'name': name, 'description': 'A fixture tool.', 'input_schema': {'type': 'object', 'properties': {}}} for name in ('fixture_alpha', 'fixture_beta')],
                 messages=[{'role': 'user', 'content': 'Call the sleep tool for 1 second; if it is unavailable, reply exactly NO_SLEEP.'}])
    sleep_stop = run(args.codex_home, args.codex_bin, args.model, sleep, no_sleep=True)
    print('sleep tool disabled: passed (' + sleep_stop + ')')
    if args.sleep_only:
        return 0
    text = dict(base, messages=[{'role': 'user', 'content': 'Reply hello.'}])
    history = dict(base, messages=[{'role': 'user', 'content': 'Remember the color teal.'},
                                   {'role': 'assistant', 'content': 'Noted.'},
                                   {'role': 'user', 'content': 'What color?'}])
    tool = dict(base, system='Use the provided tool when asked.',
                tools=[{'name': 'fixture_tool', 'description': 'Returns a fixture value.',
                        'input_schema': {'type': 'object', 'properties': {'value': {'type': 'string'}}}}],
                messages=[{'role': 'user', 'content': 'Call fixture_tool with value teal.'}])
    write = dict(base, system='Use the provided Write tool when asked.',
                 tools=[{'name': 'Write', 'description': 'Write a file.', 'input_schema': {'type': 'object', 'properties': {'file_path': {'type': 'string'}, 'content': {'type': 'string'}}, 'required': ['file_path', 'content']}}],
                 messages=[{'role': 'user', 'content': 'Use Write to create a.txt containing x.'}])
    for label, request, expected, expected_tool in [('text and effort', text, 'end_turn', None),
                                      ('history', history, 'end_turn', None),
                                      ('tool use', tool, 'tool_use', None),
                                      ('write tool use', write, 'tool_use', 'Write')]:
        actual = run(args.codex_home, args.codex_bin, args.model, request, expected_tool)
        if actual != expected:
            raise RuntimeError(label + ': unexpected stop reason ' + str(actual))
        print(label + ': passed')
    return 0


if __name__ == '__main__':
    sys.exit(main())
