import { test, expect, mock } from 'claude-code/testing'
import type { Engine } from 'claude-code/testing'
import type { On } from 'claude-code'

// What the compliance rules in docs/COMPLIANCE.md turn on: a model the bridge does not own always goes down the
// chain (`next`), a bridge model never does, and the mod stays inert on a config that names a subscription host or a
// Claude model ID. Each test builds its own world beneath the plugin; nothing here reaches a network.
const CONFIG_PATH = '/cfg/model-mod.json'
const LOCAL = 'gpt-6-sol'
const PROMPTS_DIR = '/cfg/default-prompts'
const baseConfig = {
  baseUrl: 'http://127.0.0.1:9999', headerFile: '/cfg/headers', toolsFile: '/cfg/tools.json',
  models: [LOCAL], maxTokens: 32000, effortMode: 'none', promptsDir: PROMPTS_DIR,
}

type RunReply = { exitCode: number; stdout: string; isStdoutTruncated?: boolean }
type SpawnReply = { stdout: string | readonly string[]; stderr?: string | readonly string[]; code: number }
type World = { system: string; spawned: { argv: readonly string[]; input?: string; env?: Record<string, string> }[]; ran: (readonly string[])[]
  ranEnv: (Record<string, string> | undefined)[]; reached: string[]; envSet: [string, string | undefined][]; messagesRead: number; failEnvSets: number; failEnvName?: string
  // The upstream's model list (null: unreachable), what the store holds, the picker rows of the settings, the requests
  // `$.http.fetch` made (the authorization header is reduced to its first 6 characters).
  answers: (string | null)[]; questions: { question: string; header: string; labels: string[]; multiSelect: boolean }[];
  scopes: Record<string, Record<string, unknown>>; files: Record<string, string>; writes: string[]; saved: { key: string; value: unknown }[]; registered: string[];
  toolDescriptions: Record<string, string>; httpStatus?: number; httpStatuses?: number[]; httpBody?: string; configSet?: (key: string) => { deny: string } | undefined; switchEnv: (string | undefined)[];
  models: string[] | null; store: Record<string, unknown>; picker: unknown[]; fetched: { url: string; auth?: string }[]
  // The session's current model (`/model` runs change it), the `/model` arguments run, the rate-limit windows the last
  // response reported and the clock.
  usage?: Record<string, unknown>; agents: { name: string; model?: string }[]; current: string; modelRuns: string[]; limits: { kind: string; percentUsed: number; resetsAt?: string }[]; clock: ReturnType<typeof mock.clock> }

// Answers everything the mod reads. `reached` lists the events that fell through to the test's own bottom hooks,
// which stand for the engine (the subscription path).
function world(on: On, config: Record<string, unknown> | null, model: string, spawn: SpawnReply | SpawnReply[],
  run?: RunReply | ((argv: readonly string[], stdin?: string) => RunReply), env: Record<string, string> = {}): World {
  const w: World = { system: 'Linux', spawned: [], ran: [], ranEnv: [], reached: [], envSet: [], messagesRead: 0, failEnvSets: 0,
    switchEnv: [], toolDescriptions: {}, answers: ['Keep (recommended)', 'All (recommended)'], questions: [], scopes: {}, files: {}, writes: [], saved: [], registered: [], models: null, store: {}, picker: [], fetched: [], current: model, agents: [], modelRuns: [], limits: [], clock: undefined as never }
  // The test engine has no plugin.root; supply prompt files explicitly instead of built-in text.
  for (const name of ['compact', 'title', 'subagent-note', 'worker']) w.files[PROMPTS_DIR + '/' + name + '.md'] = 'TEST ' + name + ' prompt\n'
  w.clock = mock.clock(on)
  mock.env(on, { HOME: '/fake-home', CLAUDE_CONFIG_DIR: '/fake-config', ...(config ? { MODEL_MOD_CONFIG: CONFIG_PATH } : {}), ...env })
  on('http.fetch', async (_$, e) => {
    w.fetched.push({ url: e.url, auth: e.init?.headers?.authorization?.slice(0, 6) })
    const status = w.httpStatuses?.shift() ?? w.httpStatus
    if (status !== undefined) return { value: { status, ok: status === 200, headers: {}, text: w.httpBody ?? '{}' } }
    if (w.models === null) throw new Error('unreachable')
    return { value: { status: 200, ok: true, headers: {}, text: JSON.stringify({ data: w.models.map(id => ({ id })) }) } }
  })
  on('store.get', async (_$, e) => ({ value: w.store[e.key] }))
  on('store.set', async (_$, e) => { w.store[e.key] = e.value; return { value: undefined } })
  on('settings.read', async (_$, e) => {
    if (!e.source) return { value: w.picker.length ? { modelPicker: { options: w.picker } } : {} }
    return { value: w.scopes[e.source] ?? {} }
  })
  on('session.cwd', async () => ({ value: '/work' }))
  on('fs.exists', async (_$, e) => ({ value: e.path in w.files }))
  on('fs.write', async (_$, e) => { w.files[e.path] = e.text; w.writes.push(e.path); return { value: undefined } })
  on('config.list', async () => ({ value: [{ key: 'model', label: 'Model', kind: 'choice' as const, value: 'Default', options: ['default', 'sonnet', 'opus', 'haiku', 'best'], provider: { plugin: 'engine', tier: 'core' as const }, isLocked: false }, ...['baseUrl', 'models'].map(field => ({ key: 'model-mod.' + field, label: field,
    kind: 'text' as const, value: '', provider: { plugin: 'model-mod', tier: 'user' as const }, isLocked: false }))] }))
  on('config.set', async (_$, e) => {
    const refused = w.configSet?.(e.key)
    if (refused) return refused
    w.saved.push({ key: e.key, value: e.value }); return { value: e.value }
  })
  on('tool.call', { tool: 'AskUserQuestion' }, async (_$, e) => {
    const q = e.questions[0]!
    w.questions.push({ question: q.question, header: q.header, labels: q.options.map(o => o.label), multiSelect: q.multiSelect })
    const answer = w.answers.shift()
    if (answer === null || answer === undefined) return { deny: 'dismissed' }
    return { result: { questions: e.questions, answers: { [q.question]: answer } } }
  })
  on('fs.read', async (_$, e, next) => {
    if (e.path in w.files) return { value: w.files[e.path]! }
    if (config && e.path === CONFIG_PATH) return { value: JSON.stringify(config) }
    if (e.path === baseConfig.toolsFile) return { value: JSON.stringify({ tools: [] }) }
    return next(e)
  })
  on('session.model', async () => ({ value: w.current }))
  on('session.usage', async () => ({ value: { startedAt: 0, context: { window: 1_000_000 }, rateLimits: w.limits, ...w.usage } as never }))
  on('session.messages', async () => {
    w.messagesRead++
    return { value: [{ role: 'user', content: [{ type: 'text', text: 'hi' }] }] }
  })
  on('tool.list', async () => ({ value: [] }))
  on('env.set', async (_$, e) => {
    if (w.failEnvName === e.name) { w.failEnvName = undefined; throw new Error('env write failed') }
    if (w.failEnvSets > 0) { w.failEnvSets--; throw new Error('env write failed') }
    w.envSet.push([e.name, e.value])
    return { value: undefined }
  })
  on('prompt.compose', async () => ({ sections: [{ id: 'intro', text: 'sys', scope: 'session' as const }] }))
  on('process.spawn', async function* (_$, e) {
    w.spawned.push({ argv: e.argv, input: e.input, env: e.env })
    const reply = Array.isArray(spawn) ? spawn[Math.min(w.spawned.length - 1, spawn.length - 1)]! : spawn
    for (const text of typeof reply.stdout === 'string' ? [reply.stdout] : reply.stdout) if (text) yield { stream: 'stdout' as const, text }
    for (const text of typeof reply.stderr === 'string' ? [reply.stderr] : reply.stderr ?? []) yield { stream: 'stderr' as const, text }
    return { value: { code: reply.code, signal: null } }
  })
  on('process.run', async (_$, e) => {
    w.ran.push(e.argv)
    w.ranEnv.push(e.init?.env)
    const reply: RunReply | undefined = e.argv[0] === 'uname' ? { exitCode: 0, stdout: w.system + '\n' } : typeof run === 'function' ? run(e.argv, e.init?.stdin) : run
    return { value: { exitCode: reply?.exitCode ?? 1, stdout: reply?.stdout ?? '', stderr: '', isStdoutTruncated: reply?.isStdoutTruncated ?? false, isStderrTruncated: false } }
  })
  on('turn.step', async function* (_$, e) {
    w.reached.push('turn.step')
    return { turnId: e.turnId, index: e.index, answer: 'engine', toolUses: [], stopReason: 'end_turn',
      usage: { model: e.model, input_tokens: 0, output_tokens: 0, cache_read_input_tokens: 0, cache_creation_input_tokens: 0 } }
  })
  on('session.compact', async (_$, e) => { w.reached.push('session.compact'); return { skip: 'engine' } })
  on('turn.complete', async (_$, e) => ({ text: e.answer }))
  on('session.start', async (_$, e) => ({ cwd: '/work' }))
  on('classic.PostModelSwitch', async () => ({}))
  on('command.register', async (_$, e) => { w.registered.push(e.name); return { value: { command: e.name } } })
  on('tool.register', async (_$, e) => { w.toolDescriptions[e.name] = e.description; return { value: { tool: e.name } } })
  on('agent.register', async (_$, e) => { w.agents.push({ name: e.name, model: e.model }); return { value: { agent: 'model-mod:' + e.name } } })
  on('command.run', async (_$, e) => {
    if (e.command === 'model') { w.switchEnv.push(w.envSet.filter(([name]) => name === 'ANTHROPIC_CUSTOM_MODEL_OPTION').at(-1)?.[1]); w.modelRuns.push(e.args); w.current = e.args; return { text: `Set model to ${e.args}` } }
    w.reached.push('command.run')
    return { text: 'engine' }
  })
  return w
}


