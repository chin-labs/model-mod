import type { EngineInterface, PluginOptions, Register, SessionMessage, TurnStepChunk, TurnStepInput, TurnStepResult } from 'claude-code'
import { update } from 'claude-code'
import type { EnvMemo, FallbackMemo, TrackedAgent } from '../types'
import { MessagesStream } from './sse.ts'
import { htmlToText } from './text.ts'
import { openPane, registerPane } from './pane.tsx'

// Read legacy rows only as an extra ownership source; this mod never writes them.
const ROW_MARK = 'Local API via model-mod'
const MODEL_ID = /^[A-Za-z0-9][A-Za-z0-9._:\/-]{0,99}$/
const NOT_CHAT = /claude|anthropic|image|auto-review|embed|tts|whisper|moderation/i
const OFFICIAL_ALIAS = /^(sonnet|opus|haiku|fable|best|default|opusplan)(\[1m\])?$/i
const MODEL_CACHE_CAP = 2000
// CLIProxyAPI's default loopback address; keep it in step with the manifest's baseUrl default.
const DEFAULT_BASE_URL = 'http://127.0.0.1:8317'

function endpoint(value: string): string {
  const url = new URL(value.trim())
  const host = url.hostname.toLowerCase().replace(/\.$/, '')
  if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password || url.search || url.hash ||
      !/^(\[[0-9a-f:.]+\]|[a-z0-9_]([a-z0-9._-]*[a-z0-9_])?)$/.test(host) ||
      ['anthropic.com', 'claude.ai'].some(d => host === d || host.endsWith(d))) throw new Error('refused upstream URL')
  return url.origin + url.pathname.replace(/\/+$/, '')
}

type ModelList = { ids: string[]; chat: string[] } | { error: string; unsupported?: boolean }
async function modelList($: EngineInterface, baseUrl: string, key: string): Promise<ModelList> {
  try {
    const reply = await Promise.race([
      $.http.fetch(baseUrl + '/v1/models', { headers: { authorization: 'Bearer ' + key } }),
      $.clock.sleep(8000).then(() => undefined),
    ])
    if (!reply) return { error: 'timeout' }
    if (!reply.ok) return { error: `HTTP ${reply.status}`, unsupported: [404, 405, 501].includes(reply.status) }
    let body: unknown
    try { body = JSON.parse(reply.text) } catch { return { error: 'body is not a model list', unsupported: true } }
    const data = (body as { data?: unknown } | null)?.data
    if (!Array.isArray(data) || !data.every(row => row && typeof row === 'object' && typeof row.id === 'string')) {
      return { error: 'body is not a model list', unsupported: true }
    }
    const ids = [...new Set(data.map(row => row.id as string).filter(id => (MODEL_ID.test(id) || OFFICIAL_ALIAS.test(id)) && !/claude|anthropic/i.test(id)))]
    return { ids, chat: ids.filter(id => !NOT_CHAT.test(id)) }
  } catch { return { error: 'unreachable' } }
}

class Cancelled extends Error {}
async function ask($: EngineInterface, question: string, options: Parameters<EngineInterface['ui']['ask']>[1]): Promise<string> {
  try { return await $.ui.ask(question, options) } catch { throw new Cancelled() }
}

// ui.ask exposes labels only; include the current-model description in its label.
async function pickModel($: EngineInterface, ids: readonly string[], current: string): Promise<string> {
  for (let page = 0;; page = (page + 1) % Math.ceil(ids.length / 3)) {
    const listed = ids.slice(page * 3, page * 3 + 3)
    const labels = listed.map(id => id === current ? `${id} (current)` : id)
    const options = [...labels]
    if ((page + 1) * 3 < ids.length) options.push('More…')
    if (options.length < 2) options.push('[Cancel]')
    const choice = await ask($, `Choose a model. Current model: ${current}.`, { options, header: 'Model' })
    if (choice === 'More…' && (page + 1) * 3 < ids.length) continue
    const index = labels.indexOf(choice)
    if (index < 0) throw new Cancelled()
    return listed[index]!
  }
}

async function chooseModels($: EngineInterface, ids: string[], notes: string[]): Promise<{ selected: string[]; all: boolean }> {
  $.ui.log('Local API chat models: ' + ids.join(', '))
  const choice = await ask($, 'Which local API models should /model-mod:model offer?', ['All (recommended)', 'Choose a subset'])
  if (choice === 'All (recommended)') return { selected: ids, all: true }
  if (ids.includes(choice)) return { selected: [choice], all: false }
  if (choice !== 'Choose a subset') notes.push('Ignored text that did not match a listed model ID.')
  for (;;) {
    const selected = new Set<string>()
    const pages = Math.ceil(ids.length / 4)
    for (let page = 0; page < pages; page++) {
      const listed = ids.slice(page * 4, page * 4 + 4)
      // The engine requires 2–4 labels, even when the last page contains just one model.
      const labels = listed.length === 1 ? [...listed, 'None on this page'] : listed
      const answer = await ask($, 'Which models on this page should be included?', { options: labels, header: `Models ${page + 1}/${pages}`, multiSelect: true })
      for (const id of answer.split(',').map(s => s.trim()).filter(Boolean)) {
        if (listed.includes(id)) selected.add(id)
        else if (id !== 'None on this page') notes.push(`Ignored text that did not match a listed model ID on page ${page + 1}.`)
      }
    }
    if (selected.size) return { selected: [...selected], all: false }
    const retry = await ask($, 'At least one model is required. Choose again?', ['Choose again (recommended)', 'Cancel'])
    if (retry !== 'Choose again (recommended)') throw new Cancelled()
  }
}

async function configurePicker($: EngineInterface, c: { baseUrl: string; key?: string; models: string[]; explicitModels?: boolean }, setup: boolean, interactive: boolean, status: string): Promise<string> {
  if (setup && !c.key) return 'model-mod: apiKey is not configured. Open /plugin → model-mod configure, set the upstream API key there, then run /model-mod:setup.'
  if (setup && !interactive) return 'model-mod setup is interactive. ' + status
  if (!c.key) return 'model-mod: no apiKey in the plugin options; picker refresh is unavailable.'
  try {
    let baseUrl = c.baseUrl
    if (setup) {
      const choice = await ask($, `Keep the API endpoint ${baseUrl}?`, ['Keep (recommended)', 'Change'])
      if (choice !== 'Keep (recommended)') {
        const input = choice === 'Change' ? await ask($, 'What is the API endpoint URL? Type it under Other.', ['Cancel', 'Keep current endpoint']) : choice
        if (input === 'Cancel') throw new Cancelled()
        if (input !== 'Keep current endpoint') baseUrl = input
      }
    }
    try { baseUrl = endpoint(baseUrl) } catch { return 'model-mod: refused upstream URL; nothing changed.' }
    const notes: string[] = []
    let capped = false
    const offered = (ids: string[]): string[] => {
      const skipped = ids.filter(id => OFFICIAL_ALIAS.test(id))
      if (skipped.length) notes.push('skipped (collides with an official alias): ' + skipped.join(', '))
      const local = { models: [] as string[] }
      addModels(local, ids)
      if (setup && local.models.length > MODEL_CACHE_CAP) {
        capped = true
        notes.push(`Limited to the first ${MODEL_CACHE_CAP} local model IDs (${local.models.length} listed) to fit the ownership cache; saved as an explicit allowlist.`)
        return local.models.slice(0, MODEL_CACHE_CAP)
      }
      return local.models
    }
    let selected: string[], all = false
    for (let retries = 0;; retries++) {
      const fetched = await modelList($, baseUrl, c.key)
      if ('error' in fetched) {
        if (!setup || !fetched.unsupported) return `model-mod: model list failed (${fetched.error}); nothing changed.`
        const input = await ask($, `The API does not support a model list (${fetched.error}). Which comma-separated model IDs should be used? Type them under Other.`, ['Cancel', 'Try again'])
        if (input === 'Cancel') throw new Cancelled()
        if (input === 'Try again') {
          if (retries >= 3) return 'model-mod: model list retry limit reached; nothing changed.'
          continue
        }
        selected = offered(input.split(',').map(s => s.trim()).filter(id => !NOT_CHAT.test(id)))
        if (!selected.length) return ['model-mod: no valid chat model IDs; nothing changed.', ...notes].join('\n')
      } else {
        const ids = offered(fetched.chat)
        if (!ids.length) return ['model-mod: no chat models listed; nothing changed.', ...notes].join('\n')
        if (setup) {
          ({ selected, all } = await chooseModels($, ids, notes))
          if (capped) all = false
        } else selected = c.explicitModels ? ids.filter(id => c.models.includes(id)) : ids
      }
      break
    }
    if (!selected.length) return 'model-mod: none of the saved models remain in the API list; allowlist unchanged.'
    // Resolve config rows before changing anything; set options last because the module reloads.
    const rows = await $.config.list()
    const rowFor = (field: string) => rows.find(row => row.key.endsWith('.' + field) && row.provider.plugin.split('@')[0] === $.plugin.name.split('@')[0])
    const urlRow = rowFor('baseUrl'), modelsRow = rowFor('models')
    if (!modelsRow || modelsRow.isLocked || (setup && (!urlRow || urlRow.isLocked))) return 'model-mod: writable plugin config rows are unavailable; nothing changed.'
    const known = await $.store.get('models')
    const cached = { models: [] as string[] }
    if (Array.isArray(known)) addModels(cached, known.filter(id => typeof id === 'string' && !NOT_CHAT.test(id) && !selected.includes(id)))
    addModels(cached, selected)
    await $.store.set('models', cached.models.slice(-MODEL_CACHE_CAP))
    if (!c.explicitModels) addModels(c, selected)
    const text = [`model-mod: ${selected.length} local models selected. /model-mod:model offers these models.`, ...notes].join('\n')
    $.ui.log(text)
    if (setup) {
      const urlResult = await $.config.set({ key: urlRow!.key, value: baseUrl })
      if ('deny' in urlResult) return 'model-mod: endpoint option was refused; configure it through /plugin.'
    }
    const modelResult = await $.config.set({ key: modelsRow.key, value: setup ? (all ? '' : selected.join(',')) : (c.explicitModels ? selected.join(',') : '') })
    if ('deny' in modelResult) return 'model-mod: model option was refused; configure it through /plugin.'
    return text
  } catch (err) {
    if (err instanceof Cancelled) return 'model-mod: setup cancelled, nothing changed'
    return 'model-mod: setup could not complete; check the plugin configuration.'
  }
}

type Config = { prompts: Prompts; promptsDir?: string; baseUrl: string; headerFile?: string; key?: string; models: string[]; toolsFile?: string; defaultWindow?: number; explicitModels?: boolean; excluded?: Set<string>; imageAuto?: boolean; source?: 'options' | 'file'; maxTokens: number; effortMode: 'suffix' | 'none'; imageModel?: string; contextWindows?: Record<string, number>; sideModel?: string; keepThinking?: boolean; localTitle?: boolean; localContext?: boolean; toolSearch?: 'auto' | 'on' | 'off'; toolSearchPercent?: number; refresh?: string[]; fallbackModel?: string; fallbackPercent?: number; workerModel?: string }
type Tool = { name: string; description: string; input_schema: Record<string, unknown> }

let config: Config | undefined
let loaded = false
let missingToolsHint = false
// What must survive a hot reload of this plugin lives in the host's session state (contract: ../types/index.d.ts):
// the model of every agent loop seen in turn.step, so an agent's own compaction can tell a bridge model from a
// subscription one (`$.session.model()` answers for the main loop only); the conversation of each workflow agent
// that runs on a bridge model (a workflow script's agents are not readable through `$.session.messages`: the prompt
// from `agent.spawn`, our own answers, and tool results from `tool.call`); and what applyWindow changed in the
// environment. Left as module variables, because losing them costs nothing but a re-read: `config`, the remembered
// reasoning (`thinkingStash`, only continuity of thinking) and the per-tool approvals (a reload asks again).
type Turn = TrackedAgent['turns'][number]
const ENV_MEMO = { plugin: 'model-mod', key: 'env' } as const
const FALLBACK = { plugin: 'model-mod', key: 'fallback' } as const
const AGENT_MODEL = { plugin: 'model-mod', key: 'agentModel' } as const
const TRACKED = { plugin: 'model-mod', key: 'tracked' } as const

