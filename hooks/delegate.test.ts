import { test, expect } from 'claude-code/testing'
import type { EngineInterface } from 'claude-code'
import { delegate, formatOutput, parseDelegate, backgroundCommand, pollJob, transfer } from './delegate.ts'

test('delegate parser handles quotes, separator, repeats and unknown flags', () => {
  expect(parseDelegate('review', `--base 'feature/test' --adversarial -- "focus text" 'and more'`)).toEqual({ base: 'feature/test', adversarial: true, text: `"focus text" 'and more'` })
  expect(parseDelegate('rescue', `--model "gpt test" -- --account literal`)).toEqual({ model: 'gpt test', text: '--account literal' })
  expect(() => parseDelegate('review', '--base a --base b')).toThrow()
  expect(() => parseDelegate('review', '--unknown')).toThrow()
  expect(parseDelegate('rescue', `-- 'unterminated`).text).toBe(`'unterminated`)
  expect(() => parseDelegate('rescue', `--model 'unterminated`)).toThrow()
})

test('write is rescue-only and requires explicit confirmation', async () => {
  expect(parseDelegate('rescue', '--write -- task')).toEqual({ write: true, text: 'task' })
  expect(() => parseDelegate('rescue', '--write --write -- task')).toThrow()
  expect(() => parseDelegate('review', '--write')).toThrow()
  const config = { codex: new Map([['test/chat', { account: 'test', model: 'chat', directory: '/accounts/test' }]]), accountsDir: '/accounts' }
  for (const answer of ['Cancel', '', 'throw', 'no-ui', 'Allow write']) {
    let spawned = 0, submitted = 0, input: any
    const $ = { plugin: { root: '/plugin' }, session: { model: async () => 'test/chat', cwd: async () => '/repo' },
      ui: answer === 'no-ui' ? undefined : { ask: async () => { if (answer === 'throw') throw new Error('dismissed'); return answer } },
      fs: { stat: async () => ({ kind: 'dir', realPath: '/repo' }) },
      process: { run: async () => { submitted++; throw new Error('unexpected run') }, spawn: (args: { input: string }) => { spawned++; input = JSON.parse(args.input); return { async *[Symbol.asyncIterator]() { yield { stream: 'stdout', text: '{"text":"ok"}' } } } } } } as unknown as EngineInterface
    const result = await delegate($, 'rescue', '--write -- task', config, new AbortController().signal)
    expect((await delegate($, 'rescue', '--write -- task', config, new AbortController().signal, false)).text).toContain('interactive')
    if (answer === 'Allow write') { expect(spawned).toBe(1); expect(input.writeRoot).toBe('/repo'); expect(input.options.write).toBe(true) }
    else { expect(spawned).toBe(0); expect(submitted).toBe(0); expect(result.text).toContain('Omit --write') }
  }
})

test('write rejects a misleading working-directory display before asking', async () => {
  let asked = 0
  const $ = { plugin: { root: '/plugin' }, session: { model: async () => 'test/chat', cwd: async () => '/repo' },
    fs: { stat: async () => ({ kind: 'dir', realPath: '/repo\nother' }) }, ui: { ask: async () => { asked++; return 'Allow write' } } } as unknown as EngineInterface
  const config = { codex: new Map([['test/chat', { account: 'test', model: 'chat', directory: '/accounts/test' }]]), accountsDir: '/accounts' }
  const result = await delegate($, 'rescue', '--write -- task', config, new AbortController().signal)
  expect(asked).toBe(0); expect(result.text).toContain('not allowed')
})