// Drives a streaming step to its end: the chunks it yielded and the result it returned.
async function drain<C extends { kind: string }, R>(stream: AsyncGenerator<C, R>): Promise<{ chunks: C[]; result: R }> {
  const chunks: C[] = []
  for (;;) {
    const next = await stream.next()
    if (next.done) return { chunks, result: next.value }
    chunks.push(next.value)
  }
}

const STEP = (model: string) => ({ turnId: 't', index: 0, model, messageCount: 1 }) as never
const SSE_OK = [
  ['message_start', { message: { usage: { input_tokens: 3 } } }],
  ['content_block_start', { index: 0, content_block: { type: 'text', text: '' } }],
  ['content_block_delta', { index: 0, delta: { type: 'text_delta', text: 'local answer' } }],
  ['content_block_stop', { index: 0 }],
  ['message_delta', { delta: { stop_reason: 'end_turn' }, usage: { output_tokens: 2 } }],
  ['message_stop', {}],
].map(([event, data]) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`).join('')

test('a model the bridge does not own goes down the chain and nothing is spawned', async ($, on) => {
  const w = world(on, { ...baseConfig, imageModel: 'gpt-image-2' }, 'claude-sonnet-5-5', { stdout: SSE_OK, code: 0 })
  await $.session.start({ cwd: '/work' } as never)
  for (const name of ['web_search', 'web_fetch', 'generate_image', 'tool_search']) {
    expect(w.toolDescriptions[name]).toContain('Only usable while a local model is selected')
  }
  for (const [name, builtin] of [['web_search', 'WebSearch'], ['web_fetch', 'WebFetch']] as const) {
    expect(w.toolDescriptions[name]).toContain(`where it replaces the built-in ${builtin}.`)
    expect(w.toolDescriptions[name]).toContain(`With any other model use the built-in ${builtin} instead.`)
  }
  for (const name of ['generate_image', 'tool_search']) {
    const outcome = await $.tool.call({ tool: `mcp__model-mod__${name}` } as never).then(
      value => JSON.stringify(value), error => String(error instanceof Error ? error.message : error))
    expect(outcome).toContain(`${name} is only available while a local model is selected. Select a local model to use this tool.`)
  }
  const { chunks, result } = await drain($.turn.step(STEP('claude-sonnet-5-5')))
  expect(chunks).toEqual([])
  expect(result.answer).toBe('engine')
  expect(w.reached).toEqual(['turn.step'])
  expect(w.spawned).toEqual([])
  expect(w.ran).toEqual([])
})

test('a bridge model is answered by the upstream and never reaches the chain', async ($, on) => {
  const w = world(on, baseConfig, LOCAL, { stdout: SSE_OK, code: 0 })
  const { chunks, result } = await drain($.turn.step(STEP(LOCAL)))
  expect(result.answer).toBe('local answer')
  expect(chunks.map(c => c.kind)).toEqual(['text', 'stop'])
  expect(w.reached).toEqual([])
  expect(w.spawned.length).toBe(1)
  const sent = w.spawned[0]!
  expect(sent.argv).toContain('http://127.0.0.1:9999/v1/messages')
  // Only the user's own header file is passed; no subscription credential is read or forwarded.
  expect(sent.argv.filter(a => a.startsWith('@') && a !== '@-')).toEqual(['@/cfg/headers'])
  expect(JSON.parse(sent.input ?? '{}').model).toBe(LOCAL)
})

test('an upstream failure ends the turn with an error text and never falls back to the chain', async ($, on) => {
  const body = JSON.stringify({ type: 'error', error: { type: 'authentication_error', message: 'x' } })
  const w = world(on, baseConfig, LOCAL, { stdout: body, code: 22 })
  const stream = $.turn.step(STEP(LOCAL))
  const texts: string[] = []
  for await (const chunk of stream) if (chunk.kind === 'text') texts.push(chunk.text)
  expect(texts.join('')).toMatch(/^model-mod: HTTP error \(authentication_error\)/)
  expect(w.spawned.length).toBe(1)
  expect(w.reached).toEqual([])
})

test('502/503/504 retry without a known error type and can eventually succeed', async ($, on) => {
  const w = world(on, baseConfig, LOCAL, [
    { stdout: '{"error":{"type":"unknown_error"}}', stderr: ['\nmodel-mod-ht', 'tp:503\n'], code: 22 },
    { stdout: '', stderr: '\nmodel-mod-http:502\n', code: 22 },
    { stdout: '{"error":{"type":"unknown_error"}}', stderr: '\nmodel-mod-http:504\n', code: 22 },
    { stdout: SSE_OK, code: 0 },
  ])
  const statuses: (string | undefined)[] = []
  on('ui.status', (_$, e) => { statuses.push(e.text); return { value: undefined } })
  const { chunks, result } = await drain($.turn.step(STEP(LOCAL)))
  expect(result.answer).toBe('local answer')
  expect(chunks.map(c => c.kind)).toEqual(['text', 'stop'])
  expect(w.spawned.length).toBe(4)
  expect(w.ran.filter(argv => argv[0] === 'sleep')).toEqual([
    ['sleep', '2'], ['sleep', '3'], ['sleep', '3'],
    ['sleep', '3'], ['sleep', '3'], ['sleep', '3'], ['sleep', '3'], ['sleep', '3'],
  ])
  expect(statuses).toEqual([1, 2, 3].map(n => `model-mod: HTTP error; retrying (${n}/3)`))
  expect(w.reached).toEqual([])
})

test('503 with an unknown error type stops after three retries with a visible error', async ($, on) => {
  const w = world(on, baseConfig, LOCAL, {
    stdout: '{"error":{"type":"unknown_error","message":"untrusted message"}}',
    stderr: '\nmodel-mod-http:503\n', code: 22,
  })
  const { chunks, result } = await drain($.turn.step(STEP(LOCAL)))
  expect(w.spawned.length).toBe(4)
  expect(result.answer).toBe('model-mod: HTTP error.')
  expect(chunks.filter(c => c.kind === 'text').map(c => c.text).join('')).toBe(result.answer)
  expect(w.reached).toEqual([])
})

test('transient SSE errors before output share the same retry budget and status messages', async ($, on) => {
  const w = world(on, baseConfig, LOCAL, [
    ...['overloaded_error', 'rate_limit_error', 'api_error'].map(type => ({
      stdout: `event: error\ndata: ${JSON.stringify({ type: 'error', error: { type, message: 'untrusted message' } })}\n\n`, code: 0,
    })),
    { stdout: SSE_OK, code: 0 },
  ])
  const statuses: (string | undefined)[] = []
  on('ui.status', (_$, e) => { statuses.push(e.text); return { value: undefined } })
  const { chunks, result } = await drain($.turn.step(STEP(LOCAL)))
  expect(w.spawned.length).toBe(4)
  expect(result.answer).toBe('local answer')
  expect(chunks.map(c => c.kind)).toEqual(['text', 'stop'])
  expect(statuses).toEqual(['overloaded_error', 'rate_limit_error', 'api_error']
    .map((type, i) => `model-mod: HTTP error (${type}); retrying (${i + 1}/3)`))
  expect(w.reached).toEqual([])
})

test('SSE errors after output never retry even when content and error arrive in one piece', async ($, on) => {
  const partial = 'event: content_block_delta\ndata: {"index":0,"delta":{"type":"text_delta","text":"partial"}}\n\n'
  const error = 'event: error\ndata: {"type":"error","error":{"type":"overloaded_error"}}\n\n'
  const reply: SpawnReply = { stdout: partial + error, code: 0 }
  const w = world(on, baseConfig, LOCAL, reply)
  const statuses: (string | undefined)[] = []
  on('ui.status', (_$, e) => { statuses.push(e.text); return { value: undefined } })
  for (const stdout of [partial + error, [partial, error]]) {
    reply.stdout = stdout
    const { chunks, result } = await drain($.turn.step(STEP(LOCAL)))
    expect(chunks.filter(c => c.kind === 'text').map(c => c.text)).toEqual([
      'partial', 'model-mod: HTTP error (overloaded_error).',
    ])
    expect(result.answer).toBe('model-mod: HTTP error (overloaded_error).')
  }
  expect(w.spawned.length).toBe(2)
  expect(w.ran.filter(argv => argv[0] === 'sleep')).toEqual([])
  expect(statuses).toEqual([])
  expect(w.reached).toEqual([])
})

test('a config that lists a Claude model ID leaves the mod inert', async ($, on) => {
  const w = world(on, { ...baseConfig, models: ['claude-sonnet-5-5'] }, 'claude-sonnet-5-5', { stdout: SSE_OK, code: 0 })
  const stream = $.turn.step(STEP('claude-sonnet-5-5'))
  for await (const _chunk of stream) { /* none expected */ }
  expect(w.reached).toEqual(['turn.step'])
  expect(w.spawned).toEqual([])
})

test('a config whose upstream is the subscription API leaves the mod inert', async ($, on) => {
  const w = world(on, { ...baseConfig, baseUrl: 'https://api.anthropic.com' }, LOCAL, { stdout: SSE_OK, code: 0 })
  const stream = $.turn.step(STEP(LOCAL))
  for await (const _chunk of stream) { /* none expected */ }
  expect(w.reached).toEqual(['turn.step'])
  expect(w.spawned).toEqual([])
})

test('compaction of a bridge model is summarised upstream and never reaches the chain, even when that fails', async ($, on) => {
  let sent: { system: string; messages: { content: { text: string }[] }[] } | undefined
  const failed = world(on, { ...baseConfig, promptsDir: '/cfg/prompts' }, LOCAL, { stdout: '', code: 0 }, (_argv, stdin) => {
    sent = JSON.parse(stdin!)
    return { exitCode: 22, stdout: '' }
  })
  const customPath = '/cfg/prompts/compact.md'
  failed.files[customPath] = 'CUSTOM COMPACT instructions\n\n'
  const prior = 'This session is being continued from a previous conversation that ran out of context.\n\nEarly fact: COBALT_OTTER_731. Pending: read notes.txt.'
  const answer = await $.session.compact({ trigger: 'auto', messages: [{ role: 'user', text: prior, toolUses: [] }] } as never)
  expect(sent?.system).toBe('CUSTOM COMPACT instructions')
  expect(sent?.messages[0]?.content[0]?.text).toContain(prior)
  expect('skip' in answer && answer.skip).toMatch(/^model-mod:/)
  failed.files[customPath] = 'changed without refresh'
  await $.session.compact({ trigger: 'manual', messages: [] } as never)
  expect(sent?.system).toBe('CUSTOM COMPACT instructions')
  const refresh = () => $.command.run({ command: 'model-mod:refresh', args: '', origin: { kind: 'composer' } } as never)
  // Missing/empty/NUL/oversized files disable compaction; refresh re-reads the cached config's prompts.
  for (const invalid of [undefined, '', ' \n', 'bad\0prompt', 'x'.repeat(8001)]) {
    if (invalid === undefined) delete failed.files[customPath]
    else failed.files[customPath] = invalid
    const refreshed = await refresh()
    expect(refreshed.text).toContain('missing=compact')
    const missing = await $.session.compact({ trigger: 'manual', messages: [{ role: 'user', text: prior, toolUses: [] }] } as never)
    expect(missing).toEqual({ skip: 'model-mod: compaction prompt file missing' })
  }
  expect(sent?.system).toBe('CUSTOM COMPACT instructions')
  expect('skip' in answer && answer.skip).toMatch(/^model-mod:/)
  expect(failed.reached).toEqual([])
})

test('compaction of a subscription model goes down the chain', async ($, on) => {
  const w = world(on, baseConfig, 'claude-sonnet-5-5', { stdout: '', code: 0 })
  await $.session.compact({ trigger: 'manual', messages: [{ role: 'user', text: 'hello', toolUses: [] }] } as never)
  expect(w.reached).toEqual(['session.compact'])
  expect(w.ran).toEqual([])
})

test('/context and /btw are answered locally for a bridge model and go down the chain otherwise', async ($, on) => {
  let sent: { model: string; messages: { content: { text?: string }[] }[]; tools?: unknown; system: string } | undefined
  let failed = false
  const w = world(on, baseConfig, LOCAL, { stdout: '', code: 0 }, (_argv, stdin) => {
    sent = JSON.parse(stdin!)
    return { exitCode: failed ? 22 : 0, stdout: JSON.stringify({ content: [{ type: 'text', text: 'side answer' }] }) }
  })
  const sq = (categoryName: string, isFilled: boolean, squareFullness: number) => ({ color: 'x', isFilled, categoryName, tokens: 1, percentage: 1, squareFullness })
  w.usage = { context: { window: 272000, tokens: 10, breakdown: { model: LOCAL, totalTokens: 10, rawMaxTokens: 272000, percentage: 1,
    categories: [], memoryFiles: [], mcpTools: [], gridRows: [[sq('Messages', true, 1), sq('Messages', true, 0.3), sq('Free space', false, 0)]] } } }
  const out = await $.command.run({ command: 'context', args: '', origin: { kind: 'composer' }, presentation: { layout: 'main', columns: 80 } } as never)
  expect(out.text).toMatch(/estimated locally/)
  expect(out.text).toContain('■ □ ·')
  expect(w.reached).toEqual([])
  const btw = { command: 'btw', args: 'What was said?', origin: { kind: 'composer' }, presentation: { layout: 'main', columns: 80 } } as never
  expect((await $.command.run(btw)).text).toBe('side answer')
  expect(sent?.model).toBe(LOCAL)
  expect(sent?.messages.map(message => message.content[0]?.text)).toEqual(['hi', 'What was said?'])
  expect(sent?.tools).toBeUndefined()
  expect(sent?.system).toContain('read-only context')
  expect(w.reached).toEqual([])
  failed = true
  expect((await $.command.run(btw)).text).toContain('side-question request failed')
  expect(w.reached).toEqual([])
  w.current = 'claude-sonnet-5-5'
  expect((await $.command.run(btw)).text).toBe('engine')
  expect(w.reached).toEqual(['command.run'])
})

test('/context of a subscription model goes down the chain', async ($, on) => {
  const w = world(on, baseConfig, 'claude-sonnet-5-5', { stdout: '', code: 0 })
  const out = await $.command.run({ command: 'context', args: '', origin: { kind: 'composer' }, presentation: { layout: 'main', columns: 80 } } as never)
  expect(out.text).toBe('engine')
  expect(w.reached).toEqual(['command.run'])
})

test('a workflow agent on a bridge model keeps its own history and its compaction stays upstream', async ($, on) => {
  const summary = JSON.stringify({ content: [{ type: 'text', text: 'SUMMARY' }] })
  const w = world(on, baseConfig, LOCAL, { stdout: SSE_OK, code: 0 }, { exitCode: 0, stdout: summary })
  on('agent.spawn', async () => ({ model: LOCAL, agentId: 'wf-1' }))
  await $.agent.spawn({ tool_use_id: 'u1', prompt: 'do the thing', description: 'd', subagentType: 'general-purpose',
    workflow: { runId: 'wf_1', agentIndex: 1 } } as never)
  const { result } = await drain($.turn.step({ ...(STEP(LOCAL) as object), agentId: 'wf-1' } as never))
  expect(result.answer).toBe('local answer')
  // The agent's conversation is the one the mod tracked (the prompt it was spawned with), not a session read.
  expect(JSON.parse(w.spawned[0]!.input ?? '{}').messages[0].content[0].text).toBe('do the thing')
  expect(w.messagesRead).toBe(0)
  const compacted = await $.session.compact({ trigger: 'auto', agentId: 'wf-1', messages: [] } as never)
  expect('messages' in compacted && compacted.messages?.[0]?.text).toMatch(/SUMMARY$/)
  expect(w.reached).toEqual([])
})

test('context window and small-model variables are put back when a subscription model is selected again', async ($, on) => {
  const config = { ...baseConfig, contextWindows: { [LOCAL]: 272000 }, sideModel: 'claude-haiku-5-5' }
  const w = world(on, config, LOCAL, { stdout: SSE_OK, code: 0 }, undefined, { CLAUDE_CODE_MAX_CONTEXT_TOKENS: '500000' })
  await drain($.turn.step(STEP(LOCAL)))
  await drain($.turn.step(STEP('claude-sonnet-5-5')))
  expect(w.envSet).toEqual([
    ['CLAUDE_CODE_MAX_CONTEXT_TOKENS', '272000'], ['ANTHROPIC_SMALL_FAST_MODEL', 'claude-haiku-5-5'],
    ['CLAUDE_CODE_MAX_CONTEXT_TOKENS', '500000'], ['ANTHROPIC_SMALL_FAST_MODEL', undefined],
  ])
})

test('overlapping steps on a bridge model never take the applied window for the original', async ($, on) => {
  const config = { ...baseConfig, contextWindows: { [LOCAL]: 272000 }, sideModel: 'claude-haiku-5-5' }
  const w = world(on, config, LOCAL, { stdout: SSE_OK, code: 0 }, undefined, { CLAUDE_CODE_MAX_CONTEXT_TOKENS: '500000' })
  await Promise.all([drain($.turn.step(STEP(LOCAL))), drain($.turn.step(STEP(LOCAL))), drain($.turn.step(STEP(LOCAL)))])
  await drain($.turn.step(STEP('claude-sonnet-5-5')))
  expect(w.envSet).toEqual([
    ['CLAUDE_CODE_MAX_CONTEXT_TOKENS', '272000'], ['ANTHROPIC_SMALL_FAST_MODEL', 'claude-haiku-5-5'],
    ['CLAUDE_CODE_MAX_CONTEXT_TOKENS', '500000'], ['ANTHROPIC_SMALL_FAST_MODEL', undefined],
  ])
})

test('an environment write that failed is retried by the next step instead of being recorded as applied', async ($, on) => {
  const config = { ...baseConfig, contextWindows: { [LOCAL]: 272000 }, sideModel: 'claude-haiku-5-5' }
  const w = world(on, config, LOCAL, { stdout: SSE_OK, code: 0 })
  w.failEnvSets = 1
  await drain($.turn.step(STEP(LOCAL)))
  await drain($.turn.step(STEP(LOCAL)))
  expect(w.envSet).toEqual([['CLAUDE_CODE_MAX_CONTEXT_TOKENS', '272000'], ['ANTHROPIC_SMALL_FAST_MODEL', 'claude-haiku-5-5']])
})

test('a half-applied environment is completed and restored when the subscription model comes back', async ($, on) => {
  const config = { ...baseConfig, contextWindows: { [LOCAL]: 272000 }, sideModel: 'claude-haiku-5-5' }
  const w = world(on, config, LOCAL, { stdout: SSE_OK, code: 0 }, undefined, { CLAUDE_CODE_MAX_CONTEXT_TOKENS: '500000' })
  await drain($.turn.step(STEP(LOCAL)))
  await drain($.turn.step(STEP('claude-sonnet-5-5')))
  w.envSet.length = 0
  // second bridge selection: the window write succeeds, the side-model write throws
  w.failEnvName = 'ANTHROPIC_SMALL_FAST_MODEL'
  await drain($.turn.step(STEP(LOCAL)))
  await drain($.turn.step(STEP('claude-sonnet-5-5')))
  const last = (name: string) => w.envSet.filter(([n]) => n === name).at(-1)
  expect(last('CLAUDE_CODE_MAX_CONTEXT_TOKENS')).toEqual(['CLAUDE_CODE_MAX_CONTEXT_TOKENS', '500000'])
  expect(last('ANTHROPIC_SMALL_FAST_MODEL')?.[1]).toBeUndefined()
})

// The plugin's own options (`claude plugin install --config`), the form a user of the published plugin has.
const KEY = 'sk-test-0123456789abcdef'
const OPTIONS = { baseUrl: 'http://127.0.0.1:9999', apiKey: KEY, promptsDir: PROMPTS_DIR }

test('options: the key never enters an argument vector, models come from the upstream and the store keeps them', { options: OPTIONS }, async ($, on) => {
  const w = world(on, null, LOCAL, { stdout: SSE_OK, code: 0 }, { exitCode: 22, stdout: '' })
  w.models = [LOCAL, 'gpt-image-2', 'claude-sonnet-5-5']
  const setup = await $.command.run({ command: 'model-mod:setup', args: '', origin: { kind: 'composer' }, presentation: { layout: 'main', columns: 80 } } as never)
  // Setup reports chat models without a settings paste block.
  expect(setup.text).toContain('1 local models selected')
  expect(setup.text).not.toMatch(/gpt-image|claude-sonnet/)
  const { result } = await drain($.turn.step(STEP(LOCAL)))
  expect(result.answer).toBe('local answer')
  expect(w.reached).toEqual([])
  expect(w.fetched).toEqual([{ url: 'http://127.0.0.1:9999/v1/models', auth: 'Bearer' }])
  expect(w.store.models).toEqual([LOCAL])
  const sent = w.spawned[0]!
  expect(sent.argv.some(a => a.includes(KEY))).toBe(false)
  expect(sent.env).toEqual({ MODEL_MOD_KEY: KEY })
  // URL globbing is off, so a base URL is one request to one host
  expect(sent.argv[2]).toContain('curl -g ')
  // the run-to-completion calls (compaction here; web search, title and image use the same helper) do the same
  await $.session.compact({ trigger: 'manual', messages: [{ role: 'user', text: 'hello', toolUses: [] }] } as never)
  expect(w.ran.length).toBe(1)
  expect(w.ran[0]!.some(a => a.includes(KEY))).toBe(false)
  expect(w.ranEnv[0]).toEqual({ MODEL_MOD_KEY: KEY })
  // a subscription model still goes down the chain
  const other = await drain($.turn.step(STEP('claude-sonnet-5-5')))
  expect(other.result.answer).toBe('engine')
  expect(w.spawned.length).toBe(1)
})

test('options: with the upstream down the cached list and the picker rows still keep their turns off the chain', { options: OPTIONS }, async ($, on) => {
  const w = world(on, null, 'gpt-cached', { stdout: SSE_OK, code: 0 })
  w.store.models = ['gpt-cached']
  w.picker = [{ model: 'gpt-row', description: 'Local API via model-mod' }, { model: 'claude-x', description: 'Local API via model-mod' },
    { model: 'gpt-foreign', description: 'something else' }]
  for (const model of ['gpt-cached', 'gpt-row']) {
    const { result } = await drain($.turn.step(STEP(model)))
    expect(result.answer).toBe('local answer')
  }
  expect(w.reached).toEqual([])
  // rows that are not this mod's, and Claude IDs, are not owned
  for (const model of ['gpt-foreign', 'claude-x']) await drain($.turn.step(STEP(model)))
  expect(w.reached).toEqual(['turn.step', 'turn.step'])
})

for (const [name, options] of [
  ['no key', { baseUrl: 'http://127.0.0.1:9999' }],
  ['a key with a character that could end a curl config line', { apiKey: 'sk-"quoted' }],
  ['the subscription API as upstream', { apiKey: KEY, baseUrl: 'https://api.anthropic.com' }],
  ['a Claude model ID in the allowlist', { apiKey: KEY, models: 'gpt-a, claude-sonnet-5-5' }],
  ['a key with surrounding whitespace (it is refused, not trimmed)', { apiKey: ' sk-safe ' }],
  ['a key with a trailing newline', { apiKey: 'sk-safe\n' }],
  ['a base URL that curl would expand into two hosts', { apiKey: KEY, baseUrl: 'http://{127.0.0.1,api.anthropic.com}:9999' }],
] as const) {
  test(`options: ${name} leaves the mod inert`, { options }, async ($, on) => {
    const w = world(on, null, LOCAL, { stdout: SSE_OK, code: 0 })
    w.models = [LOCAL]
    w.store.models = [LOCAL]
    await drain($.turn.step(STEP(LOCAL)))
    expect(w.reached).toEqual(['turn.step'])
    expect(w.spawned).toEqual([])
    expect(w.fetched).toEqual([])
  })
}

test('options: an unusable key does not fall back to the configuration file', { options: { apiKey: 'sk-"quoted' } }, async ($, on) => {
  const w = world(on, baseConfig, LOCAL, { stdout: SSE_OK, code: 0 })
  await drain($.turn.step(STEP(LOCAL)))
  expect(w.reached).toEqual(['turn.step'])
  expect(w.spawned).toEqual([])
})

// `refresh` in the configuration file is argv that /model-mod:refresh runs; only absolute paths for the program and its
// script are accepted, and anything else is ignored rather than run.
for (const [name, refresh, runs] of [['absolute program and script', ['/usr/bin/python3', '/opt/capture.py', '--out', '/cfg/tools.json'], true],
  ['relative script', ['/usr/bin/python3', 'capture.py', '--out', '/cfg/tools.json'], false],
  ['relative program', ['python3', '/opt/capture.py', '--out', '/cfg/tools.json'], false],
  ['too few items', ['/usr/bin/python3', '/opt/capture.py', '--out'], false]] as const) {
  test(`refresh: a configuration file with ${name} ${runs ? 'runs the command' : 'does not run the command'}`, async ($, on) => {
    const w = world(on, { ...baseConfig, refresh }, LOCAL, { stdout: '', code: 0 }, { exitCode: 0, stdout: '' })
    const out = await $.command.run({ command: 'model-mod:refresh', args: '', origin: { kind: 'composer' } } as never)
    expect(w.ran.filter(argv => argv.join(' ') === refresh.join(' '))).toEqual(runs ? [refresh] : [])
    if (runs) expect(out.text).toContain('tool schemas refreshed')
  })
}

test('options: with an allowlist only the allowlist is answered and the other known models are refused here', { options: { ...OPTIONS, models: 'gpt-a' } }, async ($, on) => {
  const w = world(on, null, 'gpt-a', { stdout: SSE_OK, code: 0 })
  w.store.models = ['gpt-b', 'gpt-a']
  w.picker = [{ model: 'gpt-c', description: 'Local API via model-mod' }]
  expect((await drain($.turn.step(STEP('gpt-a')))).result.answer).toBe('local answer')
  for (const model of ['gpt-b', 'gpt-c']) {
    expect((await drain($.turn.step(STEP(model)))).result.answer).toContain('not in the allowlist')
  }
  expect(w.reached).toEqual([])
  expect(w.spawned.length).toBe(1)
})

test('options: the store keeps every model the bridge has owned, not only the latest listing', { options: OPTIONS }, async ($, on) => {
  const w = world(on, null, LOCAL, { stdout: SSE_OK, code: 0 })
  w.store.models = ['gpt-old']
  w.models = [LOCAL]
  await $.command.run({ command: 'model-mod:setup', args: '', origin: { kind: 'composer' }, presentation: { layout: 'main', columns: 80 } } as never)
  expect(w.store.models).toEqual(['gpt-old', LOCAL])
})

test('options: an error body that echoes the key never reaches the conversation', { options: OPTIONS }, async ($, on) => {
  const w = world(on, null, LOCAL, { stdout: SSE_OK, code: 0 },
    { exitCode: 22, stdout: `{"error":{"message":"Invalid API key: ${KEY}"}}` })
  w.store.models = [LOCAL]
  on('tool.check', async () => ({ decision: 'allow' as const }))
  const outcome = await $.tool.call({ tool: 'mcp__model-mod__web_search', query: 'anything' } as never).then(
    value => JSON.stringify(value), error => String(error instanceof Error ? error.message : error))
  expect(outcome).toContain('Search request failed')
  expect(outcome).not.toContain(KEY)
  expect(w.ranEnv[0]).toEqual({ MODEL_MOD_KEY: KEY })
})

test('options: a successful search reply that carries the key is masked too', { options: OPTIONS }, async ($, on) => {
  const w = world(on, null, LOCAL, { stdout: SSE_OK, code: 0 },
    { exitCode: 0, stdout: JSON.stringify({ content: [{ type: 'text', text: `result ${KEY} and %73${encodeURIComponent(KEY).slice(1)} in C:\\repo\\test.ts and /\\bword\\b/` },
      { type: 'web_search_tool_result', content: [{ title: `t ${KEY}`, url: `https://example.org/?k=${KEY}` }] }] }) })
  w.store.models = [LOCAL]
  on('tool.check', async () => ({ decision: 'allow' as const }))
  const outcome = await $.tool.call({ tool: 'mcp__model-mod__web_search', query: 'anything' } as never).then(
    value => JSON.stringify(value), error => String(error instanceof Error ? error.message : error))
  expect(outcome).toContain('[key]')
  expect(outcome).not.toContain(KEY)
  expect(outcome).not.toContain('0123456789abcdef')
  // Text that is already parsed JSON is not decoded a second time: a literal `\t` or `\b` stays a backslash pair.
  expect(outcome).toContain(JSON.stringify('C:\\repo\\test.ts and /\\bword\\b/').slice(1, -1))
  const requests = w.ran.length
  w.current = 'claude-opus-5-5'
  const refused = await $.tool.call({ tool: 'mcp__model-mod__web_search', query: 'anything' } as never).then(
    value => JSON.stringify(value), error => String(error instanceof Error ? error.message : error))
  expect(refused).toContain('web_search is only available while a local model is selected. With this model, use the built-in WebSearch tool instead.')
  expect(w.ran.length).toBe(requests)
})