// Agent models are also kept in memory: a failed state write must not lose what this module itself has seen, and a
// failed state read must not be mistaken for "not a bridge model" (callers treat a throw as unknown and never fall
// back to the chain for it). A reload empties the map; the state value then refills it.
const agentModels = new Map<string, string>()
async function agentModelOf($: EngineInterface, agentId: string | undefined): Promise<string | undefined> {
  if (agentId === undefined) return undefined
  const known = agentModels.get(agentId)
  if (known !== undefined) return known
  const stored = (await $.state.get({ ...AGENT_MODEL, id: agentId })).value
  if (stored !== undefined) agentModels.set(agentId, stored)
  return stored
}
// Entries whose state write failed: the state holds an older value for them, so they are never evicted (an evicted
// entry would be refilled from that older value).
const unsynced = new Set<string>()
async function rememberAgentModel($: EngineInterface, agentId: string, model: string): Promise<void> {
  agentModels.delete(agentId)
  agentModels.set(agentId, model)
  if (agentModels.size > 500) {
    for (const id of agentModels.keys()) {
      if (agentModels.size <= 500) break
      if (!unsynced.has(id) && id !== agentId) agentModels.delete(id)
    }
  }
  unsynced.add(agentId) // from before the write starts: a pending write is as unsafe to evict as a failed one
  try {
    await $.state.set({ ...AGENT_MODEL, id: agentId }, model)
    unsynced.delete(agentId)
  } catch { /* the in-memory value stands */ }
}
async function trackedOf($: EngineInterface, agentId: string | undefined): Promise<TrackedAgent | undefined> {
  return agentId === undefined ? undefined : (await $.state.get({ ...TRACKED, id: agentId })).value
}

// Turns the results gathered for the last assistant message into the next user message; true when it changed `t`.
function flushResults(t: TrackedAgent): boolean {
  if (!t.pending.length) return false
  t.turns.push({ role: 'user', content: t.pending.map(id => {
    const r = t.results[id]
    return { type: 'tool_result', tool_use_id: id, content: r?.text || (r ? '(no output)' : 'result unavailable'),
      ...(r?.isError || !r ? { is_error: true } : {}) }
  }) })
  t.pending = []
  t.results = {}
  return true
}
// Context windows (input tokens) of Codex models the CLIProxyAPI registry lists; any other model gets `contextWindow`.
const KNOWN_WINDOWS: Readonly<Record<string, number>> = { 'gpt-5.6-sol': 372_000, 'gpt-5.6-terra': 921_000 }
let pluginOptions: PluginOptions = {}

// The window of a bridge model: the configured one, else the known one, else the default of the options.
function windowOf(c: Config, model: string): number | undefined {
  return c.contextWindows?.[model] ?? (c.defaultWindow === undefined ? undefined : KNOWN_WINDOWS[model] ?? c.defaultWindow)
}
function addModels(c: Pick<Config, 'models'>, ids: readonly unknown[], validateId = true): void {
  for (const id of ids) {
    if (typeof id === 'string' && (!validateId || MODEL_ID.test(id)) && !/claude|anthropic/i.test(id) && !OFFICIAL_ALIAS.test(id) && !c.models.includes(id)) c.models.push(id)
  }
}

// A model the bridge answers for even when the upstream cannot be asked now: the allowlist of the options, the list
// the earlier fetches left in the store (every model the bridge has owned), and legacy picker rows this mod previously wrote
// (a row the user chose must never fall through to the subscription endpoint because the upstream was down at start).
// With an allowlist the allowlist alone decides; the cached and picker models outside it are only remembered, so that
// choosing one is refused here instead of being sent to the subscription endpoint under a model name from this mod.
async function seedModels($: EngineInterface, c: Config): Promise<void> {
  const known: unknown[] = []
  try {
    const cached = await $.store.get('models')
    if (Array.isArray(cached)) known.push(...cached)
    const image = await $.store.get('imageModel')
    if (c.imageAuto && c.imageModel === undefined && typeof image === 'string' && MODEL_ID.test(image) && !/claude|anthropic/i.test(image)) c.imageModel = image
  } catch { /* nothing cached */ }
  try {
    const picker = (await $.settings.read()).modelPicker as { options?: unknown } | undefined
    if (Array.isArray(picker?.options)) {
      known.push(...picker.options.filter((row): row is { model: string } => typeof row === 'object' && row !== null &&
        (row as { description?: unknown }).description === ROW_MARK).map(row => row.model))
    }
  } catch { /* no picker rows */ }
  if (!c.explicitModels) {
    addModels(c, known)
    return
  }
  c.excluded = new Set(known.filter((id): id is string => typeof id === 'string' && MODEL_ID.test(id) &&
    !/claude|anthropic/i.test(id) && !OFFICIAL_ALIAS.test(id) && !c.models.includes(id)))
}

// Asks the upstream which models it serves (OpenAI-style /v1/models) and keeps the chat ones. A failure changes
// nothing: the models already known stay the bridge's own.
async function refreshModels($: EngineInterface, c: Config): Promise<string> {
  if (c.key === undefined) return 'no key in the options'
  try {
    const fetched = await modelList($, c.baseUrl, c.key)
    if ('error' in fetched) return fetched.error
    const { ids, chat } = fetched
    if (!c.explicitModels) {
      addModels(c, chat)
      await $.store.set('models', c.models.slice(-MODEL_CACHE_CAP))
    }
    if (c.imageModel === undefined && c.imageAuto) {
      c.imageModel = ids.find(id => id === 'gpt-image-2') ?? ids.find(id => /^gpt-image/.test(id))
      if (c.imageModel !== undefined) await $.store.set('imageModel', c.imageModel)
    }
    return `${chat.length} models`
  } catch {
    return 'unreachable'
  }
}

// The configuration the plugin's `userConfig` fields give (set through `claude plugin install --config`, `claude plugin
// configure` or the configuration dialog). undefined: no key is set; null: a key is set but cannot be used, which
// leaves the mod inert (it does not fall back to a configuration file).
function optionsCandidate(o: PluginOptions): Record<string, unknown> | undefined | null {
  const text = (name: string) => typeof o[name] === 'string' ? (o[name] as string).trim() : ''
  const baseUrl = text('baseUrl') || DEFAULT_BASE_URL
  const key = o.apiKey
  if (key === undefined || key === null || key === '') return undefined
  // The key reaches curl in a configuration line; keep it to what cannot break out of it. It is not trimmed:
  // surrounding whitespace or a newline is refused, not silently removed.
  if (typeof key !== 'string' || key.length > 512 || !/^[\x21\x23-\x5b\x5d-\x7e]+$/.test(key)) return null
  const number = (name: string, fallback: number) => typeof o[name] === 'number' && Number.isFinite(o[name]) ? o[name] as number : fallback
  const side = text('sideModel')
  return { baseUrl, key, models: text('models').split(/[\s,]+/).filter(Boolean), maxTokens: number('maxTokens', 32_000),
    effortMode: text('effortMode') === 'none' ? 'none' : 'suffix', imageModel: text('imageModel') !== 'none' ? text('imageModel') || undefined : undefined, imageAuto: text('imageModel') === '',
    defaultWindow: number('contextWindow', 272_000), sideModel: side === 'none' ? undefined : side || 'claude-haiku-5-5',
    keepThinking: o.keepThinking !== false, localTitle: o.localTitle !== false, localContext: o.localContext !== false,
    toolSearch: text('toolSearch') || 'auto', toolSearchPercent: number('toolSearchPercent', 10),
    fallbackModel: text('fallbackModel'), fallbackPercent: number('fallbackPercent', 100), workerModel: text('workerModel'), promptsDir: text('promptsDir') }
}

// One load at a time: the options and the settings are read once and every caller gets the same answer.
let loading: Promise<Config | undefined> | undefined
function load($: EngineInterface): Promise<Config | undefined> {
  return loading ??= loadNow($)
}

async function loadNow($: EngineInterface) {
  if (loaded) return config
  // No throws escape configuration loading: missing/invalid config is inert.
  try {
    // The plugin's own options first; an optional configuration file named by MODEL_MOD_CONFIG next.
    const given = optionsCandidate(pluginOptions)
    if (given === null) {
      $.ui.status('model-mod: the apiKey option holds characters that cannot be used; mod is inert.')
      return undefined
    }
    const fromOptions = given !== undefined
    let candidate: Record<string, any>  // eslint-disable-line @typescript-eslint/no-explicit-any
    if (given !== undefined) {
      candidate = given
    } else {
      const path = await $.env.get('MODEL_MOD_CONFIG')
      if (!path) return undefined
      candidate = JSON.parse(await $.fs.read(path))
    }
    if (typeof candidate.baseUrl !== 'string' || typeof (fromOptions ? candidate.key : candidate.headerFile) !== 'string' ||
        (candidate.toolsFile !== undefined && typeof candidate.toolsFile !== 'string') || !Array.isArray(candidate.models) ||
        !candidate.models.every((m: unknown) => typeof m === 'string' && m.length > 0 && !/claude|anthropic/i.test(m)) ||
        !Number.isInteger(candidate.maxTokens) || candidate.maxTokens <= 0) return undefined
    const url = new URL(candidate.baseUrl)
    const host = url.hostname.toLowerCase().replace(/\.$/, '')
    if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password || url.search || url.hash ||
        !/^(\[[0-9a-f:.]+\]|[a-z0-9_]([a-z0-9._-]*[a-z0-9_])?)$/.test(host) ||
        ['anthropic.com', 'claude.ai'].some(d => host === d || host.endsWith(d))) {
      $.ui.status('model-mod: refused upstream host; mod is inert.')
      return undefined
    }
    const built: Config = { ...candidate, prompts: await loadPrompts($, candidate.promptsDir),
      promptsDir: promptDir(candidate.promptsDir), baseUrl: url.origin + url.pathname.replace(/\/+$/, ''), maxTokens: candidate.maxTokens as number,
      explicitModels: candidate.models.length > 0, imageAuto: fromOptions && candidate.imageAuto === true,
      source: fromOptions ? 'options' : 'file',
      defaultWindow: fromOptions && Number.isInteger(candidate.defaultWindow) && (candidate.defaultWindow as number) >= 32_000 &&
        (candidate.defaultWindow as number) <= 4_000_000 ? candidate.defaultWindow as number : undefined,
      key: fromOptions ? candidate.key as string : undefined,
      headerFile: fromOptions ? undefined : candidate.headerFile as string,
      toolsFile: typeof candidate.toolsFile === 'string' ? candidate.toolsFile : undefined,
      effortMode: candidate.effortMode === 'suffix' ? 'suffix' : 'none',
      models: [],
      imageModel: typeof candidate.imageModel === 'string' && /^[A-Za-z0-9._-]{1,64}$/.test(candidate.imageModel) &&
        !/claude|anthropic/i.test(candidate.imageModel) ? candidate.imageModel : undefined,
      // argv of an external command that re-captures the tool schemas, run by `/model-mod:refresh`: an absolute path to a
      // program and an absolute path to its script, 4 to 64 strings. Anything else is ignored.
      refresh: Array.isArray(candidate.refresh) && candidate.refresh.length >= 4 && candidate.refresh.length <= 64 &&
        candidate.refresh.every((x: unknown) => typeof x === 'string' && x.length <= 4096 && !x.includes('\0')) &&
        candidate.refresh[0].startsWith('/') && candidate.refresh[1].startsWith('/') ? candidate.refresh : undefined,
      toolSearch: ['auto', 'on', 'off'].includes(candidate.toolSearch) ? candidate.toolSearch : 'auto',
      toolSearchPercent: Number.isInteger(candidate.toolSearchPercent) && candidate.toolSearchPercent >= 1 &&
        candidate.toolSearchPercent <= 90 ? candidate.toolSearchPercent : 10,
      keepThinking: candidate.keepThinking !== false,
      localTitle: candidate.localTitle !== false,
      localContext: candidate.localContext !== false,
      sideModel: typeof candidate.sideModel === 'string' && /^claude-[a-z0-9.-]{1,60}$/.test(candidate.sideModel) ? candidate.sideModel : undefined,
      contextWindows: Object.fromEntries(Object.entries((candidate.contextWindows ?? {}) as Record<string, number>)
        .filter(([id, n]) => candidate.models.includes(id) && Number.isInteger(n) && n >= 32_000 && n <= 4_000_000)) }
    // Config IDs already passed the validation above; preserve their existing accepted syntax.
    addModels(built, candidate.models, false)
    await seedModels($, built)
    // The models the mod switches the session to when the subscription's limit is reached (`fallbackModel`) and runs the
    // `local-worker` agent type on (`workerModel`, else the fallback model). Options only; off when empty. Each must be
    // one of this mod's own models: inside the allowlist when there is one, never a Claude ID.
    const usable = (name: string): string | undefined => {
      const id = fromOptions && typeof candidate[name] === 'string' ? candidate[name] : ''
      if (id === '') return undefined
      if (!built.explicitModels) addModels(built, [id])
      if (!MODEL_ID.test(id) || !built.models.includes(id)) {
        $.ui.status(`model-mod: ${name} is not a model of this mod (it must be in the allowlist); that feature is off.`)
        return undefined
      }
      return id
    }
    built.fallbackModel = usable('fallbackModel')  // `candidate` was spread into `built`; only a checked value stays
    built.workerModel = usable('workerModel')
    built.fallbackPercent = typeof candidate.fallbackPercent === 'number' && Number.isFinite(candidate.fallbackPercent)
      ? Math.min(100, Math.max(50, candidate.fallbackPercent)) : 100
    config = built
    return built
  } catch {
    return undefined
  } finally {
    loaded = true
  }
}

