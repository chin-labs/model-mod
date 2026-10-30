#!/usr/bin/env python3
"""Manual live protocol contract test; consumes account usage and prints no conversation."""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


BRIDGE = Path(__file__).resolve().with_name('bridge.py')


def run(home, codex_bin, model, body):
    result = subprocess.run([sys.executable, str(BRIDGE), 'messages', '--codex-home', home,
                             '--codex-bin', codex_bin, '--model-map', 'test=' + model],
                            input=json.dumps(body), text=True, capture_output=True, timeout=180)
    if result.returncode:
        raise RuntimeError('messages failed: ' + str(result.returncode))
    frames = [json.loads(line[6:]) for line in result.stdout.splitlines() if line.startswith('data: ')]
    delta = next((frame for frame in frames if frame.get('type') == 'message_delta'), None)
    if not delta or 'event: error' in result.stdout:
        raise RuntimeError('messages did not complete')
    return delta['delta']['stop_reason']


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--codex-home', required=True)
    parser.add_argument('--codex-bin', default='codex')
    parser.add_argument('--model', required=True)
    args = parser.parse_args()
    if not os.path.isabs(args.codex_home) or not os.path.isdir(args.codex_home):
        parser.error('account home must be an existing absolute directory')
    base = {'model': 'test(high)', 'stream': True, 'max_tokens': 32}
    text = dict(base, messages=[{'role': 'user', 'content': 'Reply hello.'}])
    history = dict(base, messages=[{'role': 'user', 'content': 'Remember the color teal.'},
                                   {'role': 'assistant', 'content': 'Noted.'},
                                   {'role': 'user', 'content': 'What color?'}])
    tool = dict(base, system='Use the provided tool when asked.',
                tools=[{'name': 'fixture_tool', 'description': 'Returns a fixture value.',
                        'input_schema': {'type': 'object', 'properties': {'value': {'type': 'string'}}}}],
                messages=[{'role': 'user', 'content': 'Call fixture_tool with value teal.'}])
    for label, request, expected in [('text and effort', text, 'end_turn'),
                                      ('history', history, 'end_turn'),
                                      ('tool use', tool, 'tool_use')]:
        actual = run(args.codex_home, args.codex_bin, args.model, request)
        if actual != expected:
            raise RuntimeError(label + ': unexpected stop reason ' + str(actual))
        print(label + ': passed')
    return 0


if __name__ == '__main__':
    sys.exit(main())