// Automatic switch to the fallback model when the subscription's limit is reached.
const FALLBACK_OPTIONS = { ...OPTIONS, fallbackModel: 'gpt-fb' }
const END = { answer: '', durationMs: 1, isAborted: false, turnId: 't', reason: 'answer' as const }
const HOUR = 3_600_000
const fbWorld = (on: On, model = 'claude-sonnet-5-5', percent = 100) => {
  const w = world(on, null, model, { stdout: SSE_OK, code: 0 })
  w.store.models = [LOCAL, 'gpt-fb']
  w.limits = [{ kind: 'five_hour', percentUsed: percent, resetsAt: new Date(HOUR).toISOString() }]
  return w
}

test('fallback: nothing happens while the window is not used up, no fallback is set or the window has reset', { options: FALLBACK_OPTIONS }, async ($, on) => {
  const w = fbWorld(on, 'claude-sonnet-5-5', 99)
  await $.turn.complete(END)
  expect(w.modelRuns).toEqual([])
  w.limits = [{ kind: 'five_hour', percentUsed: 100, resetsAt: new Date(HOUR).toISOString() }]
  await w.clock.set(2 * HOUR)
  await $.turn.complete(END)
  expect(w.modelRuns).toEqual([])
})

test('fallback: off when no fallback model is set, and a subscription turn still goes down the chain', { options: OPTIONS }, async ($, on) => {
  const w = fbWorld(on)
  await $.turn.complete(END)
  expect(w.modelRuns).toEqual([])
  expect((await drain($.turn.step(STEP('claude-sonnet-5-5')))).result.answer).toBe('engine')
})