// The client's built-in tools with their input schemas: from the capture file (`toolsFile`) when one is configured;
// otherwise the names and descriptions the engine lists now with an open object schema (the engine gives a plugin no
// input schema, and none is shipped with this plugin; the tool's own validation names a wrong argument and the model
// corrects itself).
async function capturedTools($: EngineInterface, c: Config): Promise<Tool[] | undefined> {
  if (c.toolsFile !== undefined) {
    try {
      const captured = JSON.parse(await $.fs.read(c.toolsFile)).tools
      if (!Array.isArray(captured)) throw new Error('tools')
      return captured
    } catch {
      if (!missingToolsHint) {
        missingToolsHint = true
        $.ui.status('model-mod: no tool schemas; toolsFile could not be read (run /model-mod:refresh if refresh is configured).')
      }
      return undefined
    }
  }
  return (await $.tool.list()).filter(tool => !tool.mcp).map(tool => ({
    name: tool.name, description: tool.description, input_schema: { type: 'object', additionalProperties: true } }))
}

// Tool names a conversation has loaded through tool_search (the result's first line names them) or already called.
// Read from the history itself, so a reload, a compaction or another agent's own history needs no extra state.
function loadedFrom(history: readonly Turn[]): Set<string> {
  const names = new Set<string>()
  const searches = new Set<string>()
  for (const message of history) {
    for (const block of message.content) {
      if (block.type === 'tool_use' && typeof block.name === 'string') {
        names.add(block.name)
        if (block.name === TOOL_SEARCH_TOOL && typeof block.id === 'string') searches.add(block.id)
      } else if (block.type === 'tool_result' && typeof block.tool_use_id === 'string' && searches.has(block.tool_use_id)) {
        const content = block.content
        const text = typeof content === 'string' ? content : Array.isArray(content)
          ? content.map(part => typeof part?.text === 'string' ? part.text : '').join('\n') : ''
        const line = /^Loaded tools: (.*)$/m.exec(text)
        if (line) for (const name of line[1]!.split(',')) names.add(name.trim())
      }
    }
  }
  return names
}

// The window input_tokens of a tool list is measured against when deciding to defer MCP tools: the model's own.
async function tools($: EngineInterface, c: Config, model: string, history: readonly Turn[]): Promise<Tool[]> {
  const captured = await capturedTools($, c)
  if (!captured) return []
  const live = await $.tool.list()
  const enabled = new Set(live.map(tool => tool.name))
  // The built-in WebSearch/WebFetch run a side request that names the session model; for a local model it
  // would go to the subscription endpoint, so the bridge's own two tools replace them.
  const offered: Tool[] = captured.filter(tool => enabled.has(tool.name) && tool.name !== 'WebSearch' && tool.name !== 'WebFetch').map(({ name, description, input_schema }) =>
    ({ name, description, input_schema }))
  // The engine gives a plugin no input schema for an MCP tool; one in the capture file is used, any other is
  // offered with its description and an open object schema (the server's own validation names the arguments).
  const have = new Set(offered.map(tool => tool.name))
  if (c.imageModel && enabled.has(IMAGE_TOOL)) {
    offered.push({ name: IMAGE_TOOL, description: IMAGE_SPEC.description, input_schema: IMAGE_SPEC.inputSchema })
    have.add(IMAGE_TOOL)
  }
  for (const [name, spec] of [[WEB_SEARCH_TOOL, WEB_SEARCH_SPEC], [WEB_FETCH_TOOL, WEB_FETCH_SPEC]] as const) {
    if (enabled.has(name)) offered.push({ name, description: spec.description, input_schema: spec.inputSchema })
    have.add(name)
  }
  have.add(TOOL_SEARCH_TOOL)  // offered only when MCP tools are listed by name (below)
  for (const tool of live) {
    if (!tool.mcp || have.has(tool.name) || !/^[A-Za-z0-9_-]{1,64}$/.test(tool.name)) continue
    offered.push({ name: tool.name, description: tool.description.slice(0, 2000),
      input_schema: { type: 'object', additionalProperties: true } })
  }
  // Like the client's own tool search: when the MCP tools' schemas are more than a tenth of the window (or the mode
  // is `on`), only their names are offered and the model loads schemas through tool_search. Tools the conversation
  // has already loaded or called keep their schema.
  const mode = c.toolSearch ?? 'auto'
  const mcpTools = offered.filter(tool => tool.name.startsWith('mcp__') && !tool.name.startsWith('mcp__model-mod__'))
  if (mode === 'off' || mcpTools.length === 0) return offered
  const window = windowOf(c, model) ?? 200_000
  const estimate = Math.ceil(JSON.stringify(mcpTools).length / 4)
  if (mode === 'auto' && estimate <= window * (c.toolSearchPercent ?? 10) / 100) return offered
  const loadedNames = loadedFrom(history)
  const held = new Set(mcpTools.filter(tool => !loadedNames.has(tool.name)).map(tool => tool.name))
  const listing = [...held].slice(0, 400).join(', ') + (held.size > 400 ? `, … (${held.size - 400} more)` : '')
  return [...offered.filter(tool => !held.has(tool.name)), {
    name: TOOL_SEARCH_TOOL,
    description: TOOL_SEARCH_SPEC.description + (held.size ? ` Tools not loaded yet: ${listing}.` : ' Every tool is loaded.'),
    input_schema: TOOL_SEARCH_SPEC.inputSchema }]
}

// CLIProxyAPI reads a trailing `(level)` on the model name as the reasoning effort (`output_config.effort` and
// `thinking.budget_tokens` were measured to have no effect). It clamps a level the model does not declare, so the
// client's level is sent as it is, `max` included.
function wireModel(c: Config, e: TurnStepInput): string {
  if (c.effortMode !== 'suffix' || typeof e.effort !== 'string') return e.model
  return ['low', 'medium', 'high', 'xhigh', 'max'].includes(e.effort) ? `${e.model}(${e.effort})` : e.model
}

const IMAGE_SPEC = {
  name: 'generate_image',
  description: 'Generate an image from a text prompt with the local image model and save it as a PNG file in the working ' +
    'directory. Returns the file path; open it with the Read tool to look at it. Only usable while a local model is selected.',
  inputSchema: { type: 'object', additionalProperties: false, required: ['prompt'], properties: {
    prompt: { type: 'string', description: 'What the image should show.' },
    size: { type: 'string', enum: ['1024x1024', '1536x1024', '1024x1536', 'auto'], description: 'Default 1024x1024.' },
    quality: { type: 'string', enum: ['low', 'medium', 'high', 'auto'], description: 'Default medium.' },
    path: { type: 'string', description: 'Relative .png path inside the working directory; default generated-images/<time>.png.' },
  } },
  isDeferred: false,
}
const IMAGE_TOOL = 'mcp__model-mod__generate_image'
const TOOL_SEARCH_TOOL = 'mcp__model-mod__tool_search' as typeof IMAGE_TOOL
const TOOL_SEARCH_SPEC = {
  name: 'tool_search',
  description: 'Load tools that are listed by name only. Their schemas are not in this request: call tool_search with ' +
    '"select:<name>,<name>" to load tools by exact name, or with keywords to search names and descriptions; the ' +
    'loaded tools can be called from the next step on. Do not call an unloaded tool before loading it. ' +
    'Only usable while a local model is selected.',
  inputSchema: { type: 'object', additionalProperties: false, required: ['query'], properties: {
    query: { type: 'string', description: '"select:<exact name>,<exact name>" or keywords.' },
    max_results: { type: 'integer', minimum: 1, maximum: 20, description: 'Keyword search only; default 5.' },
  } },
  isDeferred: false,
}
// Cast: the generated declarations list a registered tool only once the engine has seen it registered.
const WEB_SEARCH_TOOL = 'mcp__model-mod__web_search' as typeof IMAGE_TOOL
const WEB_FETCH_TOOL = 'mcp__model-mod__web_fetch' as typeof IMAGE_TOOL
const WEB_SEARCH_SPEC = {
  name: 'web_search',
  description: 'Search the web with the local model provider\'s own search and return an answer with source links. ' +
    'Only usable while a local model is selected, where it replaces the built-in WebSearch. ' +
    'With any other model use the built-in WebSearch instead.',
  inputSchema: { type: 'object', additionalProperties: false, required: ['query'], properties: {
    query: { type: 'string', description: 'The search query.' },
    allowed_domains: { type: 'array', items: { type: 'string' }, description: 'Only use results from these domains.' },
  } },
  isDeferred: false,
}
const WEB_FETCH_SPEC = {
  name: 'web_fetch',
  description: 'Fetch an http or https URL and return its text (HTML is converted to plain text, first 60000 characters). ' +
    'Only usable while a local model is selected, where it replaces the built-in WebFetch. ' +
    'With any other model use the built-in WebFetch instead.',
  inputSchema: { type: 'object', additionalProperties: false, required: ['url'], properties: {
    url: { type: 'string', description: 'The http or https URL to fetch.' },
  } },
  isDeferred: false,
}
const PRIVATE_HOST = /^(localhost|.*\.local|.*\.internal|127\..*|10\..*|192\.168\..*|172\.(1[6-9]|2\d|3[01])\..*|169\.254\..*|0\..*|\[.*\])$/i
const PRIVATE_FETCH = 'web_fetch does not fetch local or private addresses; use Bash for those.'
const IPV4_ADDRESS = /^(?:0|[1-9]\d{0,2})(?:\.(?:0|[1-9]\d{0,2})){3}$/