test('background write submits only after confirmation with the confirmed root', async () => {
  const config = { codex: new Map([['test/chat', { account: 'test', model: 'chat', directory: '/accounts/test' }]]), accountsDir: '/accounts' }
  for (const answer of ['Cancel', 'Allow write']) {
    const calls: any[] = []
    const $ = { plugin: { root: '/plugin' }, session: { model: async () => 'test/chat', cwd: async () => '/repo-link' },
      ui: { ask: async () => answer }, fs: { stat: async () => ({ kind: 'dir', realPath: '/repo' }) }, clock: { after: () => {} }, process: { run: async (_argv: unknown, opts: { stdin: string }) => {
        calls.push(JSON.parse(opts.stdin))
        return { stdout: JSON.stringify({ ok: true, job: { ...job, id: 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb' } }) }
      } } } as unknown as EngineInterface
    const result = await delegate($, 'rescue', '--write --background -- task', config, new AbortController().signal)
    if (answer === 'Cancel') { expect(calls.length).toBe(0); expect(result.text).toContain('Omit --write') }
    else { expect(calls.length).toBe(1); expect(calls[0].request.writeRoot).toBe('/repo'); expect(calls[0].request.options.write).toBe(true) }
  }
})

test('transfer requires confirmation and accepts only account selection', async () => {
  const config = { codex: new Map([['test/chat', { account: 'test', model: 'chat', directory: '/accounts/test' }]]), accountsDir: '/accounts' }
  for (const answer of ['Cancel', 'throw', 'Import session']) {
    let count = 0, input: any
    const $ = { plugin: { root: '/plugin' }, session: { model: async () => 'test/chat', cwd: async () => '/repo' },
      ui: { ask: async () => { if (answer === 'throw') throw new Error('dismissed'); return answer } },
      process: { spawn: (args: { input: string }) => { count++; input = JSON.parse(args.input); return { async *[Symbol.asyncIterator]() { yield { stream: 'stdout', text: '{"text":"codex resume test"}' } } } } } } as unknown as EngineInterface
    const result = await transfer($, '', config, '/fake-transcript', new AbortController().signal, true)
    if (answer === 'Import session') { expect(count).toBe(1); expect(input.transcript).toBe('/fake-transcript'); expect(input.kind).toBe('transfer') }
    else { expect(count).toBe(0); expect(result.text).toContain('no transcript was imported') }
    expect((await transfer($, '--model chat', config, '/fake-transcript', new AbortController().signal, true)).text).toContain('only --account')
    expect((await transfer($, '', config, '/fake-transcript', new AbortController().signal, false)).text).toContain('interactive')
  }
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

test('background parser preserves foreground behavior and rejects duplicate flag', () => {
  expect(parseDelegate('rescue', '--background -- task')).toEqual({ background: true, text: 'task' })
  expect(parseDelegate('rescue', '-- task')).toEqual({ text: 'task' })
  expect(() => parseDelegate('rescue', '--background --background -- task')).toThrow()
})

const job = { id: 'abcdef0123456789abcdef0123456789', state: 'completed', account: 'test', model: 'chat', kind: 'rescue', createdAt: 1 }
const config = { codex: new Map([['test/chat', { account: 'test', model: 'chat', directory: '/accounts/test' }]]), accountsDir: '/accounts' }

test('background submission sends client account validation and exposes client errors', async () => {
  let input: any
  const $ = { plugin: { root: '/plugin' }, session: { model: async () => 'test/chat', cwd: async () => '/repo' },
    process: { run: async (_argv: unknown, opts: { stdin: string }) => { input = JSON.parse(opts.stdin); return { stdout: JSON.stringify({ ok: false, error: 'Background jobs require the default accounts directory; use foreground delegation for a custom directory.' }) } } } } as unknown as EngineInterface
  const result = await delegate($, 'rescue', '--background -- hello', config, new AbortController().signal)
  expect(input.request.accountsDir).toBe('/accounts')
  expect(input.request.directory).toBe('/accounts/test')
  expect(input.request.options).toEqual({ text: 'hello' })
  expect(result.text).toContain('Background jobs require the default accounts directory')
})

test('background commands validate IDs and sanitize display and errors', async () => {
  let response: unknown = { ok: false, error: 'Ambiguous job ID; provide more characters.' }
  const $ = { plugin: { root: '/plugin' }, session: { cwd: async () => '/repo' }, process: { run: async () => ({ stdout: JSON.stringify(response) }) } } as unknown as EngineInterface
  expect((await backgroundCommand($, 'result', 'xyz!', config)).text).toContain('Invalid job ID')
  expect((await backgroundCommand($, 'result', 'abc', config)).text).toContain('Invalid job ID')
  expect((await backgroundCommand($, 'result', 'abcd', config)).text).toContain('Ambiguous job ID')
  response = { ok: false, error: 'Background broker unavailable; start a new session to launch it.' }
  expect((await backgroundCommand($, 'jobs', '', config)).text).toContain('restart Claude Code')
  response = { ok: false, error: 'Background jobs are not supported on Windows.' }
  expect((await backgroundCommand($, 'jobs', '', config)).text).toContain('not supported on Windows')
  response = { ok: true, job: { ...job, account: '\x1b[31mtest\x1b[0m', model: 'chat\x01' }, text: '\x1b[31moutput\x1b[0m\x01' }
  const result = (await backgroundCommand($, 'result', 'abcd', config)).text
  expect(result).toContain('Codex output is unverified')
  expect(result).not.toContain('\x1b')
  expect(result).not.toContain('\x01')
})

test('notification polling deduplicates, stops on terminal or error and times out', async () => {
  let callbacks: (() => void)[] = [], calls = 0, notices: string[] = [], state = 'running', fail = false
  const $ = { plugin: { root: '/plugin' }, clock: { after: (_ms: number, cb: () => void) => { callbacks.push(cb) } },
    ui: { toast: async (message: string) => { notices.push(message) } },
    process: { run: async () => { calls++; if (fail) throw new Error('failure'); return { stdout: JSON.stringify({ ok: true, job: { ...job, state } }) } } } } as unknown as EngineInterface
  const step = async () => { callbacks.shift()?.(); for (let i = 0; i < 12; i++) await Promise.resolve() }
  pollJob($, config, job.id); pollJob($, config, job.id)
  expect(callbacks.length).toBe(1)
  await step(); state = 'completed'; await step()
  expect(calls).toBe(2); expect(notices.length).toBe(1); expect(callbacks.length).toBe(0)
  fail = true; pollJob($, config, job.id); await step()
  expect(notices.length).toBe(1); expect(callbacks.length).toBe(0)
  fail = false; state = 'running'; calls = 0; pollJob($, config, job.id)
  for (let i = 0; i < 140; i++) await step()
  expect(calls).toBe(140); expect(callbacks.length).toBe(0)
})

test('successful background submission starts a job without spawning foreground helper', async () => {
  let timer = 0
  const $ = { plugin: { root: '/plugin' }, session: { model: async () => 'test/chat', cwd: async () => '/repo' },
    clock: { after: () => { timer++ } }, process: { run: async () => ({ stdout: JSON.stringify({ ok: true, job }) }), spawn: () => { throw new Error('foreground used') } } } as unknown as EngineInterface
  const result = await delegate($, 'rescue', '--background -- hello', config, new AbortController().signal)
  expect(result.text).toContain('Started Codex job abcdef012345')
  expect(timer).toBe(1)
})


test('jobs can list all while clearing only the current workspace', async () => {
  let payload: any
  const $ = { plugin: { root: '/plugin' }, session: { cwd: async () => '/repo' }, process: { run: async (_argv: unknown, opts: { stdin: string }) => { payload = JSON.parse(opts.stdin); return { stdout: '{"ok":true,"jobs":[]}' } } } } as unknown as EngineInterface
  await backgroundCommand($, 'jobs', '--all --clear', config)
  expect(payload).toEqual({ cwd: '/repo', all: true, clear: true })
})