test('fallback: a used-up window switches the session to the fallback model, which then runs locally, and back after the reset',
  { options: FALLBACK_OPTIONS }, async ($, on) => {
  const w = fbWorld(on)
  await $.turn.complete(END)
  expect(w.modelRuns).toEqual(['gpt-fb'])
  expect(w.current).toBe('gpt-fb')
  // the local window and side model are applied with the switch (not left to the model-switch event)
  expect(w.envSet).toContainEqual(['CLAUDE_CODE_MAX_CONTEXT_TOKENS', '272000'])
  expect(w.envSet).toContainEqual(['ANTHROPIC_SMALL_FAST_MODEL', 'claude-haiku-5-5'])
  w.envSet.length = 0
  expect((await drain($.turn.step(STEP('gpt-fb')))).result.answer).toBe('local answer')
  expect(w.reached).toEqual([])
  // still limited: the next turn changes nothing
  await $.turn.complete(END)
  expect(w.modelRuns).toEqual(['gpt-fb'])
  // reset: back to the model the session came from
  await w.clock.set(HOUR + 1)
  await $.turn.complete(END)
  expect(w.modelRuns).toEqual(['gpt-fb', 'claude-sonnet-5-5'])
  expect(w.current).toBe('claude-sonnet-5-5')
  expect(w.envSet).toContainEqual(['CLAUDE_CODE_MAX_CONTEXT_TOKENS', undefined])
  await $.turn.complete(END)
  expect(w.modelRuns.length).toBe(2)
})

