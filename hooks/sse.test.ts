import { test, expect } from 'claude-code/testing'
import { MessagesStream } from './sse.ts'

test('Messages SSE maps text, tool input and usage to turn chunks', () => {
  const events = [
    ['message_start', { message: { usage: { input_tokens: 7 } } }],
    ['ping', {}],
    ['content_block_start', { index: 0, content_block: { type: 'text', text: '' } }],
    ['content_block_delta', { index: 0, delta: { type: 'text_delta', text: 'Reading.' } }],
    ['content_block_start', { index: 1, content_block: { type: 'tool_use', id: 't1', name: 'Read', input: {} } }],
    ['content_block_delta', { index: 1, delta: { type: 'input_json_delta', partial_json: '{"file_path":' } }],
    ['content_block_delta', { index: 1, delta: { type: 'input_json_delta', partial_json: '"/tmp/note"}' } }],
    ['content_block_stop', { index: 1 }],
    ['message_delta', { delta: { stop_reason: 'tool_use' }, usage: { output_tokens: 9 } }],
    ['message_stop', {}],
  ] as const
  const wire = events.map(([event, data], i) => {
    const nl = i % 2 ? '\r\n' : '\n'
    return `event: ${event}${nl}data: ${JSON.stringify(data)}${nl}${nl}`
  }).join('')
  const parser = new MessagesStream('gpt-6-sol')
  const chunks = []
  for (let i = 0; i < wire.length; i += 7) chunks.push(...parser.push(wire.slice(i, i + 7)))
  const usage = { model: 'gpt-6-sol', input_tokens: 7, output_tokens: 9,
    cache_read_input_tokens: 0, cache_creation_input_tokens: 0 }
  expect(chunks).toEqual([
    { kind: 'text', index: 0, text: 'Reading.' },
    { kind: 'tool', index: 1, id: 't1', name: 'Read' },
    { kind: 'input', index: 1, json: '{"file_path":' },
    { kind: 'input', index: 1, json: '"/tmp/note"}' },
    { kind: 'stop', stopReason: 'tool_use', usage },
  ])
  expect(parser.complete).toBe(true)
  expect(parser.blocks()).toEqual([{ type: 'text', text: 'Reading.' },
    { type: 'tool_use', id: 't1', name: 'Read', input: { file_path: '/tmp/note' } }])
  expect(parser.result({ turnId: 'turn1', index: 0 })).toEqual({
    turnId: 'turn1', index: 0, answer: 'Reading.', toolUses: [{ name: 'Read', input: { file_path: '/tmp/note' } }],
    stopReason: 'tool_use', usage,
  })
})
