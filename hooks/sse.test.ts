import { test, expect } from 'claude-code/testing'
import { MessagesStream } from './sse.ts'

test('Messages SSE emits tool chunks only after the block stops without delaying text', () => {
  const parser = new MessagesStream('gpt-6-sol')
  const frame = (event: string, data: unknown) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`
  expect(parser.push(frame('message_start', { message: { usage: { input_tokens: 1 } } }) +
    frame('content_block_start', { index: 0, content_block: { type: 'text', text: 'Reading.' } })))
    .toEqual([{ kind: 'text', index: 0, text: 'Reading.' }])
  expect(parser.push(frame('content_block_start', {
    index: 1, content_block: { type: 'tool_use', id: 't1', name: 'Read', input: {} },
  }) + frame('content_block_delta', {
    index: 1, delta: { type: 'input_json_delta', partial_json: '{"file_path":' },
  }))).toEqual([])
  expect(parser.push('')).toEqual([])
  expect(parser.complete).toBe(false)
  expect(parser.push(frame('content_block_delta', {
    index: 1, delta: { type: 'input_json_delta', partial_json: '"/tmp/note"}' },
  }))).toEqual([])
  expect(parser.push(frame('content_block_stop', { index: 1 }))).toEqual([
    { kind: 'tool', index: 1, id: 't1', name: 'Read' },
    { kind: 'input', index: 1, json: '{"file_path":"/tmp/note"}' },
  ])
  expect(parser.push(frame('content_block_start', {
    index: 1, content_block: { type: 'text', text: 'Next.' },
  }) + frame('content_block_stop', { index: 1 }))).toEqual([{ kind: 'text', index: 1, text: 'Next.' }])
  expect(parser.push(frame('content_block_start', {
    index: 1, content_block: { type: 'tool_use', id: 't2', name: 'Read', input: { file_path: '/tmp/other' } },
  }))).toEqual([])
  expect(parser.push(frame('content_block_stop', { index: 1 }))).toEqual([
    { kind: 'tool', index: 1, id: 't2', name: 'Read' },
    { kind: 'input', index: 1, json: '{"file_path":"/tmp/other"}' },
  ])
  expect(parser.push(frame('content_block_start', {
    index: 2, content_block: { type: 'tool_use', id: 't3', name: 'Read', input: {} },
  }) + frame('content_block_delta', {
    index: 2, delta: { type: 'input_json_delta', partial_json: '{"file_path":' },
  }))).toEqual([])
  expect(parser.complete).toBe(false)
  expect(parser.nextIndex).toBe(3)
  expect(parser.firstToolId()).toBe('t2')
})

test('Messages SSE flushes unfinished tool blocks in index order at message_stop', () => {
  const parser = new MessagesStream('gpt-6-sol')
  const frame = (event: string, data: unknown) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`
  expect(parser.push(frame('content_block_start', {
    index: 4, content_block: { type: 'tool_use', id: 't4', name: 'Read', input: { file_path: '/tmp/other' } },
  }) + frame('content_block_start', {
    index: 1, content_block: { type: 'tool_use', id: 't1', name: 'Read', input: {} },
  }) + frame('content_block_delta', {
    index: 1, delta: { type: 'input_json_delta', partial_json: '{"file_path":' },
  }) + frame('content_block_delta', {
    index: 1, delta: { type: 'input_json_delta', partial_json: '"/tmp/note"}' },
  }))).toEqual([])
  expect(parser.complete).toBe(false)
  const chunks = parser.push(frame('message_delta', { delta: { stop_reason: 'tool_use' } }) + frame('message_stop', {}))
  expect(chunks).toEqual([
    { kind: 'tool', index: 1, id: 't1', name: 'Read' },
    { kind: 'input', index: 1, json: '{"file_path":"/tmp/note"}' },
    { kind: 'tool', index: 4, id: 't4', name: 'Read' },
    { kind: 'input', index: 4, json: '{"file_path":"/tmp/other"}' },
    { kind: 'stop', stopReason: 'tool_use', usage: { ...parser.usage } },
  ])
  expect(parser.complete).toBe(true)
  expect(parser.blocks()).toEqual([
    { type: 'tool_use', id: 't4', name: 'Read', input: { file_path: '/tmp/other' } },
    { type: 'tool_use', id: 't1', name: 'Read', input: { file_path: '/tmp/note' } },
  ])
})

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
    ['content_block_start', { index: 8, content_block: { type: 'tool_use', id: 'late', name: 'Write', input: {} } }],
    ['content_block_delta', { index: 0, delta: { type: 'text_delta', text: 'Ignored.' } }],
    ['message_start', { message: { usage: { input_tokens: 999 } } }],
    ['message_delta', { delta: { stop_reason: 'max_tokens' }, usage: { output_tokens: 999 } }],
    ['content_block_stop', { index: 8 }],
    ['error', { error: { type: 'overloaded_error' } }],
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
    { kind: 'input', index: 1, json: '{"file_path":"/tmp/note"}' },
    { kind: 'stop', stopReason: 'tool_use', usage },
  ])
  expect(parser.complete).toBe(true)
  expect(parser.push('event: message_stop\ndata: {}\n\nevent: message_start\ndata: invalid JSON\n\n')).toEqual([])
  expect(parser.error).toBeUndefined()
  expect(parser.nextIndex).toBe(2)
  expect(parser.firstToolId()).toBe('t1')
  expect(parser.blocks()).toEqual([{ type: 'text', text: 'Reading.' },
    { type: 'tool_use', id: 't1', name: 'Read', input: { file_path: '/tmp/note' } }])
  expect(parser.result({ turnId: 'turn1', index: 0 })).toEqual({
    turnId: 'turn1', index: 0, answer: 'Reading.', toolUses: [{ name: 'Read', input: { file_path: '/tmp/note' } }],
    stopReason: 'tool_use', usage,
  })
})