test('fallback: a model chosen by hand is left alone, before and after the switch', { options: FALLBACK_OPTIONS }, async ($, on) => {
  const w = fbWorld(on, LOCAL)
  await $.turn.complete(END)
  expect(w.modelRuns).toEqual([])
  w.current = 'claude-opus-5-5'
  await $.turn.complete(END)
  expect(w.modelRuns).toEqual(['gpt-fb'])
  // the person goes back to a subscription model by hand: the switch is theirs, nothing is switched back
  w.current = 'claude-haiku-5-5'
  w.limits = []
  await w.clock.set(HOUR + 1)
  await $.turn.complete(END)
  expect(w.modelRuns).toEqual(['gpt-fb'])
  expect(w.current).toBe('claude-haiku-5-5')
})

test('fallback: no picker row is needed and env is set before switching', { options: FALLBACK_OPTIONS }, async ($, on) => {
  const w = fbWorld(on)
  w.picker = []
  await $.turn.complete(END)
  expect(w.modelRuns).toEqual(['gpt-fb'])
  expect(w.switchEnv).toEqual(['gpt-fb'])
})

test('fallback: a Claude ID is ignored', { options: { ...OPTIONS, fallbackModel: 'claude-opus-5-5' } }, async ($, on) => {
  const w = fbWorld(on)
  w.picker = [{ model: 'claude-opus-5-5', description: 'Local API via model-mod' }]
  await $.turn.complete(END)
  expect(w.modelRuns).toEqual([])
})

test('fallback: a model outside the allowlist is ignored', { options: { ...OPTIONS, models: 'gpt-a', fallbackModel: 'gpt-fb' } }, async ($, on) => {
  const w = fbWorld(on)
  await $.turn.complete(END)
  expect(w.modelRuns).toEqual([])
})

test('worker: the local-worker agent type exists only when a worker or fallback model is set, and runs on that model',
  { options: { ...OPTIONS, workerModel: 'gpt-w', fallbackModel: 'gpt-fb' } }, async ($, on) => {
  const w = fbWorld(on)
  await $.session.start({ cwd: '/work' } as never)
  expect(w.agents).toEqual([{ name: 'local-worker', model: 'gpt-w' }])
})

test('worker: the fallback model is the worker model when none is set', { options: FALLBACK_OPTIONS }, async ($, on) => {
  const w = fbWorld(on)
  await $.session.start({ cwd: '/work' } as never)
  expect(w.agents).toEqual([{ name: 'local-worker', model: 'gpt-fb' }])
})

test('worker: no agent type without either model, and none for a Claude ID', { options: { ...OPTIONS, workerModel: 'claude-opus-5-5' } }, async ($, on) => {
  const w = fbWorld(on)
  await $.session.start({ cwd: '/work' } as never)
  expect(w.agents).toEqual([])
})

