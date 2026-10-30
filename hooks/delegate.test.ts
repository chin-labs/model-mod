import { test, expect } from 'claude-code/testing'
import type { EngineInterface } from 'claude-code'
import { delegate, formatOutput, parseDelegate } from './delegate.ts'

test('delegate parser handles quotes, separator, repeats and unknown flags', () => {
  expect(parseDelegate('review', `--base 'feature/test' --adversarial -- "focus text" 'and more'`)).toEqual({ base: 'feature/test', adversarial: true, text: `"focus text" 'and more'` })
  expect(parseDelegate('rescue', `--model "gpt test" -- --account literal`)).toEqual({ model: 'gpt test', text: '--account literal' })
  expect(() => parseDelegate('review', '--base a --base b')).toThrow()
  expect(() => parseDelegate('review', '--unknown')).toThrow()
  expect(parseDelegate('rescue', `-- 'unterminated`).text).toBe(`'unterminated`)
  expect(() => parseDelegate('rescue', `--model 'unterminated`)).toThrow()
})

test('delegate output has a warning and strips terminal controls', () => {
  const text = formatOutput('test', 'chat', '\x1b[31mhello\x1b[0m\x01')
  expect(text).toContain('no file writes; read-only commands may still run')
  expect(text).toContain('Codex output is unverified')
  expect(text).not.toContain('\x1b')
  expect(text).not.toContain('\x01')
})

test('delegate abort closes the foreground helper', async () => {
  const controller = new AbortController()
  let closed = false, wake: () => void = () => {}, ready: () => void = () => {}
  const started = new Promise<void>(resolve => { ready = resolve })
  const child = {
    next: () => { ready(); return new Promise<{ done: true; value: { code: null; signal: string } }>(resolve => { wake = () => resolve({ done: true, value: { code: null, signal: 'SIGTERM' } }) }) },
    return: async () => { closed = true; wake(); return { done: true as const, value: { code: null, signal: 'SIGTERM' } } },
    [Symbol.asyncIterator]() { return this },
  }
  const $ = { plugin: { root: '/plugin' }, session: { model: async () => 'test/chat', cwd: async () => '/repo' }, process: { spawn: () => child } } as unknown as EngineInterface
  const task = delegate($, 'rescue', '-- test', { codex: new Map([['test/chat', { account: 'test', model: 'chat', directory: '/accounts/test' }]]), accountsDir: '/accounts' }, controller.signal)
  await started
  controller.abort()
  const result = await task
  expect(closed).toBe(true)
  expect(result.text).toContain('cancelled')
  expect('context' in result).toBe(false)
})


test('delegate passes the exact task text to the helper', async () => {
  const tasks = ["why doesn't this work", String.raw`explain regex \d+ in C:\tmp and "quoted"  two  spaces`, 'line one\n  line two']
  for (const text of tasks) {
    let input = ''
    const $ = { plugin: { root: '/plugin' }, session: { model: async () => 'test/chat', cwd: async () => '/repo' },
      process: { spawn: (args: { input: string }) => { input = args.input; return { async *[Symbol.asyncIterator]() { yield { stream: 'stdout', text: '{"text":"ok"}' } } } } } } as unknown as EngineInterface
    await delegate($, 'rescue', '-- ' + text, { codex: new Map([['test/chat', { account: 'test', model: 'chat', directory: '/accounts/test' }]]), accountsDir: '/accounts' }, new AbortController().signal)
    expect((JSON.parse(input) as { options: { text: string } }).options.text).toBe(text)
  }
})