// DNS answers are untrusted too. URL canonicalises IPv6 (including dotted mapped IPv4); malformed answers fail closed.
function privateAddress(address: string): boolean {
  if (/^\d+\.\d+\.\d+\.\d+$/.test(address)) {
    const bytes = address.split('.').map(Number)
    if (!IPV4_ADDRESS.test(address) || bytes.some(b => b > 255)) return true
    const [a, b] = bytes as [number, number, number, number]
    return a === 0 || a === 10 || a === 127 || a >= 224 ||
      (a === 100 && b >= 64 && b <= 127) || (a === 169 && b === 254) ||
      (a === 172 && b >= 16 && b <= 31) || (a === 192 && b === 168)
  }
  let host: string
  try { host = new URL(`http://[${address}]/`).hostname.slice(1, -1) } catch { return true }
  const halves = host.split('::').map(part => part ? part.split(':').map(word => parseInt(word, 16)) : [])
  const words = halves.length === 1 ? halves[0]! :
    [...halves[0]!, ...Array<number>(8 - halves[0]!.length - halves[1]!.length).fill(0), ...halves[1]!]
  const mappedOrCompatible = words.slice(0, 5).every(w => w === 0) && (words[5] === 0xffff || words[5] === 0)
  const siit = words.slice(0, 4).every(w => w === 0) && words[4] === 0xffff && words[5] === 0
  const isatap = words.slice(0, 5).every(w => w === 0) && words[5] === 0x5efe
  const nat64 = words[0] === 0x64 && words[1] === 0xff9b && words.slice(2, 6).every(w => w === 0)
  // 64:ff9b:1::/48 is the local-use NAT64 prefix: its embedded IPv4 is not defined by the standard, so fail closed.
  if (words[0] === 0x64 && words[1] === 0xff9b && words[2] === 1) return true
  if (mappedOrCompatible || siit || isatap || nat64 || words[0] === 0x2002) {
    const [high, low] = words[0] === 0x2002 ? words.slice(1, 3) : words.slice(6)
    return privateAddress(`${high! >>> 8}.${high! & 255}.${low! >>> 8}.${low! & 255}`)
  }
  return words.every(w => w === 0) || (words.slice(0, 7).every(w => w === 0) && words[7] === 1) ||
    (words[0]! & 0xfe00) === 0xfc00 || (words[0]! & 0xffc0) === 0xfe80 || (words[0]! & 0xffc0) === 0xfec0 || (words[0]! & 0xff00) === 0xff00
}

async function resolveHost($: EngineInterface, host: string): Promise<string[] | undefined> {
  if (host.startsWith('-')) return undefined
  try {
    // Hooks have no Node process; the resolver is chosen by the system name, not by falling back when a lookup fails.
    const system = await $.process.run(['uname', '-s'], { timeoutMs: 10_000 })
    if (system.exitCode !== 0 || system.isStdoutTruncated) return undefined
    const platform = system.stdout.trim()
    if (platform !== 'Darwin' && platform !== 'Linux') return undefined
    const mac = platform === 'Darwin'
    const dns = await $.process.run(mac ? ['dscacheutil', '-q', 'host', '-a', 'name', host] : ['getent', 'ahosts', host], { timeoutMs: 10_000 })
    if (dns.exitCode !== 0 || dns.isStdoutTruncated) return undefined
    const addresses: string[] = []
    for (const line of dns.stdout.split(/\r?\n/).map(line => line.trim()).filter(Boolean)) {
      if (mac && /^(?:name:\s*\S+|alias:\s*\S+(?:\s+\S+)*)$/.test(line)) continue
      const row = mac ? /^(ip_address|ipv6_address):\s*(\S+)$/.exec(line) :
        /^(\S+)\s+(?:STREAM|DGRAM|RAW)(?:\s+\S+)?$/.exec(line)
      if (!row) return undefined
      const address = row[mac ? 2 : 1]!
      if (mac && (row[1] === 'ipv6_address') !== address.includes(':')) return undefined
      if (address.includes(':')) {
        if (!/^[0-9a-f:.]+$/i.test(address)) return undefined
        try { new URL(`http://[${address}]/`) } catch { return undefined }
      } else if (!IPV4_ADDRESS.test(address) || address.split('.').some(byte => Number(byte) > 255)) return undefined
      addresses.push(address)
    }
    return addresses.length ? addresses : undefined
  } catch { return undefined }
}

function fetchResponse(stdout: string): { status: number; location?: string; body: string } | undefined {
  let rest = stdout
  for (;;) {
    const status = /^HTTP\/\S+\s+(\d{3})[^\r\n]*\r?\n/.exec(rest)
    const end = /\r?\n\r?\n/.exec(rest)
    if (!status || !end) return undefined
    const headers = rest.slice(0, end.index)
    rest = rest.slice(end.index + end[0].length)
    // Only the final response's headers and body count, not 100 Continue / 103 Early Hints.
    if (Number(status[1]) < 200) continue
    return { status: Number(status[1]), location: /(?:^|\r?\n)location:[ \t]*([^\r\n]*)/i.exec(headers)?.[1]?.trim(), body: rest }
  }
}

// A tool a hook answers never reaches the engine's permission prompt (the prompt belongs to the core step after the
// hooks), so the replacements for WebSearch/WebFetch and generate_image ask here with the engine's own verdict: an allow
// rule or bypass mode lets the call through, a deny rule refuses, anything else asks the person. `-p` has nobody to ask.
const RETRY_DELAYS = [2000, 6000, 15000]
// The engine's transcript does not keep the signed reasoning a bridge response carries (a mod cannot record a thinking
// block), so it is remembered here by the first tool call it came with and handed back inside the tool loop, which lets the
// model continue its reasoning instead of starting over. Only blocks whose signature has the shape the API returns for
// Codex reasoning (an OpenAI encrypted item) are kept; anything else is dropped as before.
const CODEX_SIGNATURE = /^gAAAA/
type Thinking = { type: 'thinking'; thinking: string; signature: string }
const thinkingStash = new Map<string, Thinking[]>()
function stashThinking(toolId: string | undefined, blocks: Thinking[]): void {
  const usable = blocks.filter(b => CODEX_SIGNATURE.test(b.signature))
  if (toolId === undefined || usable.length === 0) return
  if (thinkingStash.size >= 300) thinkingStash.delete(thinkingStash.keys().next().value as string)
  thinkingStash.set(toolId, usable)
}
const approvedTools = new Set<string>()
async function permitted($: EngineInterface, e: { tool: string }, tool: string, what: string): Promise<string | undefined> {
  if (approvedTools.has(tool)) return undefined
  const { tool: _name, tool_use_id: _id, agentId: _agent, ...input } = e as unknown as Record<string, unknown>
  let verdict: { decision: string; reason?: string } = { decision: 'ask' }
  try { verdict = await $.tool.check({ tool, input } as never) } catch { /* ask the person */ }
  if (verdict.decision === 'allow') return undefined
  if (verdict.decision === 'deny') return verdict.reason ?? `${tool} is not permitted.`
  const always = 'Yes, and do not ask again this session'
  try {
    const answer = await $.ui.ask(what, ['Yes', always, 'No'])
    if (answer === always) approvedTools.add(tool)
    return answer === 'Yes' || answer === always ? undefined : 'The user declined this tool call.'
  } catch {
    return `${tool} needs the user's approval and nobody could be asked.`
  }
}

// The model of the loop a tool call came from, when it is a bridge model.
async function bridgeModel($: EngineInterface, e: { agentId?: string }, c: Config): Promise<string | undefined> {
  const model = e.agentId === undefined ? await $.session.model() : await agentModelOf($, e.agentId)
  return model !== undefined && c.models.includes(model) ? model : undefined
}

// The model's context window is the engine's to know; an unlisted model is assumed to have 200k. A bridge model
// gets its real window through the variable the engine reads for that, and the original value is put back for any
// other model.
// The client's own side requests (the session title, token counts) name the session model unless a small-model variable
// is set, which for a local model would send its ID to the subscription endpoint. While a local model is selected the
// variable names a Claude model instead (`sideModel`, the user's own value wins); the original is put back afterwards.
// Both originals and what was applied are kept in session state (a missing key: not read / not applied; null: unset),
// because the environment itself outlives a reload of this plugin and a forgotten original would be read back as the
// value this mod had set.
// Calls are chained: two overlapping applyWindow runs would both read an unset memo and the second would take the
// first one's value for the original.
let windowQueue: Promise<unknown> = Promise.resolve()
let envUncertain = false
function applyWindow($: EngineInterface, c: Config, model: string): Promise<void> {
  const run = windowQueue.then(() => applyWindowNow($, c, model))
  windowQueue = run.catch(() => undefined)
  return run
}
async function applyWindowNow($: EngineInterface, c: Config, model: string): Promise<void> {
  const local = c.models.includes(model)
  const window = local ? windowOf(c, model) : undefined
  const memo: EnvMemo = { ...(await $.state.get(ENV_MEMO)).value }
  // 1. the originals, saved before anything is changed
  // (once an original is stored the variable counts as touched, whatever the applied* record says)
  const needWindow = window !== undefined || memo.originalWindow !== undefined
  const needSide = c.sideModel !== undefined && (local || memo.originalSide !== undefined)
  let read = false
  if (needWindow && memo.originalWindow === undefined) {
    memo.originalWindow = (await $.env.get('CLAUDE_CODE_MAX_CONTEXT_TOKENS')) ?? null
    read = true
  }
  if (needSide && memo.originalSide === undefined) {
    memo.originalSide = (await $.env.get('ANTHROPIC_SMALL_FAST_MODEL')) ?? null
    read = true
  }
  if (read) await $.state.set(ENV_MEMO, memo)
  // 2. the environment is changed, and only a write that succeeded is recorded as applied, so a failure is retried
  // While `envUncertain` the record may not match the environment (a write threw, or the record was not saved), so
  // the applied* comparison is not trusted and every wanted value is written again.
  const next: EnvMemo = { ...memo }
  const wantWindow = needWindow ? (window === undefined ? memo.originalWindow! : String(window)) : undefined
  const wantSide = needSide ? (local ? memo.originalSide ?? c.sideModel! : memo.originalSide!) : undefined
  const writeWindow = wantWindow !== undefined && (envUncertain || wantWindow !== memo.appliedWindow)
  const writeSide = wantSide !== undefined && (envUncertain || wantSide !== memo.appliedSide)
  if (!writeWindow && !writeSide) return
  envUncertain = true
  if (writeWindow) {
    await $.env.set('CLAUDE_CODE_MAX_CONTEXT_TOKENS', wantWindow ?? undefined)
    next.appliedWindow = wantWindow
  }
  if (writeSide) {
    await $.env.set('ANTHROPIC_SMALL_FAST_MODEL', wantSide ?? undefined)
    next.appliedSide = wantSide
  }
  await $.state.set(ENV_MEMO, next)
  envUncertain = false
}

// POSTs the images/generations request (body on stdin) and writes the first returned image to "$3", printing its
// size. The response never passes through the engine, whose process output is capped at 4 MiB (a large PNG as base64
// is not). The JSON is read with tr/grep/sed/base64 (whitespace removed, the first "b64_json" string taken, `\/`
// unescaped): enough for the response of an images endpoint. Any failing stage fails the whole call; the image is
// written to a private temporary file next to the target and only a complete one is renamed into place.
const IMAGE_PIPELINE = [
  'set -o pipefail',
  'out=$3; dir=$(dirname -- "$out") || exit 1',
  'mkdir -p -- "$dir" || exit 1',
  'tmp=$(mktemp -- "$dir/.model-mod-image.XXXXXX") || exit 1',
  'trap \'rm -f -- "$tmp"\' EXIT',
  // The key (options mode, `$1` empty) is given to curl as a configuration line from a process substitution, which
  // must be an argument of curl's own command line: an array assignment would close it before curl starts.
  'fetch() {',
  '  if [ -z "$1" ]; then',
  '    curl -g -sS --fail-with-body --max-time 280 -K <(printf \'header = "Authorization: Bearer %s"\\n\' "$MODEL_MOD_KEY") -H "content-type: application/json" --data-binary @- "$2"',
  '  else',
  '    curl -g -sS --fail-with-body --max-time 280 -H @"$1" -H "content-type: application/json" --data-binary @- "$2"',
  '  fi',
  '}',
  'fetch "$1" "$2" |' +
    ' tr -d \' \\t\\r\\n\' | grep -o \'"b64_json":"[^"]*"\' | sed -n \'1{s/^"b64_json":"//;s/"$//;s|\\\\/|/|g;p;}\' |' +
    ' base64 -d > "$tmp"',
  'status=$?',
  'if [ "$status" -ne 0 ] || [ ! -s "$tmp" ]; then echo "no image in the response"; exit 1; fi',
  'chmod "$(printf \'%03o\' $(( 0666 & ~0$(umask) )))" "$tmp" && mv -f -- "$tmp" "$out" || exit 1',
  'wc -c < "$out"',
].join('\n')