test('options: a key echoed with JSON escapes, percent encoding or base64 is still masked', { options: { ...OPTIONS, apiKey: 'token/secret+token???' } }, async ($, on) => {
  const key = 'token/secret+token???'
  let stdout = '{"error":"bad key token\\/secret+token??? \\u0074oken/secret+token??? \\u005ctoken/secret+token???"}'
  const w = world(on, null, LOCAL, { stdout: SSE_OK, code: 0 },
    () => ({ exitCode: 22, stdout }))
  w.store.models = [LOCAL]
  on('tool.check', async () => ({ decision: 'allow' as const }))
  const outcome = await $.tool.call({ tool: 'mcp__model-mod__web_search', query: 'anything' } as never).then(
    value => JSON.stringify(value), error => String(error instanceof Error ? error.message : error))
  expect(outcome).toContain('Search request failed')
  expect(outcome).not.toContain('secret+token')
  const percent = encodeURIComponent(key)
  // Canonical, lower-case hex, mixed hex case, and a partly percent-encoded form (a letter written as %74).
  const echoes = [percent, percent.replace(/%[0-9A-F]{2}/g, hex => hex.toLowerCase()), 'token%2fsecret%2Btoken%3F%3F%3F', '%74oken%2Fsecret%2Btoken%3F%3F%3F']
  for (let offset = 0; offset < 3; offset++) {
    const encoded = btoa('x'.repeat(offset) + key + 'suffix')
    echoes.push(encoded, encoded.replace(/\+/g, '-').replace(/\//g, '_'))
  }
  const maskedEchoes: string[] = []
  for (const echo of echoes) {
    stdout = JSON.stringify({ error: echo })
    const masked = await $.tool.call({ tool: 'mcp__model-mod__web_search', query: 'anything' } as never).then(
      value => JSON.stringify(value), error => String(error instanceof Error ? error.message : error))
    maskedEchoes.push(masked)
  }
  // Check every encoding together: with the old scrub every entry is false (not hidden by truncation).
  expect(maskedEchoes.map(masked => masked.includes('[key]'))).toEqual(echoes.map(() => true))
  for (let i = 0; i < echoes.length; i++) {
    expect(maskedEchoes[i]).toContain('Search request failed')
    expect(maskedEchoes[i]).not.toContain(echoes[i]!)
  }
})

const fetchOutcome = ($: Engine, url: string) => $.tool.call({ tool: 'mcp__model-mod__web_fetch', url } as never).then(
  value => JSON.stringify(value), error => String(error instanceof Error ? error.message : error))
const PRIVATE_FETCH = 'web_fetch does not fetch local or private addresses; use Bash for those.'
const PUBLIC_IP = '93.184.216.34'
test('web_fetch: private IP literals (including URL-normalised forms) and option-shaped hosts are refused directly', async ($, on) => {
  const w = world(on, baseConfig, LOCAL, { stdout: '', code: 0 })
  on('tool.check', async () => ({ decision: 'allow' as const }))
  for (const host of ['0x7f.1', '2130706433', '100.64.0.1', '224.0.0.1', '[::1]', '[::ffff:192.168.1.2]']) {
    expect(await fetchOutcome($, `http://${host}/`)).toContain(PRIVATE_FETCH)
  }
  expect(await fetchOutcome($, 'http://-flushcache/')).toContain('The host could not be resolved.')
  w.current = 'claude-opus-5-5'
  expect(await fetchOutcome($, 'https://example.com/page')).toContain(
    'web_fetch is only available while a local model is selected. With this model, use the built-in WebFetch tool instead.')
  expect(w.ran).toEqual([])
})

for (const system of ['Linux', 'Darwin']) {
  const mac = system === 'Darwin'
  const resolver = mac ? 'dscacheutil' : 'getent'
  const hostIndex = mac ? 5 : 2
  const dnsCommand = (host: string) => mac ? ['dscacheutil', '-q', 'host', '-a', 'name', host] : ['getent', 'ahosts', host]
  const dnsAnswer = (address: string) => mac ?
    `name: canonical.example\nalias: example.com other.example \n${address.includes(':') ? 'ipv6_address' : 'ip_address'}: ${address}\n\n` :
    `${address} STREAM example.com\n${address} DGRAM\n${address} RAW\n`

  test(`web_fetch (${system}): any private DNS answer is refused before curl runs`, async ($, on) => {
    let addresses: string[] = []
    const w = world(on, baseConfig, LOCAL, { stdout: '', code: 0 },
      () => ({ exitCode: 0, stdout: addresses.map(dnsAnswer).join('') }))
    w.system = system
    on('tool.check', async () => ({ decision: 'allow' as const }))
    for (const address of ['10.2.3.4', '192.168.1.2', '127.0.0.2', '172.16.1.2', '169.254.1.2', '0.0.0.0',
      '100.64.0.1', '100.127.255.254', '224.0.0.1', '::', '::1', 'fe80::2', 'febf::1', 'fec0::1', 'feff::1', 'fc00::1', 'fd12::1', 'ff02::1',
      '::ffff:10.2.3.4', '::ffff:127.0.0.1', '::ffff:c0a8:102', '::ffff:100.64.0.1',
      '::7f00:1', '64:ff9b::7f00:1', '2002:7f00:1::1',
      '::ffff:0:a02:304', '::ffff:0:7f00:1', '64:ff9b:1::7f00:1', '64:ff9b:1::5db8:d822', '::5efe:a02:304', '::5efe:c0a8:102']) {
      for (const position of [0, 1, 2]) {
        addresses = [PUBLIC_IP, PUBLIC_IP]
        addresses.splice(position, 0, address)
        expect(await fetchOutcome($, 'https://example.com/page')).toContain(PRIVATE_FETCH)
        expect(w.ran[w.ran.length - 1]).toEqual(dnsCommand('example.com'))
      }
    }
    expect(w.ran.every(argv => argv[0] === 'uname' || argv[0] === resolver)).toBe(true)
  })

  for (const [location, hosts, message] of [['http://127.0.0.1:9999/private', ['example.com'], PRIVATE_FETCH],
    ['http://private.example/private', ['example.com', 'private.example'], PRIVATE_FETCH],
    ['http://-flushcache/', ['example.com'], 'The host could not be resolved.']] as const) {
    test(`web_fetch (${system}): a redirect to ${location} is refused`, async ($, on) => {
      const w = world(on, baseConfig, LOCAL, { stdout: '', code: 0 }, argv => ({ exitCode: 0,
        stdout: argv[0] === resolver ? dnsAnswer(argv[hostIndex] === 'private.example' ? '192.168.1.2' : PUBLIC_IP) :
          `HTTP/1.1 302 Found\r\nLocation: ${location}\r\n\r\nredirect body` }))
      w.system = system
      on('tool.check', async () => ({ decision: 'allow' as const }))
      expect(await fetchOutcome($, 'https://example.com/start')).toContain(message)
      expect(w.ran.filter(argv => argv[0] === 'curl').length).toBe(1)
      expect(w.ran.filter(argv => argv[0] === resolver)).toEqual(hosts.map(dnsCommand))
    })
  }

  test(`web_fetch (${system}): public redirects resolve and pin each hop, accept five hops and use the final headers and body`, async ($, on) => {
    const urls = ['https://example.com/start', 'https://example.com/next', 'http://other.example:8080/page',
      'https://ipv6.example/end', 'https://ipv6.example/again', 'https://example.com/final']
    const locations = ['/next', 'http://other.example:8080/page', 'https://ipv6.example/end', 'again', 'https://example.com/final']
    const publicAddresses = ['2606:4700:4700::1111', '::5db8:d822', '64:ff9b::5db8:d822', '2002:5db8:d822::1',
      '::ffff:0:5db8:d822', '::5efe:5db8:d822', PUBLIC_IP, '8.0.0.8']
    let page = 0
    const w = world(on, baseConfig, LOCAL, { stdout: '', code: 0 }, argv => {
      if (argv[0] === resolver) return { exitCode: 0, stdout: (argv[hostIndex] === 'ipv6.example' ? publicAddresses : [PUBLIC_IP]).map(dnsAnswer).join('') }
      const location = locations[page++]
      return { exitCode: 0, stdout: 'HTTP/1.1 100 Continue\r\nLocation: http://127.0.0.1/ignored\r\n\r\n' +
        (location ? `HTTP/2 302\r\nlOcAtIoN: ${location}\r\n\r\nredirect body` :
          'HTTP/2 200\r\nContent-Type: text/html\r\nX-Test: header only\r\n\r\n<p>Public page</p>') }
    })
    w.system = system
    on('tool.check', async () => ({ decision: 'allow' as const }))
    const outcome = await fetchOutcome($, urls[0]!)
    expect(outcome).toContain('Public page')
    expect(outcome).not.toMatch(/header only|redirect body|Continue/)
    const curls = w.ran.filter(argv => argv[0] === 'curl')
    expect(curls.map(argv => argv[argv.length - 1])).toEqual(urls)
    expect(w.ran.filter(argv => argv[0] === resolver)).toEqual(urls.map(url => dnsCommand(new URL(url).hostname)))
    const mixedResolve = `ipv6.example:443:[2606:4700:4700::1111],[::5db8:d822],[64:ff9b::5db8:d822],[2002:5db8:d822::1],[::ffff:0:5db8:d822],[::5efe:5db8:d822],${PUBLIC_IP},8.0.0.8`
    expect(curls.map(argv => argv[argv.indexOf('--resolve') + 1])).toEqual([
      `example.com:443:${PUBLIC_IP}`, `example.com:443:${PUBLIC_IP}`, `other.example:8080:${PUBLIC_IP}`,
      mixedResolve, mixedResolve, `example.com:443:${PUBLIC_IP}`,
    ])
    for (const argv of curls) {
      expect(argv[1]).toBe('-q')
      expect(argv).toContain('-i')
      expect(argv.some(arg => /^-[^-]*L/.test(arg))).toBe(false)
      expect(argv).not.toContain('--location')
      expect(argv[argv.indexOf('--proto') + 1]).toBe('=http,https')
      expect(argv[argv.indexOf('--max-time') + 1]).toBe('60')
      expect(argv[argv.indexOf('--max-filesize') + 1]).toBe('3000000')
      expect(argv[argv.indexOf('--noproxy') + 1]).toBe('*')
      expect(argv[argv.length - 2]).toBe('--')
    }
  })

  test(`web_fetch (${system}): a sixth redirect is refused without fetching its destination`, async ($, on) => {
    let page = 0
    const w = world(on, baseConfig, LOCAL, { stdout: '', code: 0 }, argv => ({ exitCode: 0,
      stdout: argv[0] === resolver ? dnsAnswer(PUBLIC_IP) : `HTTP/1.1 302 Found\r\nLocation: /hop-${++page}\r\n\r\n` }))
    w.system = system
    on('tool.check', async () => ({ decision: 'allow' as const }))
    expect(await fetchOutcome($, 'https://example.com/start')).toContain('Too many redirects.')
    const curls = w.ran.filter(argv => argv[0] === 'curl')
    expect(curls.length).toBe(6)
    expect(curls[curls.length - 1]![curls[curls.length - 1]!.length - 1]).toBe('https://example.com/hop-5')
  })

  test(`web_fetch (${system}): resolver failures never reach curl`, async ($, on) => {
    let reply: RunReply | undefined
    const w = world(on, baseConfig, LOCAL, { stdout: '', code: 0 }, () => {
      if (!reply) throw new Error('resolver missing')
      return reply
    })
    w.system = system
    on('tool.check', async () => ({ decision: 'allow' as const }))
    for (reply of [undefined, { exitCode: 1, stdout: dnsAnswer(PUBLIC_IP) },
      { exitCode: 0, stdout: '' }, { exitCode: 0, stdout: 'garbled' },
      { exitCode: 0, stdout: dnsAnswer(PUBLIC_IP) + (mac ? 'ipv6_address: not-an-ip\n' : 'not-an-ip STREAM\n') },
      { exitCode: 0, stdout: dnsAnswer('012.0.0.1') }, { exitCode: 0, stdout: dnsAnswer('01.2.3.4') },
      { exitCode: 0, stdout: dnsAnswer(PUBLIC_IP), isStdoutTruncated: true }]) {
      expect(await fetchOutcome($, 'https://example.com/page')).toContain('The host could not be resolved.')
      expect(w.ran[w.ran.length - 1]).toEqual(dnsCommand('example.com'))
    }
    expect(w.ran.some(argv => argv[0] === 'curl')).toBe(false)
  })
}

test('options: the store keeps a model the bridge took over even when 300 are already known', { options: OPTIONS }, async ($, on) => {
  const w = world(on, null, LOCAL, { stdout: SSE_OK, code: 0 }, { exitCode: 22, stdout: '' })
  w.store.models = Array.from({ length: 300 }, (_, i) => `gpt-old-${i}`)
  w.models = ['gpt-new']
  await $.command.run({ command: 'model-mod:setup', args: '', origin: { kind: 'composer' }, presentation: { layout: 'main', columns: 80 } } as never)
  expect(w.store.models).toContain('gpt-new')
  expect(w.store.models).toContain('gpt-old-0')
})

test('fallback: a manual choice after a switch is respected until that window resets', { options: FALLBACK_OPTIONS }, async ($, on) => {
  const w = fbWorld(on)
  await $.turn.complete(END)
  expect(w.modelRuns).toEqual(['gpt-fb'])
  w.current = 'claude-opus-5-5'          // the person goes back to the subscription by hand
  await $.turn.complete(END)
  await $.turn.complete(END)
  expect(w.modelRuns).toEqual(['gpt-fb'])
  await w.clock.set(HOUR + 1)             // reset: the window is no longer used up, the switch is possible again later
  w.limits = [{ kind: 'five_hour', percentUsed: 100, resetsAt: new Date(3 * HOUR).toISOString() }]
  await $.turn.complete(END)
  await $.turn.complete(END)
  expect(w.modelRuns).toEqual(['gpt-fb', 'gpt-fb'])
})

test('fallback: a model of another plugin is not switched away from', { options: FALLBACK_OPTIONS }, async ($, on) => {
  const w = fbWorld(on, 'gpt-other-plugin')
  await $.turn.complete(END)
  expect(w.modelRuns).toEqual([])
})


const SETUP = { command: 'model-mod:setup', args: '', origin: { kind: 'composer' }, presentation: { isFullscreen: false, columns: 80 } } as const

for (const scope of ['local', 'project', 'user'] as const) {
  test(`setup: Keep → All saves options at ${scope} install without any file write`, { options: OPTIONS }, async ($, on) => {
    const w = world(on, null, LOCAL, { stdout: '', code: 0 })
    w.scopes[scope] = { enabledPlugins: { 'model-mod@test-market': true, 'other@test-market': true } }
    w.models = [LOCAL, 'gpt-other', 'claude-sonnet-5-5', 'gpt-image-2']
    const out = await $.command.run(SETUP)
    expect(out.text).toContain('2 local models selected')
    expect(w.writes).toEqual([])
    expect(w.ran).toEqual([])
    expect(w.saved).toEqual([{ key: 'model-mod.baseUrl', value: OPTIONS.baseUrl }, { key: 'model-mod.models', value: '' }])
    expect(w.questions.length).toBe(2)
    expect(w.questions[1]!.labels[0]).toBe('All (recommended)')
  })
}

test('setup: Change URL fetches that endpoint and saves it after fetching models', { options: OPTIONS }, async ($, on) => {
  const w = world(on, null, LOCAL, { stdout: '', code: 0 })
  w.models = [LOCAL]; w.scopes.project = { enabledPlugins: { 'model-mod@test': true } }
  w.answers = ['Change', 'http://localhost:9999/proxy/', 'All (recommended)']
  const out = await $.command.run(SETUP)
  expect(out.text).toContain('1 local models selected')
  expect(w.fetched[0]!.url).toBe('http://localhost:9999/proxy/v1/models')
  expect(w.saved[0]!.value).toBe('http://localhost:9999/proxy')
})

test('setup: subset uses pages of at most four IDs, ignores unknown Other text, and allows empty pages', { options: OPTIONS }, async ($, on) => {
  const w = world(on, null, LOCAL, { stdout: '', code: 0 })
  w.models = Array.from({ length: 9 }, (_, i) => `gpt-${i}`)
  w.scopes.user = { enabledPlugins: { 'model-mod@test': true } }
  w.answers = ['Keep (recommended)', 'Choose a subset', 'gpt-0,gpt-3,not-listed', '', 'gpt-8']
  const out = await $.command.run(SETUP)
  expect(out.text).toContain('Ignored text')
  expect(w.questions.slice(2).map(q => q.header)).toEqual(['Models 1/3', 'Models 2/3', 'Models 3/3'])
  expect(w.questions.slice(2).every(q => q.multiSelect && q.labels.length <= 4 && q.labels.length >= 2)).toBe(true)
  expect(w.writes).toEqual([])
  expect(w.saved[1]!.value).toBe('gpt-0,gpt-3,gpt-8')
})

test('setup: an empty subset offers another pass, and Other accepts only exact listed IDs', { options: OPTIONS }, async ($, on) => {
  const w = world(on, null, LOCAL, { stdout: '', code: 0 })
  w.models = [LOCAL, 'gpt-other']; w.scopes.user = { enabledPlugins: { 'model-mod@test': true } }
  w.answers = ['Keep (recommended)', 'Choose a subset', '', 'Choose again (recommended)', LOCAL]
  await $.command.run(SETUP)
  expect(w.questions[3]!.question).toContain('At least one')
  expect(w.saved[1]!.value).toBe(LOCAL)
})

for (const status of [404, 405, 501, 200]) {
  test(`setup: unsupported model list (${status}) permits manual IDs`, { options: OPTIONS }, async ($, on) => {
    const w = world(on, null, LOCAL, { stdout: '', code: 0 })
    w.httpStatus = status; w.httpBody = '<html>no model endpoint</html>'
    w.scopes.user = { enabledPlugins: { 'model-mod@test': true } }
    w.answers = ['Keep (recommended)', 'gpt-manual, claude-sonnet-5-5, gpt-image-2']
    const out = await $.command.run(SETUP)
    expect(out.text).toContain('1 local models selected')
    expect(w.questions[1]!.question).toContain('does not support')
    expect(w.saved[1]!.value).toBe('gpt-manual')
    if (status === 404) {
      w.httpStatus = undefined; w.httpStatuses = [404, 404, 404]; w.models = [LOCAL]
      w.answers = ['Keep (recommended)', 'Try again', 'Try again', 'Try again', 'All (recommended)']
      expect((await $.command.run(SETUP)).text).toContain('1 local models selected')
      expect(w.fetched.length).toBe(5)
      expect(w.saved.at(-1)).toEqual({ key: 'model-mod.models', value: '' })
      const saved = [...w.saved], cached = [...w.store.models as string[]]
      w.httpStatus = 404
      w.answers = ['Keep (recommended)', 'Try again', 'Try again', 'Try again', 'Try again']
      expect((await $.command.run(SETUP)).text).toContain('retry limit reached; nothing changed')
      expect(w.fetched.length).toBe(9)
      expect(w.saved).toEqual(saved)
      expect(w.store.models).toEqual(cached)
    }
  })
}
for (const status of [undefined, 401, 500, 503]) {
  test(`setup: upstream failure (${status ?? 'network'}) never offers a manual fallback`, { options: OPTIONS }, async ($, on) => {
    const w = world(on, null, LOCAL, { stdout: '', code: 0 })
    w.httpStatus = status
    const out = await $.command.run(SETUP)
    expect(out.text).toContain('model list failed')
    expect(w.questions.length).toBe(1)
    expect(w.writes).toEqual([]); expect(w.saved).toEqual([])
  })
}

test('setup: dismissing any question changes nothing', { options: OPTIONS }, async ($, on) => {
  const w = world(on, null, LOCAL, { stdout: '', code: 0 })
  w.models = [LOCAL]; w.answers = ['Keep (recommended)', null]
  const out = await $.command.run(SETUP)
  expect(out.text).toContain('setup cancelled, nothing changed')
  expect(w.writes).toEqual([]); expect(w.saved).toEqual([]); expect(w.store).toEqual({})
})

for (const url of ['https://api.anthropic.com', 'https://claude.ai', 'https://tenant.claude.ai']) {
  test(`setup: rejects subscription endpoint ${url}`, { options: OPTIONS }, async ($, on) => {
    const w = world(on, null, LOCAL, { stdout: '', code: 0 })
    w.answers = ['Change', url]
    const out = await $.command.run(SETUP)
    expect(out.text).toContain('refused upstream URL')
    expect(w.fetched).toEqual([]); expect(w.writes).toEqual([]); expect(w.saved).toEqual([])
  })
}

test('setup: missing apiKey stops without asking for a key even while inactive', async ($, on) => {
  const w = world(on, null, LOCAL, { stdout: '', code: 0 })
  await $.session.start({ cwd: '/work' } as never)
  const out = await $.command.run(SETUP)
  expect(out.text).toContain('apiKey is not configured')
  expect(out.text).toContain('/plugin → model-mod configure')
  expect(w.questions).toEqual([]); expect(w.writes).toEqual([])
  expect(w.registered).toEqual([])
})

test('setup: headless run shows status without a question or changes; old command is not hooked', { options: OPTIONS }, async ($, on) => {
  const w = world(on, null, LOCAL, { stdout: '', code: 0 })
  const out = await $.command.run({ ...SETUP, origin: { kind: 'sdk' } } as never)
  expect(out.text).toContain('setup is interactive')
  expect(out.text).toContain('picker=active')
  expect(w.questions).toEqual([]); expect(w.writes).toEqual([]); expect(w.saved).toEqual([])
  expect((await $.command.run({ ...SETUP, command: 'old-command', args: '' })).text).toBe('engine')
})

test('refresh: saved subset removes disappeared IDs, keeps the ownership cache and writes no file', { options: { ...OPTIONS, models: 'gpt-old,gpt-kept' } }, async ($, on) => {
  const w = world(on, null, LOCAL, { stdout: '', code: 0 })
  w.models = ['gpt-kept', 'gpt-new']; w.store.models = ['gpt-old']
  const out = await $.command.run({ ...SETUP, command: 'model-mod:refresh' })
  expect(out.text).toContain('/model-mod:model offers')
  expect(w.saved).toEqual([{ key: 'model-mod.models', value: 'gpt-kept' }])
  expect(w.store.models).toEqual(['gpt-old', 'gpt-kept'])
  expect(w.writes).toEqual([]); expect(w.ran).toEqual([])
  w.models = ['gpt-new']
  expect((await $.command.run({ ...SETUP, command: 'model-mod:refresh' })).text).toContain('allowlist unchanged')
  expect(w.saved).toEqual([{ key: 'model-mod.models', value: 'gpt-kept' }])
})

const MODEL = { ...SETUP, command: 'model', args: '' }
// The paged menu is what a bridge origin gets; a composer gets the pane, which these tests do not cover.
// The chosen model is applied by the client's own /model after the hook answered: step the clock past that timer.
async function picked($: { command: { run: (c: never) => Promise<{ text?: string }> } }, w: { clock: { set: (ms: number) => Promise<unknown> } }, input: unknown) {
  const out = await $.command.run(input as never)
  await w.clock.set(Date.now() + 1)
  return out
}
const PICK = { ...SETUP, command: 'model-mod:model', args: '', origin: { kind: 'bridge' } } as const

test('/model: a cached local ID excluded by the allowlist is refused without forwarding or env', { options: { ...OPTIONS, models: 'gpt-kept' } }, async ($, on) => {
  const w = world(on, null, 'claude-sonnet-5-5', { stdout: '', code: 0 })
  w.store.models = ['gpt-old']
  const out = await $.command.run({ ...MODEL, args: 'gpt-old' })
  expect(out.text).toBe('model-mod: gpt-old is not in the allowlist; run /model-mod:setup.')
  expect(w.modelRuns).toEqual([])
  expect(w.envSet).toEqual([])
})

const ALIASES = ['sonnet', 'opus', 'haiku', 'fable', 'best', 'default', 'opusplan'].flatMap(id => [id, id + '[1m]'])

test('setup: official alias collisions are skipped and absent from local pages', { options: OPTIONS }, async ($, on) => {
  const w = world(on, null, 'claude-sonnet-5-5', { stdout: '', code: 0 })
  w.models = [...ALIASES, 'Cancel']
  await $.session.start({ cwd: '/work' } as never)
  expect(w.store.models).toEqual(['Cancel'])
  for (const id of ALIASES) await $.command.run({ ...MODEL, args: id })
  expect(w.modelRuns).toEqual(ALIASES)
  expect(w.envSet).toEqual([])
  const out = await $.command.run(SETUP)
  expect(out.text).toContain('1 local models selected')
  expect(out.text).toContain('skipped (collides with an official alias): ' + ALIASES.join(', '))
  w.answers = ['Local models (1)', null]
  await $.command.run(PICK)
  expect(w.questions.at(-1)!.labels).toEqual(['Cancel', '[Cancel]'])
  expect(w.envSet).toEqual([])
})

test('/model: aliases in allowlist, cache, legacy rows and worker options stay official', { options: {
  ...OPTIONS, models: [...ALIASES, 'gpt-a'].join(','), fallbackModel: 'sonnet', workerModel: 'opus',
} }, async ($, on) => {
  const w = world(on, null, 'claude-sonnet-5-5', { stdout: '', code: 0 })
  w.store.models = ALIASES
  w.picker = ALIASES.map(model => ({ model, description: 'Local API via model-mod' }))
  await $.session.start({ cwd: '/work' } as never)
  expect(w.agents).toEqual([])
  for (const id of ALIASES) {
    await $.command.run({ ...MODEL, args: id })
    expect((await drain($.turn.step(STEP(id)))).result.answer).toBe('engine')
  }
  expect(w.modelRuns).toEqual(ALIASES)
  expect(w.envSet).toEqual([])
  expect(w.spawned).toEqual([])
  w.answers = ['Local models (1)', null]
  await $.command.run(PICK)
  expect(w.questions.at(-1)!.labels).toEqual(['gpt-a', '[Cancel]'])
})

test('setup: All caps offers and saves at the first 2000 IDs, all retained in the cache', { options: OPTIONS }, async ($, on) => {
  const w = world(on, null, 'claude-sonnet-5-5', { stdout: '', code: 0 })
  w.models = Array.from({ length: 2100 }, (_, i) => `gpt-${i}`)
  // Overlapping old entries must not displace any selected ID when the cache is full.
  w.store.models = ['gpt-0', 'gpt-old']
  const out = await $.command.run(SETUP)
  const selected = w.models.slice(0, 2000)
  expect(w.store.models).toEqual(selected)
  expect(w.saved[1]!.value).toBe(selected.join(','))
  expect(out.text).toContain('2000 local models selected')
  expect(out.text).toContain('first 2000 local model IDs (2100 listed)')
  expect(out.text).toContain('saved as an explicit allowlist')
})

test('/model-mod:model: a local selection sets env and runs the native /model; the current model is marked', { options: { ...OPTIONS, models: LOCAL } }, async ($, on) => {
  const w = world(on, null, LOCAL, { stdout: '', code: 0 })
  w.answers = [LOCAL + ' (current)']
  await picked($, w, PICK)
  expect(w.questions).toHaveLength(1)
  expect(w.questions[0]!.labels).toContain(LOCAL + ' (current)')
  expect(w.modelRuns).toEqual([LOCAL])
  expect(w.switchEnv).toEqual([LOCAL])
  expect(w.envSet).toEqual([['ANTHROPIC_CUSTOM_MODEL_OPTION', LOCAL]])
})

test('/model-mod:model: dismissing the menu never switches', { options: { ...OPTIONS, models: LOCAL } }, async ($, on) => {
  const w = world(on, null, LOCAL, { stdout: '', code: 0 })
  w.answers = [null]
  expect((await picked($, w, PICK)).text).toBe('model-mod: model not changed.')
  expect(w.modelRuns).toEqual([]); expect(w.envSet).toEqual([])
})

test('/model: direct owned ID sets env; official args pass through; env failure never forwards', { options: { ...OPTIONS, models: LOCAL } }, async ($, on) => {
  const w = world(on, null, LOCAL, { stdout: '', code: 0 })
  await $.command.run({ ...MODEL, args: LOCAL })
  expect(w.modelRuns).toEqual([LOCAL]); expect(w.switchEnv).toEqual([LOCAL])
  w.envSet.length = 0
  await $.command.run({ ...MODEL, args: 'sonnet' })
  expect(w.modelRuns).toEqual([LOCAL, 'sonnet']); expect(w.envSet).toEqual([])
  w.failEnvName = 'ANTHROPIC_CUSTOM_MODEL_OPTION'
  expect((await $.command.run({ ...MODEL, args: LOCAL })).text).toContain('model not changed')
  expect(w.modelRuns).toEqual([LOCAL, 'sonnet'])
})

test('/model: empty args and official IDs pass through the native command untouched', { options: { ...OPTIONS, models: LOCAL } }, async ($, on) => {
  const w = world(on, null, LOCAL, { stdout: '', code: 0 })
  await $.command.run(MODEL)
  expect(w.modelRuns).toEqual(['']); expect(w.questions).toEqual([]); expect(w.envSet).toEqual([])
})

test('/model-mod:model: an inactive mod says so and opens nothing', async ($, on) => {
  const w = world(on, null, LOCAL, { stdout: '', code: 0 })
  expect((await $.command.run(PICK)).text).toContain('inactive')
  expect(w.modelRuns).toEqual([]); expect(w.questions).toEqual([])
})

test('/model-mod:model: sdk is refused and an empty local list points to setup', { options: OPTIONS }, async ($, on) => {
  const w = world(on, null, LOCAL, { stdout: '', code: 0 })
  expect((await $.command.run({ ...PICK, origin: { kind: 'sdk' } })).text).toContain('interactive session')
  expect((await $.command.run(PICK)).text).toContain('/model-mod:setup')
  expect(w.questions).toEqual([]); expect(w.modelRuns).toEqual([])
})

test('/model: PostModelSwitch applies the local window and restores it for Claude', { options: { ...OPTIONS, models: LOCAL } }, async ($, on) => {
  const w = world(on, null, 'claude-sonnet-5-5', { stdout: '', code: 0 })
  await $.command.run({ ...MODEL, args: LOCAL })
  await $.classic.PostModelSwitch({ from_model: 'claude-sonnet-5-5', to_model: LOCAL } as never)
  expect(w.envSet).toContainEqual(['CLAUDE_CODE_MAX_CONTEXT_TOKENS', '272000'])
  await $.classic.PostModelSwitch({ from_model: LOCAL, to_model: 'claude-sonnet-5-5' } as never)
  expect(w.envSet).toContainEqual(['CLAUDE_CODE_MAX_CONTEXT_TOKENS', undefined])
})