// curl with the configured authorisation, so no call site cares where the key comes from. A key from the plugin's
// options never enters an argument vector: it travels in the child's environment and bash turns it into a curl
// configuration line read from a pipe. A header file named in the configuration file is given to curl as `-H @file`. URL globbing is off
// (`-g`) so that a base URL is one request to one host.
const KEY_CURL = 'exec curl -g -K <(printf \'header = "Authorization: Bearer %s"\\n\' "$MODEL_MOD_KEY") "$@"'
// Text that came from the upstream or from an exception, with the key (and anything shaped like a bearer token)
// removed before it is shown or kept in the conversation: an upstream may echo the credential it was given.
// `escaped` is true for raw bodies and messages, which may carry JSON escapes; text that was already parsed from JSON is
// masked as it is (decoding it again would turn a literal `\t` in a summary into a tab).
function scrub(c: Config | undefined, text: string, escaped = true): string {
  const echoes = new Set<string>()
  let percentEcho: RegExp | undefined
  if (c?.key) {
    echoes.add(c.key)
    // Percent-encoding is matched per character: any character may appear literally or as `%XX` in either hex case,
    // so a mix (`%74oken%2fsecret`) is masked as well as the canonical `encodeURIComponent` form.
    if (/^[\x21-\x7e]+$/.test(c.key)) {
      const hex = (d: string) => /[a-f]/i.test(d) ? `[${d.toLowerCase()}${d.toUpperCase()}]` : d
      const unit = (ch: string) => `(?:${ch.replace(/[\\^$.*+?()[\]{}|/-]/g, '\\$&')}|%${(ch.charCodeAt(0) + 0x100).toString(16).slice(1).split('').map(hex).join('')})`
      percentEcho = new RegExp([...c.key].map(unit).join(''), 'g')
    }
    for (let offset = 0; offset < 3; offset++) {
      // Keep only characters whose six bits come entirely from the key, independent of surrounding bytes or padding.
      const fragment = btoa('x'.repeat(offset) + c.key).slice(Math.ceil(offset * 8 / 6), Math.floor((offset + c.key.length) * 8 / 6))
      if (fragment) {
        echoes.add(fragment)
        echoes.add(fragment.replace(/\+/g, '-').replace(/\//g, '_'))
      }
    }
  }
  const variants = [...echoes].sort((a, b) => b.length - a.length)
  // An upstream that echoes the key as JSON may have escaped it (`\/`, `\u0073`): the key is masked in the raw text and in
  // the text decoded once (one pass, so that a decoded backslash is not combined with the next character).
  const mask = (t: string) => variants.reduce((out, key) => out.split(key).join('[key]'), percentEcho ? t.replace(percentEcho, '[key]') : t)
  const decoded = !escaped ? mask(text) : mask(text).replace(/\\(?:u([0-9a-fA-F]{4})|(["\\/bfnrt]))/g, (_m, hex: string | undefined, ch: string | undefined) =>
    hex !== undefined ? String.fromCharCode(parseInt(hex, 16)) :
      ({ b: '\b', f: '\f', n: '\n', r: '\r', t: '\t' } as Record<string, string>)[ch!] ?? ch!)
  return mask(decoded).replace(/\bBearer\s+\S+/gi, 'Bearer [key]').replace(/\bsk-[A-Za-z0-9_-]{6,}/g, '[key]')
}
function curlCall(c: Config, args: readonly string[]): { argv: string[]; env?: Record<string, string> } {
  if (c.key !== undefined) return { argv: ['bash', '-c', KEY_CURL, 'bash', ...args], env: { MODEL_MOD_KEY: c.key } }
  return { argv: ['curl', '-g', '-H', '@' + c.headerFile, ...args] }
}
function curlRun($: EngineInterface, c: Config, args: readonly string[], init: { stdin?: string; timeoutMs?: number }) {
  const call = curlCall(c, args)
  return $.process.run(call.argv, { ...init, ...(call.env ? { env: call.env } : {}) })
}

function* failure(e: TurnStepInput, reason: string, index = 0): Generator<TurnStepChunk, TurnStepResult> {
  const answer = `model-mod: ${reason}.`
  const usage = { model: e.model, input_tokens: 0, output_tokens: 0,
    cache_read_input_tokens: 0, cache_creation_input_tokens: 0 }
  yield { kind: 'text', index, text: answer }
  yield { kind: 'stop', stopReason: 'end_turn', usage }
  return { turnId: e.turnId, index: e.index, answer, toolUses: [], stopReason: 'end_turn', usage }
}


const PROMPT_NAMES = ['compact', 'title', 'subagent-note', 'worker'] as const
type PromptName = typeof PROMPT_NAMES[number]
type Prompts = { text: Partial<Record<PromptName, string>>; files: PromptName[] }

// Only fixed filenames are joined to absolute directories without traversal segments.
function promptDir(value: unknown): string | undefined {
  if (typeof value !== 'string' || !value.startsWith('/') || /[\\\0]/.test(value) ||
      value.split('/').some(part => part === '..' || part === '.')) return undefined
  return value.replace(/\/+$/, '') || '/'
}

async function loadPrompts($: EngineInterface, custom: unknown): Promise<Prompts> {
  let root: string | undefined
  try { root = promptDir($.plugin.root) } catch { /* some clients may not expose the root */ }
  const dir = promptDir(custom) ?? (root ? root.replace(/\/+$/, '') + '/prompts' : undefined)
  const prompts: Prompts = { text: {}, files: [] }
  await Promise.all(PROMPT_NAMES.map(async name => {
    if (dir === undefined) return
    try {
      // Bound an unreadable/slow file at config load; requests only use the cached strings.
      const raw = await Promise.race([
        $.fs.read(dir.replace(/\/+$/, '') + '/' + name + '.md'),
        $.clock.sleep(1000).then(() => undefined),
      ])
      if (typeof raw !== 'string' || raw.length > 8000 || raw.includes('\0') || !raw.trim()) return
      prompts.text[name] = raw.replace(/[\r\n]+$/, '')
      prompts.files.push(name)
    } catch { /* this prompt is unavailable */ }
  }))
  return prompts
}

function promptStatus(prompts: Prompts): string {
  return `prompts files=${PROMPT_NAMES.filter(name => prompts.files.includes(name)).join(',') || 'none'}; missing=${PROMPT_NAMES.filter(name => !prompts.files.includes(name)).join(',') || 'none'}`
}

async function registerWorker($: EngineInterface, c: Config): Promise<void> {
  const worker = c.workerModel ?? c.fallbackModel
  if (worker !== undefined && c.prompts.text.worker !== undefined) {
    try {
      await $.agent.register({ name: 'local-worker', model: worker,
        description: `Runs a delegated task on the local model ${worker} (through the user's own upstream). Use it for work the user wants done on the local model.`,
        prompt: c.prompts.text.worker })
    } catch { /* the agent type is optional */ }
  }
}

const MAX_TRANSCRIPT = 600_000

function clip(text: string | undefined, max: number): string {
  const t = text ?? ''
  return t.length > max ? t.slice(0, max) + `… [${t.length - max} chars omitted]` : t
}

function renderTranscript(messages: readonly SessionMessage[]): string {
  const parts: string[] = []
  for (const m of messages) {
    const lines = [`## ${m.role}`, clip(m.text, 20_000)]
    for (const use of m.toolUses ?? []) {
      lines.push(`[tool ${use.tool}] ${clip(JSON.stringify(use.input), 1_000)}` +
        (use.text !== undefined ? `\n[result${use.isError ? ' (error)' : ''}] ${clip(use.text, 1_500)}` : ''))
    }
    for (const r of m.toolResults ?? []) lines.push(`[tool result] ${clip(r.text, 1_500)}`)
    parts.push(lines.join('\n'))
  }
  const all = parts.join('\n\n')
  return all.length > MAX_TRANSCRIPT ? '[earlier part omitted]\n' + all.slice(all.length - MAX_TRANSCRIPT) : all
}

let fallbackHinted = false
// Called when a turn of the main loop has ended. While a subscription model is selected and a rate-limit window the
// last response reported is used up (and not yet reset), the session switches to `fallbackModel` with the client's own
// `/model` command (this session only); once the window has reset it switches back. A model the person chose by hand
// is never changed. Returns the notice to show, if any. The turn that hit the limit is not repeated: it already failed.
async function autoFallback($: EngineInterface, c: Config): Promise<string | undefined> {
  const model = await $.session.model()
  const memo: FallbackMemo = { ...(await $.state.get(FALLBACK)).value }
  const now = await $.clock.now()
  // A switch this mod made (`memo.to`, kept in the state so that a changed setting or a reload does not lose it).
  if (memo.from !== undefined && memo.to !== undefined) {
    if (model !== memo.to) {
      // The person chose another model since: the switch is theirs now, and no automatic switch happens again until the
      // window that triggered this one has reset.
      await $.state.set(FALLBACK, { suppressUntil: memo.until })
      return undefined
    }
    if (memo.until === undefined || now < memo.until) return undefined
    await $.state.set(FALLBACK, {})
    await $.command.run({ command: 'model', args: memo.from })
    // The engine raises PostModelSwitch for this too; applying the window here as well does not depend on it.
    try { await applyWindow($, c, await $.session.model()) } catch { /* window stays as it was */ }
    return await $.session.model() === memo.from
      ? `model-mod: the rate limit has reset; switched back to ${memo.from}.`
      : `model-mod: the rate limit has reset; could not switch back to ${memo.from}, choose it with /model.`
  }
  if (memo.suppressUntil !== undefined) {
    if (now < memo.suppressUntil) return undefined
    await $.state.set(FALLBACK, {})
  }
  const target = c.fallbackModel
  if (target === undefined) return undefined
  // Only a subscription model is switched away from: another plugin's model has no known way back.
  if (!/^claude-/i.test(model) || model === target || c.models.includes(model) || c.excluded?.has(model)) return undefined
  const { rateLimits } = await $.session.usage()
  const reached = rateLimits.filter(r => r.percentUsed >= (c.fallbackPercent ?? 100) && r.resetsAt !== undefined &&
    Date.parse(r.resetsAt) > now)
  if (reached.length === 0) return undefined
  if (!c.models.includes(target)) {
    if (fallbackHinted) return undefined
    fallbackHinted = true
    return `model-mod: the ${reached[0]!.kind} limit is reached, but ${target} is not an owned local model; run /model-mod:setup.`
  }
  try { await $.env.set('ANTHROPIC_CUSTOM_MODEL_OPTION', target) } catch {
    return `model-mod: could not prepare the local model ${target}; model not changed.`
  }
  const until = Math.max(...reached.map(r => Date.parse(r.resetsAt!)))
  await $.state.set(FALLBACK, { from: model, to: target, until })
  await $.command.run({ command: 'model', args: target })
  try { await applyWindow($, c, await $.session.model()) } catch { /* window stays as it was */ }
  if (await $.session.model() !== target) {
    await $.state.set(FALLBACK, {})
    return `model-mod: the ${reached[0]!.kind} limit is reached; switching to ${target} failed, choose it with /model.`
  }
  return `model-mod: the ${reached[0]!.kind} limit is reached (${reached[0]!.percentUsed}%); the session now uses ${target} until the limit resets` +
    ` (${new Date(until).toISOString().slice(0, 16).replace('T', ' ')} UTC). Your messages and project files are sent to the upstream while it does.`
}

// The paged ask menu, three models a page; undefined when nothing was chosen (cancelled or no way to ask).
async function menuPick($: EngineInterface, models: readonly string[], current: string): Promise<string | undefined> {
  try { return await pickModel($, models, current) } catch { return undefined }
}

async function admin($: EngineInterface, e: { origin: { kind: string } }, arg: 'setup' | 'status' | 'refresh') {
  const c = await load($)
  if (arg === 'setup') return { text: await configurePicker($, c ?? { baseUrl: typeof pluginOptions.baseUrl === 'string' ? pluginOptions.baseUrl : DEFAULT_BASE_URL, models: [] }, true, e.origin.kind === 'composer' || e.origin.kind === 'bridge', `picker=${c ? 'active' : 'inactive'}; models=${c?.models.length ?? 0}`) }
  if (!c) return { text: `model-mod: inactive; picker=inactive; models=0. Configure apiKey through /plugin → model-mod configure.` }
  if (arg === 'refresh') {
    c.prompts = await loadPrompts($, c.promptsDir)
    await registerWorker($, c)
    const prompts = promptStatus(c.prompts)
    if (!c.refresh) return { text: (await configurePicker($, c, false, e.origin.kind === 'composer' || e.origin.kind === 'bridge', '')) + '; ' + prompts }
    const before = await capturedTools($, c)
    const run = await $.process.run(c.refresh, { timeoutMs: 240_000 })
    const after = await capturedTools($, c)
    const names = new Set((before ?? []).map(tool => tool.name))
    const added = (after ?? []).filter(tool => !names.has(tool.name)).map(tool => tool.name)
    return { text: run.exitCode === 0
      ? `tool schemas refreshed (${after?.length ?? 0} tools${added.length ? `; new: ${added.join(', ')}` : ''}); ${prompts}.`
      : `refresh failed (exit ${run.exitCode}); ${prompts}.` }
  }
  const captured = await capturedTools($, c)
  let open = 0
  if (captured && c.toolsFile !== undefined) {
    const known = new Set(captured.map(tool => tool.name))
    open = (await $.tool.list()).filter(tool => tool.mcp && !tool.name.startsWith('mcp__model-mod__') && !known.has(tool.name)).length
  }
  return { text: `model-mod 0.1.0: picker=active; host=${new URL(c.baseUrl).hostname}; config=${c.source}; models=${c.models.length}; tools=${captured ? (c.toolsFile ? 'captured' : 'listed') : 'missing'}` +
    `; ${promptStatus(c.prompts)}; tool search=${c.toolSearch ?? 'auto'}; MCP tools without a captured schema=${open}${open && c.refresh ? ' (/model-mod:refresh captures them)' : ''}` }
}

export const register: Register = (on, options) => {
  registerPane(on)
  pluginOptions = options ?? {}
  on('session.start', async ($, e, next) => {
    const c = await load($)
    if (c) {
      // Models the upstream serves now; a failure keeps the cached and configured ones.
      if (c.source === 'options') await refreshModels($, c)
      for (const spec of c.toolSearch === 'off' ? [WEB_SEARCH_SPEC, WEB_FETCH_SPEC] : [WEB_SEARCH_SPEC, WEB_FETCH_SPEC, TOOL_SEARCH_SPEC]) {
        try { await $.tool.register(spec) } catch { /* the bridge works without the web tools */ }
      }
      try { await applyWindow($, c, await $.session.model()) } catch { /* window stays the engine's default */ }
      // An agent type that runs on a model of this mod, so a subscription model can hand work to it with the Agent tool
      // (whose own `model` parameter accepts only aliases). It appears in the Agent tool's listing only when configured.
      await registerWorker($, c)
      if (c.imageModel) {
        try { await $.tool.register(IMAGE_SPEC) } catch { /* the bridge works without the image tool */ }
      }
    }
    return next(e)
  })

  on('tool.call', { tool: IMAGE_TOOL }, async ($, e, next) => {
    // A refusal reaches the model as an error result; a success is the plain text of the result.
    const answer = (text: string, isError = false) => isError ? { deny: text } : { result: text }
    try {
      const c = await load($)
      if (!c || !c.imageModel) return answer('Image generation is not configured.', true)
      // Only a turn that already runs on a bridge model may use the image endpoint.
      const model = await bridgeModel($, e, c)
      if (model === undefined) {
        return answer('generate_image is only available while a local model is selected. Select a local model to use this tool.', true)
      }
      const input = e as unknown as Record<string, unknown>
      const prompt = typeof input.prompt === 'string' ? input.prompt.trim() : ''
      if (!prompt || prompt.length > 4000) return answer('prompt must be 1-4000 characters.', true)
      const refused = await permitted($, e, IMAGE_TOOL, `Generate an image and save it in the working directory: "${prompt.slice(0, 200)}"?`)
      if (refused) return answer(refused, true)
      const size = input.size ?? '1024x1024'
      const quality = input.quality ?? 'medium'
      if (!['1024x1024', '1536x1024', '1024x1536', 'auto'].includes(String(size)) ||
          !['low', 'medium', 'high', 'auto'].includes(String(quality))) return answer('size or quality is not supported.', true)
      const cwd = (await $.session.cwd()).replace(/\/+$/, '')
      const given = typeof input.path === 'string' ? input.path : `generated-images/image-${Date.now()}.png`
      if (!/^[A-Za-z0-9._\/-]{1,200}\.png$/.test(given) || given.startsWith('/') || given.split('/').some(part => part === '..' || part === '')) {
        return answer('path must be a relative .png path inside the working directory.', true)
      }
      const out = `${cwd}/${given}`
      const body = JSON.stringify({ model: c.imageModel, prompt, size, quality, n: 1 })
      const run = await $.process.run(['bash', '-c', IMAGE_PIPELINE, 'bash', c.headerFile ?? '',
        c.baseUrl + '/v1/images/generations', out], { stdin: body, timeoutMs: 300_000, ...(c.key !== undefined ? { env: { MODEL_MOD_KEY: c.key } } : {}) })
      if (run.exitCode !== 0) return answer(`Image request failed (${run.stdout.trim().slice(0, 100) || 'no output'}).`, true)
      return answer(`Saved image to ${out} (${run.stdout.trim()} bytes, ${size}). Open it with the Read tool to look at it.`)
    } catch (err) {
      return answer(`Image request failed (${err instanceof Error ? err.name : 'error'}).`, true)
    }
  })

  // Looks up schemas the bridge already holds; nothing leaves the machine, so no permission prompt.
  on('tool.check', { tool: TOOL_SEARCH_TOOL }, () => ({ decision: 'allow', reason: 'model-mod tool lookup' }))

  on('tool.call', { tool: TOOL_SEARCH_TOOL }, async ($, e, next) => {
    const answer = (text: string, isError = false) => isError ? { deny: text } : { result: text }
    try {
      const c = await load($)
      if (!c) return answer('Tool search is not configured.', true)
      if (await bridgeModel($, e, c) === undefined) return answer('tool_search is only available while a local model is selected. Select a local model to use this tool.', true)
      const input = e as unknown as Record<string, unknown>
      const query = typeof input.query === 'string' ? input.query.trim() : ''
      if (!query || query.length > 500) return answer('query must be 1-500 characters.', true)
      const max = Number.isInteger(input.max_results) ? Math.min(20, Math.max(1, input.max_results as number)) : 5
      const schemas = new Map((await capturedTools($, c) ?? []).map(tool => [tool.name, tool]))
      const pool = new Map<string, Tool>()
      for (const tool of await $.tool.list()) {
        if (!tool.mcp || tool.name.startsWith('mcp__model-mod__')) continue
        pool.set(tool.name, schemas.get(tool.name) ??
          { name: tool.name, description: tool.description, input_schema: { type: 'object', additionalProperties: true } })
      }
      let found: Tool[]
      const missing: string[] = []
      if (/^select:/i.test(query)) {
        found = []
        for (const name of query.slice(7).split(',').map(n => n.trim()).filter(Boolean)) {
          const hit = pool.get(name)
          if (hit) found.push(hit)
          else missing.push(name)
        }
      } else {
        const terms = query.toLowerCase().split(/[\s,]+/).filter(Boolean)
        found = [...pool.values()].map(tool => ({ tool, score: terms.reduce((sum, term) =>
          sum + (tool.name.toLowerCase().includes(term) ? 3 : 0) + (tool.description.toLowerCase().includes(term) ? 1 : 0), 0) }))
          .filter(row => row.score > 0).sort((a, b) => b.score - a.score).slice(0, max).map(row => row.tool)
      }
      if (!found.length) return answer(`No matching tools${missing.length ? ` (unknown: ${missing.join(', ')})` : ''}. ` +
        `Available: ${[...pool.keys()].slice(0, 200).join(', ')}.`, true)
      return answer(`Loaded tools: ${found.map(tool => tool.name).join(', ')}\n` +
        (missing.length ? `Unknown: ${missing.join(', ')}\n` : '') +
        'These tools can be called now.\n\n' +
        found.map(tool => JSON.stringify({ name: tool.name, description: tool.description, input_schema: tool.input_schema })).join('\n'))
    } catch (err) {
      return answer(`Tool search failed (${err instanceof Error ? err.name : 'error'}).`, true)
    }
  })

  on('tool.call', { tool: WEB_SEARCH_TOOL }, async ($, e, next) => {
    const answer = (text: string, isError = false) => isError ? { deny: text } : { result: text }
    try {
      const c = await load($)
      if (!c) return answer('Web search is not configured.', true)
      const model = await bridgeModel($, e, c)
      if (model === undefined) return answer('web_search is only available while a local model is selected. With this model, use the built-in WebSearch tool instead.', true)
      const input = e as unknown as Record<string, unknown>
      const query = typeof input.query === 'string' ? input.query.trim() : ''
      if (!query || query.length > 500) return answer('query must be 1-500 characters.', true)
      const refused = await permitted($, e, WEB_SEARCH_TOOL, `Search the web for "${query.slice(0, 200)}"?`)
      if (refused) return answer(refused, true)
      const domains = Array.isArray(input.allowed_domains) ? input.allowed_domains : []
      if (domains.length > 20 || !domains.every(d => typeof d === 'string' && /^[A-Za-z0-9.-]{1,253}$/.test(d))) {
        return answer('allowed_domains must be at most 20 plain domain names.', true)
      }
      const body = { model: c.effortMode === 'suffix' ? `${model}(low)` : model, max_tokens: c.maxTokens, stream: false,
        tools: [{ type: 'web_search_20250305', name: 'web_search', max_uses: 5,
          ...(domains.length ? { allowed_domains: domains } : {}) }],
        messages: [{ role: 'user', content: `Search the web for: ${query}\nAnswer with the facts found and name the sources.` }] }
      const run = await curlRun($, c, ['-sS', '--fail-with-body', '--max-time', '280',
        '-H', 'content-type: application/json', '-H', 'anthropic-version: 2023-06-01',
        '--data-binary', '@-', c.baseUrl + '/v1/messages'], { stdin: JSON.stringify(body), timeoutMs: 300_000 })
      if (run.exitCode !== 0) return answer(`Search request failed (${scrub(c, run.stdout.trim()).slice(0, 100) || 'no output'}).`, true)
      const reply = JSON.parse(run.stdout) as { content?: { type: string; text?: string; content?: unknown }[] }
      const parts = reply.content ?? []
      // A successful body is masked too: nothing the upstream returned may carry the credential into the conversation.
      const text = scrub(c, parts.filter(b => b.type === 'text').map(b => b.text ?? '').join('').trim(), false)
      const links: string[] = []
      for (const part of parts) {
        if (part.type !== 'web_search_tool_result' || !Array.isArray(part.content)) continue
        for (const hit of part.content as { title?: string; url?: string }[]) {
          if (typeof hit?.url === 'string') links.push(scrub(c, `- ${hit.title && hit.title !== hit.url ? hit.title + ' ' : ''}${hit.url}`, false))
        }
      }
      if (!text && !links.length) return answer('The search returned nothing.', true)
      return answer(`Web search results for query: "${query}"\n\n${text}\n\n${links.length ? 'Sources:\n' + [...new Set(links)].join('\n') : ''}`.trim())
    } catch (err) {
      return answer(`Search request failed (${err instanceof Error ? err.name : 'error'}).`, true)
    }
  })

  on('tool.call', { tool: WEB_FETCH_TOOL }, async ($, e, next) => {
    const answer = (text: string, isError = false) => isError ? { deny: text } : { result: text }
    try {
      const c = await load($)
      if (!c) return answer('Web fetch is not configured.', true)
      if (await bridgeModel($, e, c) === undefined) return answer('web_fetch is only available while a local model is selected. With this model, use the built-in WebFetch tool instead.', true)
      let url = String((e as unknown as Record<string, unknown>).url ?? '').trim()
      for (let redirects = 0; redirects <= 5; redirects++) {
        let parsed: URL
        try { parsed = new URL(url) } catch { return answer('url is not a valid URL.', true) }
        if (url.length > 2000 || !['http:', 'https:'].includes(parsed.protocol) || parsed.username || parsed.password) {
          return answer('url must be a plain http or https URL.', true)
        }
        const host = parsed.hostname
        const literal = /^\d+\.\d+\.\d+\.\d+$/.test(host) || host.startsWith('[')
        if (PRIVATE_HOST.test(host) || (literal && privateAddress(host.replace(/^\[|\]$/g, '')))) return answer(PRIVATE_FETCH, true)
        if (redirects === 0) {
          const refused = await permitted($, e, WEB_FETCH_TOOL, `Fetch ${url.slice(0, 300)}?`)
          if (refused) return answer(refused, true)
        }
        let addresses = [host]
        if (!literal) {
          const resolved = await resolveHost($, host)
          if (!resolved) return answer('The host could not be resolved.', true)
          addresses = resolved
          if (addresses.some(privateAddress)) return answer(PRIVATE_FETCH, true)
        }
        const port = parsed.port || (parsed.protocol === 'https:' ? '443' : '80')
        // Ignore curlrc and proxies so neither can bypass the checked, pinned destination or enable redirects.
        const run = await $.process.run(['curl', '-q', '-g', '-sS', '-i', '--noproxy', '*',
          '--proto', '=http,https', '--proto-redir', '=http,https',
          '--resolve', `${host}:${port}:${[...new Set(addresses)].map(address => address.includes(':') ? `[${address}]` : address).join(',')}`,
          '--max-time', '60', '--max-filesize', '3000000', '-A', 'Mozilla/5.0 (compatible; model-mod)',
          '--', parsed.href], { timeoutMs: 90_000 })
        const response = run.exitCode === 0 ? fetchResponse(run.stdout) : undefined
        if (!response) return answer('The page could not be fetched or had no text.', true)
        if (response.status >= 300 && response.status < 400 && response.location) {
          if (redirects === 5) return answer('Too many redirects.', true)
          try { url = new URL(response.location, parsed).href } catch { return answer('url is not a valid URL.', true) }
          continue
        }
        const text = htmlToText(response.body)
        return text ? answer(text) : answer('The page could not be fetched or had no text.', true)
      }
      return answer('Too many redirects.', true)
    } catch (err) {
      return answer(`Fetch failed (${err instanceof Error ? err.name : 'error'}).`, true)
    }
  })

  // The client names a session with a small request to the subscription endpoint, outside every hook. A title set here
  // replaces that request (measured: none is sent), so while a local model is selected the first prompt is titled by the
  // local model and the prompt never leaves for the subscription endpoint for naming.
  on('classic.UserPromptSubmit', async ($, e, next) => {
    const result = await next(e)
    try {
      if (e.session_title || (e.source !== undefined && e.source !== 'user')) return result
      const c = await load($)
      if (!c || c.localTitle === false) return result
      // Headless runs (-p, the SDK) have no title to show.
      if (/sdk/i.test(await $.env.get('CLAUDE_CODE_ENTRYPOINT') ?? '')) return result
      const model = await $.session.model()
      if (!c.models.includes(model)) return result
      const prompt = e.prompt.replace(/\s+/g, ' ').trim().slice(0, 2000)
      if (!prompt) return result
      let title = ''
      if (c.prompts.text.title !== undefined) try {
        const body = { model: c.effortMode === 'suffix' ? `${model}(low)` : model, max_tokens: 64, stream: false,
          system: c.prompts.text.title,
          messages: [{ role: 'user', content: [{ type: 'text', text: prompt }] }] }
        const run = await curlRun($, c, ['-sS', '--fail-with-body', '--max-time', '15',
          '-H', 'content-type: application/json', '-H', 'anthropic-version: 2023-06-01',
          '--data-binary', '@-', c.baseUrl + '/v1/messages'], { stdin: JSON.stringify(body), timeoutMs: 20_000 })
        if (run.exitCode === 0) {
          const reply = JSON.parse(run.stdout) as { content?: { type: string; text?: string }[] }
          title = scrub(c, (reply.content ?? []).filter(b => b.type === 'text').map(b => b.text ?? '').join(' '), false)
            .replace(/[\r\n"“”]+/g, ' ').replace(/\s+/g, ' ').trim().replace(/[.\u3002]+$/, '')
        }
      } catch { /* use the prompt itself */ }
      // Without a title the client would send the prompt to the subscription endpoint to get one.
      if (!title || title.length > 80) title = prompt.slice(0, 50).trim()
      return { ...result, sessionTitle: title }
    } catch { /* the client names the session */ }
    return result
  })

  on('classic.PostModelSwitch', async ($, e, next) => {
    try {
      const c = await load($)
      if (c) await applyWindow($, c, e.to_model)
    } catch { /* window stays as it was */ }
    return next(e)
  })

  // Native /btw forks the main model outside turn.step. Answer through the local API without running tools or
  // changing the conversation; never let a local model or its session content fall through to that fork.
  on('command.run', { command: 'btw' }, async ($, e, next) => {
    try {
      const c = await load($)
      if (!c) return next(e)
      const model = await $.session.model()
      if (c.excluded?.has(model)) return { text: 'model-mod: model is not in the allowlist' }
      if (!c.models.includes(model)) return next(e)
      const question = e.args.trim()
      if (!question) return { text: 'model-mod: /btw needs a side question.' }
      const history = await $.session.messages({ as: 'api' })
      if (!Array.isArray(history)) return { text: 'model-mod: side-question context is unavailable.' }
      const messages = (history as unknown as Turn[]).map(message => ({ ...message,
        content: message.content.filter(block => !['thinking', 'redacted_thinking', 'server_tool_use'].includes(block.type)
          && !block.type.endsWith('_tool_result')) })).filter(message => message.content.length > 0)
      while (messages.length && messages[0]!.role !== 'user') messages.shift()
      messages.push({ role: 'user', content: [{ type: 'text', text: question }] })
      const prompt = await $.prompt.compose({ model, tools: [] })
      const body = { model, max_tokens: c.maxTokens, stream: false, messages,
        system: [...prompt.sections.map(section => section.text),
          'Answer only the side question using the conversation as read-only context. Give one reply. Do not use tools or perform actions.'].join('\n\n') }
      const run = await curlRun($, c, ['-sS', '--fail-with-body', '--max-time', '280',
        '-H', 'content-type: application/json', '-H', 'anthropic-version: 2023-06-01',
        '--data-binary', '@-', c.baseUrl + '/v1/messages'], { stdin: JSON.stringify(body), timeoutMs: 300_000 })
      if (run.exitCode !== 0) return { text: 'model-mod: side-question request failed.' }
      const reply = JSON.parse(run.stdout) as { content?: { type: string; text?: string }[] }
      const text = scrub(c, (reply.content ?? []).filter(block => block.type === 'text').map(block => block.text ?? '').join('').trim(), false)
      return { text: text || 'model-mod: side question returned no text.' }
    } catch {
      return { text: 'model-mod: side-question request failed.' }
    }
  })

  // /context counts every category through the subscription API's token-count endpoint (about 30 requests that name the
  // local model ID; measured). While a local model is selected the engine's local estimate answers instead: no request.
  on('command.run', { command: 'context' }, async ($, e, next) => {
    let local = false
    try {
      const c = await load($)
      local = !!c && c.localContext !== false && c.models.includes(await $.session.model())
    } catch { return next(e) }
    if (!local) return next(e)
    // From here on never next(e): the built-in command would send the local model ID to the subscription endpoint.
    try {
      const { context } = await $.session.usage({ breakdown: 'summary', columns: 80 })
      const b = context.breakdown
      const n = (x: number) => x.toLocaleString('en-US')
      const lines = [`Context usage (estimated locally, no token-count requests) — ${b?.model ?? await $.session.model()}`]
      if (b) {
        lines.push(`${n(b.totalTokens)} / ${n(b.rawMaxTokens)} tokens (${b.percentage}%)`)
        for (const cat of b.categories) {
          lines.push(`  ${cat.name}: ${n(cat.tokens)} tokens (${((cat.tokens / b.rawMaxTokens) * 100).toFixed(1)}%)${cat.isDeferred ? ' [deferred]' : ''}`)
        }
        if (b.memoryFiles.length) {
          lines.push('Memory files:')
          for (const f of b.memoryFiles) lines.push(`  ${f.type}: ${f.path}: ${n(f.tokens)} tokens`)
        }
        const mcp = b.mcpTools.filter(t => t.isLoaded)
        if (mcp.length) lines.push(`MCP tools loaded: ${mcp.length} (${n(mcp.reduce((a, t) => a + t.tokens, 0))} tokens)`)
        if (b.autoCompactThreshold !== undefined) lines.push(`Auto-compact at ${n(b.autoCompactThreshold)} tokens`)
        // The grid /context draws: ■ filled, □ partly filled, · free space.
        const grid = (b.gridRows ?? []).map(row => row.map(sq => sq.categoryName === 'Free space' || !sq.isFilled ? '·' :
          sq.squareFullness < 0.7 ? '□' : '■').join(' '))
        if (grid.length) lines.splice(2, 0, ...grid, '')
      }
      if (context.tokens !== undefined) {
        lines.push(`Last response: ${n(context.tokens)} input tokens of a ${n(context.window)} window${context.percent !== undefined ? ` (${context.percent}%)` : ''}`)
      }
      return { text: lines.join('\n') }
    } catch (err) {
      return { text: `model-mod: /context could not be estimated (${err instanceof Error ? err.name : 'error'}).` }
    }
  })

  // /model stays the client's own. Only a typed owned ID is prepared (the client has to accept it as a custom model).
  on('command.run', { command: 'model' }, async ($, e, next) => {
    const args = e.args.trim()
    if (!args) return next(e)
    const c = await load($)
    if (!c) return next(e)
    if (c.excluded?.has(args)) return { text: `model-mod: ${args} is not in the allowlist; run /model-mod:setup.` }
    if (!c.models.includes(args)) return next(e)
    try { await $.env.set('ANTHROPIC_CUSTOM_MODEL_OPTION', args) } catch {
      return { text: 'model-mod: could not prepare the local model; model not changed.' }
    }
    return next(e)
  })

  // /model-mod:model lists the local models only (official models stay with the client's own /model): the picker pane,
  // or the paged menu where the pane cannot be shown.
  on('command.run', { command: 'model-mod:model' }, async ($, e) => {
    const c = await load($)
    if (!c) return { text: 'model-mod: inactive; models=0. Configure apiKey through /plugin → model-mod configure.' }
    if (e.origin.kind !== 'composer' && e.origin.kind !== 'bridge') return { text: 'model-mod: /model-mod:model needs an interactive session.' }
    if (!c.models.length) return { text: 'model-mod: no local models. Run /model-mod:setup to add them.' }
    let current = ''
    try { current = await $.session.model() } catch { /* no model is marked */ }
    // A choice is applied through the client's own /model, so the usual switch rules and events run. The engine refuses
    // command.run from inside a command.run hook, so it runs once this hook has answered; its reply is shown as a toast.
    const apply = async (id: string | undefined): Promise<string | undefined> => {
      if (!id || !c.models.includes(id)) return 'model-mod: model not changed.'
      // The native command accepts a model it does not list only through this variable (the typed-ID path sets it too).
      try { await $.env.set('ANTHROPIC_CUSTOM_MODEL_OPTION', id) } catch { return 'model-mod: could not prepare the local model; model not changed.' }
      $.clock.after(0, () => {
        void $.command.run({ command: 'model', args: id }).then(run => { if (run.text) void $.ui.toast(run.text) })
          .catch(() => { void $.ui.toast('model-mod: model not changed.').catch(() => {}) })
      })
      return undefined
    }
    // The pane outlives this hook (a hook may run for 10 s of its own time, a person may take longer), so its
    // choices are applied from its handlers and reported as a toast.
    if (e.origin.kind === 'composer') {
      const toast = (text?: string) => { if (text) void $.ui.toast(text).catch(() => {}) }
      const shown = await openPane($, { local: c.models, current }, {
        pick: async id => toast(await apply(id)),
        fallback: async () => toast(await apply(await menuPick($, c.models, current))),
      })
      if (shown === 'shown') return {}
    }
    const text = await apply(await menuPick($, c.models, current))
    return text ? { text } : {}
  })

  // The names stay literal: the engine reads them statically.
  on('command.run', { command: 'model-mod:setup' }, ($, e) => admin($, e, 'setup'))
  on('command.run', { command: 'model-mod:status' }, ($, e) => admin($, e, 'status'))
  on('command.run', { command: 'model-mod:refresh' }, ($, e) => admin($, e, 'refresh'))

  on('agent.spawn', async ($, e, next) => {
    const started = await next(e)
    try {
      const c = await load($)
      if (c && e.workflow && started.agentId && !started.deny && c.models.includes(started.model)) {
        await rememberAgentModel($, started.agentId, started.model)
        await $.state.set({ ...TRACKED, id: started.agentId }, { turns: [{ role: 'user', content: [{ type: 'text', text: e.prompt }] }],
          pending: [], results: {} })
      }
    } catch { /* tracking is best effort; the agent still runs */ }
    return started
  })

  on('tool.call', async ($, e, next) => {
    const result = await next(e)
    const id = e.tool_use_id
    if (e.agentId !== undefined && id) {
      try {
        const outcome = 'deny' in result && result.deny !== undefined
          ? { text: result.deny, isError: true }
          : { text: String(result.text ?? ''), isError: result.isError === true }
        // `update` retries on a version miss, so parallel tool calls of one agent each land. Only agents the mod
        // tracks (workflow agents on a bridge model) have a value; for any other agent nothing is written.
        const held = await trackedOf($, e.agentId)
        if (held) await update($, { ...TRACKED, id: e.agentId }, t => ({ ...(t ?? held), results: { ...(t ?? held).results, [id]: outcome } }))
      } catch { /* tracking is best effort */ }
    }
    return result
  })

  // Automatic switch to the fallback model (off unless `fallbackModel` is set), decided between turns.
  on('turn.complete', async ($, e, next) => {
    const result = await next(e)
    if (e.agentId !== undefined) return result
    try {
      const c = await load($)
      const note = c ? await autoFallback($, c) : undefined
      if (note !== undefined) {
        $.ui.status(note)
        $.ui.toast(note, { timeoutMs: 15_000 })
      }
    } catch { /* the switch is best effort; the session keeps its model */ }
    return result
  })

  // /compact and auto-compaction summarise with the main model; for a bridge model the
  // engine's own request would name a non-Anthropic ID, so the summary is made here.
  on('session.compact', async ($, e, next) => {
    const c = await load($)
    if (!c) return next(e)
    let model: string | undefined
    if (e.agentId === undefined) {
      try { model = await $.session.model() } catch { return next(e) }
    } else {
      // An unreadable value is unknown, not "subscription": ending the compaction is safe for both kinds of agent.
      try { model = await agentModelOf($, e.agentId) } catch { return { skip: 'model-mod: agent model unknown' } }
    }
    if (model !== undefined && c.excluded?.has(model)) return { skip: 'model-mod: model is not in the allowlist' }
    if (model === undefined || !c.models.includes(model)) return next(e)
    // From here on never fall back to next(e): that would send the bridge model ID to the subscription endpoint.
    if (c.prompts.text.compact === undefined) return { skip: 'model-mod: compaction prompt file missing' }
    if (e.trigger === 'precompute') return { skip: 'model-mod: no precomputed summary for a local model' }
    try {
      const ask = `Summarize this conversation.${e.instructions ? `\nExtra focus: ${e.instructions}` : ''}\n\n<transcript>\n` +
        `${renderTranscript(e.messages)}\n</transcript>`
      const body = { model, max_tokens: c.maxTokens, stream: false, system: c.prompts.text.compact,
        messages: [{ role: 'user', content: [{ type: 'text', text: ask }] }] }
      const run = await curlRun($, c, ['-sS', '--fail-with-body', '--max-time', '590',
        '-H', 'content-type: application/json', '-H', 'anthropic-version: 2023-06-01',
        '--data-binary', '@-', c.baseUrl + '/v1/messages'], { stdin: JSON.stringify(body), timeoutMs: 600_000 })
      if (run.exitCode !== 0) return { skip: 'model-mod: summary request failed' }
      const reply = JSON.parse(run.stdout) as { content?: { type: string; text?: string }[] }
      const summary = scrub(c, (reply.content ?? []).filter(b => b.type === 'text').map(b => b.text ?? '').join('').trim(), false)
      if (!summary) return { skip: 'model-mod: empty summary' }
      const text = 'This session is being continued from a previous conversation that ran out of context. ' +
        'The summary below covers the earlier portion of the conversation.\n\n' + summary
      const own = await trackedOf($, e.agentId)
      if (own) {
        await $.state.set({ ...TRACKED, id: e.agentId! },
          { turns: [{ role: 'user', content: [{ type: 'text', text }] }], pending: [], results: {} })
      }
      return { messages: [{ role: 'user' as const, toolUses: [], text }] }
    } catch (err) {
      const why = err instanceof Error ? `${err.name}: ${err.message}` : String(err)
      return { skip: `model-mod: summary failed (${scrub(c, why).slice(0, 160)})` }
    }
  })

  on('turn.step', async function* ($, e, next) {
    const c = await load($)
    if (!c) return yield* next(e)
    if (e.agentId !== undefined) {
      await rememberAgentModel($, e.agentId, e.model)
    }
    if (e.agentId === undefined) {
      try { await applyWindow($, c, e.model) } catch { /* window stays as it was */ }
    }
    if (c.excluded?.has(e.model)) return yield* failure(e, 'model is not in the allowlist')
    if (!c.models.includes(e.model)) return yield* next(e)
    let parser = new MessagesStream(e.model)
    try {
      const own = await trackedOf($, e.agentId)
      let history: readonly Turn[]
      if (own) {
        if (flushResults(own)) await $.state.set({ ...TRACKED, id: e.agentId! }, own)
        history = own.turns
      } else {
        const read = await $.session.messages({ as: 'api', agentId: e.agentId })
        if (!Array.isArray(read)) throw new Error(`messages_unavailable ${JSON.stringify(read).slice(0, 100)}`)
        history = read as unknown as Turn[]
      }
      if (e.agentId !== undefined && !own && history.length !== e.messageCount) {
        $.ui.status(`model-mod: agent message count differs (${history.length}/${e.messageCount}); using available history.`)
      }
      const messages = history.map(message => ({ ...message, content: message.content.filter(block => {
        const type = block.type
        return !['thinking', 'redacted_thinking', 'server_tool_use'].includes(type) && !type.endsWith('_tool_result')
      }) })).filter(message => message.content.length > 0)
      while (messages.length && messages[0]!.role !== 'user') messages.shift()
      let withThinking: typeof messages | undefined
      if (c.keepThinking !== false && thinkingStash.size > 0) {
        let any = false
        withThinking = messages.map(message => {
          if (message.role !== 'assistant') return message
          const ids = message.content.filter(b => b.type === 'tool_use').map(b => String((b as { id?: unknown }).id))
          const kept = ids.map(id => thinkingStash.get(id)).find(Boolean)
          if (!kept) return message
          any = true
          return { ...message, content: [...kept, ...message.content] }
        })
        if (!any) withThinking = undefined
      }
      if (!messages.length) throw new Error(`messages_unavailable history=${history.length} agent=${String(e.agentId)} count=${e.messageCount}`)
      const offered = await tools($, c, e.model, history)
      // PromptComposeArgs has no agentId: compose the session system for this model.
      const prompt = await $.prompt.compose({ model: e.model, tools: offered.map(tool => tool.name) })
      const body = { model: wireModel(c, e), max_tokens: c.maxTokens, stream: true, messages,
        system: [...prompt.sections.map(section => section.text), ...(e.agentId !== undefined && c.prompts.text['subagent-note'] !== undefined ? [c.prompts.text['subagent-note']] : [])].join('\n\n'),
        ...(offered.length ? { tools: offered } : {}) }
      // A failure before anything was shown (rate limit, overload, a dropped connection) is retried with a backoff, like the
      // client does for its own endpoint; once output has streamed the turn ends instead of repeating it.
      let sendThinking = withThinking !== undefined
      for (let attempt = 0; ; attempt++) {
        if (next.signal.aborted) return yield* failure(e, 'cancelled')
        parser = new MessagesStream(e.model)
        const call = curlCall(c, ['-sN', '--fail-with-body', '--max-time', '900',
          '--write-out', '%{stderr}\nmodel-mod-http:%{http_code}\n', '-H', 'content-type: application/json',
          '-H', 'anthropic-version: 2023-06-01', '--data-binary', '@-', c.baseUrl + '/v1/messages'])
        const child = $.process.spawn({ argv: call.argv, ...(call.env ? { env: call.env } : {}),
          input: JSON.stringify(sendThinking ? { ...body, messages: withThinking } : body) })
        let finished = false
        let rawError = ''
        let statusTail = ''
        let httpStatus = 0
        let streamed = false
        try {
          for await (const piece of child) {
            if (next.signal.aborted) return yield* failure(e, 'cancelled', parser.nextIndex)
            if (piece.stream !== 'stdout') {
              statusTail = (statusTail + piece.text).slice(-64)
              const status = /\nmodel-mod-http:(\d{3})\n/.exec(statusTail)
              if (status) httpStatus = Number(status[1])
              continue
            }
            // Preserve a small error JSON prefix without ever displaying its message.
            if (rawError.length < 4096) rawError += piece.text.slice(0, 4096 - rawError.length)
            for (const chunk of parser.push(piece.text)) { streamed = true; yield chunk }
            if (parser.error) break
          }
          const exit = parser.error ? { code: 0 } : await child.result
          if (parser.error) {
            try { await child.return({ code: null, signal: 'SIGTERM' }) } catch { /* the stream already closed the child */ }
          }
          finished = true
          if (parser.error || exit.code !== 0 || !parser.complete) {
            let reason = parser.error || exit.code === 22 ? 'HTTP error' : exit.code !== 0 ? 'curl failed' : 'incomplete upstream response'
            let type: unknown = parser.error?.type
            if (!parser.error) {
              try { type = JSON.parse(rawError).error?.type } catch { /* SSE, not JSON */ }
            }
            if (['api_error', 'authentication_error', 'permission_error', 'not_found_error',
              'invalid_request_error', 'rate_limit_error', 'overloaded_error'].includes(type as string)) reason += ` (${type})`
            const transient = parser.error || exit.code === 22
              ? [429, 502, 503, 504, 529].includes(httpStatus) || ['rate_limit_error', 'overloaded_error', 'api_error'].includes(type as string)
              : exit.code === 0 || (exit.code !== null && [6, 7, 18, 28, 35, 52, 55, 56].includes(exit.code))
            if (!streamed && sendThinking && type === 'invalid_request_error') {
              // The API did not accept the remembered reasoning (another credential, a changed format): go without it.
              sendThinking = false
              attempt--
              continue
            }
            if (!streamed && transient && attempt < RETRY_DELAYS.length) {
              $.ui.status(`model-mod: ${reason}; retrying (${attempt + 1}/${RETRY_DELAYS.length})`)
              // $.clock.sleep is paid out of the hook's own time budget (about 10 s); a process wait is not.
              for (let left = RETRY_DELAYS[attempt]!; left > 0 && !next.signal.aborted; left -= 3000) {
                await $.process.run(['sleep', String(Math.min(left, 3000) / 1000)])
              }
              continue
            }
            return yield* failure(e, reason, parser.nextIndex)
          }
          if (c.keepThinking !== false) stashThinking(parser.firstToolId(), parser.thinkingBlocks())
          if (own) {
            own.turns.push({ role: 'assistant', content: parser.blocks() })
            own.pending = parser.blocks().filter(b => b.type === 'tool_use').map(b => String(b.id))
            await $.state.set({ ...TRACKED, id: e.agentId! }, own)
          }
          return parser.result(e)
        } finally {
          // Closing the outer generator while it yields also closes/kills its child.
          if (!finished) {
            try { await child.return({ code: null, signal: 'SIGTERM' }) } catch { /* abort already killed it */ }
          }
        }
      }
    } catch (err) {
      const why = err instanceof Error ? scrub(c, `${err.name}: ${err.message}`).slice(0, 160) : 'unknown'
      return yield* failure(e, next.signal.aborted ? 'cancelled' : `local request failed (${why})`, parser.nextIndex)
    }
  }).catch(async function* ($, e, next) {
    // No engine calls in this handler: re-entry failures deny all $ operations.
    if (config?.models.includes(e.model)) return yield* failure(e, 'hook failed')
    return yield* next(e)
  })
}
