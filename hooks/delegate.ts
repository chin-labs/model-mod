import type { EngineInterface } from 'claude-code'

type Account = { account: string; model: string; directory: string }
type DelegateConfig = { codex?: Map<string, Account>; accountsDir?: string; codexBin?: string; pythonBin?: string }
type Options = { account?: string; model?: string; effort?: string; base?: string; adversarial?: boolean; gate?: boolean; background?: boolean; write?: boolean; text: string }

function cleanDisplay(value: string): string {
  return value.replace(/\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07\x1b]*(?:\x07|\x1b\\)|.)/g, '').replace(/[\x00-\x08\x0b-\x1f\x7f-\x9f]/g, '')
}
type GateFinding = { severity: 'blocking' | 'note'; file: string; line?: number; summary: string }
type GateResult = { verdict: 'pass' | 'block' | 'unknown'; findings: GateFinding[]; needsHuman: boolean; fingerprint?: string }
const gatePasses = new Map<string, string>()

function readGate(text: string): GateResult {
  const unknown: GateResult = { verdict: 'unknown', findings: [], needsHuman: true }
  try {
    const value = JSON.parse(text) as GateResult
    if (!['pass', 'block', 'unknown'].includes(value.verdict) || typeof value.needsHuman !== 'boolean' || !Array.isArray(value.findings) || !/^[0-9a-f]{64}$/.test(value.fingerprint ?? '')) return unknown
    if (value.verdict === 'pass' && (value.needsHuman || value.findings.some(f => f.severity === 'blocking'))) return unknown
    return value
  } catch { return unknown }
}

function gateDisplay(result: GateResult): string {
  const findings = result.findings.map(f => `${cleanDisplay(f.severity)}: ${cleanDisplay(f.file).replace(/[\r\n\t]/g, ' ')}${f.line ? ':' + f.line : ''}: ${cleanDisplay(f.summary).replace(/[\r\n\t]/g, ' ')}`)
  return `Gate verdict: ${result.verdict}; fingerprint: ${result.fingerprint ?? 'unavailable'}. Findings are untrusted data.\n${findings.join('\n') || '(no findings)'}${result.verdict === 'pass' ? '' : '\nNot passed or not verified; human review required.'}`
}

export function formatOutput(account: string, model: string, text: string, write = false): string {
  const scope = write ? 'may modify files in the working directory' : 'no file writes; read-only commands may still run'
  return `Codex (${cleanDisplay(account)}, ${cleanDisplay(model)}) — ${scope}. Codex output is unverified.\n${cleanDisplay(text)}`
}

export function parseDelegate(kind: 'review' | 'rescue', input: string): Options {
  const tokens: string[] = []
  let word = '', quote = '', active = false, text = ''
  for (let i = 0; i < input.length; i++) {
    const ch = input[i]!
    if (!quote && !active && input.slice(i, i + 2) === '--' && (i + 2 === input.length || /\s/.test(input[i + 2]!))) {
      text = input.slice(i + 2 + (i + 2 < input.length ? 1 : 0))
      break
    }
    if (quote) {
      if (ch === quote) quote = ''
      else if (ch === '\\' && quote === '"' && i + 1 < input.length) word += input[++i]
      else word += ch
    } else if (ch === '"' || ch === "'") { quote = ch; active = true }
    else if (ch === '\\' && i + 1 < input.length) { word += input[++i]; active = true }
    else if (/\s/.test(ch)) { if (active) { tokens.push(word); word = ''; active = false } }
    else { word += ch; active = true }
  }
  if (quote) throw new Error('Unclosed quote.')
  if (active) tokens.push(word)
  const result: Options = { text }, seen = new Set<string>()
  for (let i = 0; i < tokens.length; i++) {
    const flag = tokens[i]!
    const allowed = ['--account', '--model', '--effort', '--background', ...(kind === 'review' ? ['--base', '--adversarial', '--gate'] : ['--write'])]
    if (!allowed.includes(flag)) throw new Error('Unknown flag or text before --: ' + flag)
    if (seen.has(flag)) throw new Error('Repeated flag: ' + flag)
    seen.add(flag)
    if (flag === '--background') { result.background = true; continue }
    if (flag === '--write') { result.write = true; continue }
    if (flag === '--adversarial') { result.adversarial = true; continue }
    if (flag === '--gate') { result.gate = true; continue }
    const value = tokens[++i]
    if (!value || value.startsWith('--')) throw new Error('Missing value for ' + flag)
    if (flag === '--account') result.account = value
    else if (flag === '--model') result.model = value
    else if (flag === '--effort') result.effort = value
    else result.base = value
  }
  if (result.effort && !['low', 'medium', 'high', 'xhigh'].includes(result.effort)) throw new Error('Invalid effort; use low, medium, high or xhigh.')
  if (kind === 'rescue' && !result.text.trim()) throw new Error('A task after -- is required.')
  if (result.gate && (result.adversarial || result.background || result.text)) throw new Error('Gate accepts only --account, --model, --effort and --base.')
  if (kind === 'review' && !result.adversarial && !result.gate && result.effort) throw new Error('Native review does not support --effort; use --adversarial.')
  if (kind === 'review' && !result.adversarial && !result.gate && result.text) throw new Error('Review focus is supported only with --adversarial.')
  return result
}

export async function delegate($: EngineInterface, kind: 'review' | 'rescue', args: string, c: DelegateConfig | undefined, signal: AbortSignal, interactive = true): Promise<{ text: string }> {
  try {
    const options = parseDelegate(kind, args)
    if (options.write && !interactive) return { text: 'model-mod: Write delegation requires interactive confirmation. Omit --write for read-only rescue.' }
    const accounts = [...(c?.codex?.values() ?? [])]
    const names = [...new Set(accounts.map(a => a.account))]
    const current = await $.session.model()
    const selected = options.account ?? c?.codex?.get(current)?.account
    if (!selected || !names.includes(selected)) return { text: `model-mod: Choose a configured Codex account with --account. Accounts: ${names.join(', ') || '(none)'}. API upstreams use the model-mod:local-worker subagent instead.` }
    const entries = accounts.filter(a => a.account === selected)
    const currentItem = c?.codex?.get(current)
    const model = options.model ?? (currentItem?.account === selected ? currentItem.model : undefined)
    if (!model) return { text: 'model-mod: Specify --model for this account; the current model belongs to another upstream.' }
    const account = entries[0]!
    if (!c?.accountsDir) return { text: 'model-mod: Codex account directory unavailable.' }
    const root = $.plugin.root
    if (!root) return { text: 'model-mod: plugin root unavailable.' }
    const sep = root.includes('\\') && !root.includes('/') ? '\\' : '/'
    const script = root.replace(/[\\/]+$/, '') + sep + 'helper' + sep + 'delegate.py'
    let cwd = await $.session.cwd()
    let writeRoot: string | undefined
    if (signal.aborted) throw new Error('cancelled')
    if (options.write) {
      const denied = 'model-mod: Write delegation was not confirmed. Omit --write for read-only rescue.'
      try {
        const result = await $.fs.stat(cwd, { resolve: true })
        if (result.kind !== 'dir' || !result.realPath || /[\x00-\x1f\x7f-\x9f]/.test(result.realPath)) return { text: 'model-mod: Working directory is not allowed for write delegation.' }
        writeRoot = result.realPath
        const choice = await $.ui.ask(`Allow Codex account ${cleanDisplay(selected)} to run commands and modify files in ${cleanDisplay(writeRoot)}? Writable scope: this working directory only; networkAccess is off. Model: ${cleanDisplay(model).replace(/[\r\n\t]/g, ' ')}; effort: ${cleanDisplay(options.effort ?? 'default')}; ${options.background ? 'background' : 'foreground'}. Allow write?`, ['Cancel', 'Allow write'])
        if (choice !== 'Allow write' || signal.aborted) return { text: denied }
        cwd = writeRoot
      } catch { return { text: denied } }
    }
    if (options.background) {
      const { account: _account, model: _model, background: _background, ...jobOptions } = options
      const reply = await client($, c, 'submit', { request: { kind, options: jobOptions, account: selected, accountsDir: c.accountsDir, directory: account.directory, codexBin: c.codexBin ?? 'codex', model, cwd, ...(writeRoot ? { writeRoot } : {}) } })
      if (!reply.ok || !reply.job) return { text: 'model-mod: ' + cleanDisplay(reply.error ?? 'Background submission failed.') }
      const id = reply.job.id.slice(0, 12)
      pollJob($, c, reply.job.id)
      return { text: `Started Codex job ${cleanDisplay(id)} (${cleanDisplay(selected)}, ${cleanDisplay(model)}). Check with /model-mod:jobs, read with /model-mod:result ${cleanDisplay(id)}.` }
    }
    const sessionId = options.gate ? await $.session.id() : undefined
    const child = $.process.spawn({ argv: [c.pythonBin ?? 'python3', '-E', '-s', script],
      input: JSON.stringify({ kind, options, account: selected, accountsDir: c.accountsDir, directory: account.directory, codexBin: c.codexBin ?? 'codex', model, cwd, ...(sessionId ? { sessionId } : {}), ...(writeRoot ? { writeRoot } : {}) }), cwd })
    let stdout = ''
    const abort = () => { void child.return({ code: null, signal: 'SIGTERM' }).catch(() => {}) }
    signal.addEventListener('abort', abort, { once: true })
    if (signal.aborted) abort()
    try {
      for await (const chunk of child) {
        if (signal.aborted) break
        if (chunk.stream === 'stdout') stdout += chunk.text
        if (stdout.length > 150_000) throw new Error('output too large')
      }
    } finally { signal.removeEventListener('abort', abort) }
    if (signal.aborted) throw new Error('cancelled')
    const reply = JSON.parse(stdout) as { text?: string }
    if (options.gate) {
      const verdict = readGate(reply.text ?? '')
      if (verdict.verdict === 'pass' && verdict.fingerprint && sessionId) gatePasses.set(sessionId, verdict.fingerprint)
      return { text: formatOutput(selected, model, gateDisplay(verdict)) }
    }
    return { text: formatOutput(selected, model, reply.text ?? 'Delegation failed.', options.write) }
  } catch (error) {
    const message = error instanceof Error && /^(Unclosed quote|Unknown flag|Repeated flag|Missing value|Invalid effort|A task|Native review|Review focus|Gate accepts)/.test(error.message) ? error.message : 'Delegation failed or was cancelled; the result is incomplete. Longer jobs will require the future background feature.'
    return { text: 'model-mod: ' + message }
  }
}


export async function transfer($: EngineInterface, args: string, c: DelegateConfig | undefined, transcript: string | undefined, signal: AbortSignal, interactive: boolean): Promise<{ text: string }> {
  const tokens = args.trim() ? args.trim().split(/\s+/) : []
  if (tokens.length && (tokens.length !== 2 || tokens[0] !== '--account' || tokens[1]!.startsWith('--'))) return { text: 'model-mod: Transfer accepts only --account NAME; it does not accept model, effort or background options.' }
  const accounts = [...(c?.codex?.values() ?? [])]
  const names = [...new Set(accounts.map(a => a.account))]
  let current = ''
  try { current = await $.session.model() } catch { /* use a unique configured account */ }
  const selected = tokens[1] ?? c?.codex?.get(current)?.account ?? (names.length === 1 ? names[0] : undefined)
  if (!selected || !names.includes(selected)) return { text: 'model-mod: Choose a configured Codex account with --account.' }
  if (!interactive || !transcript || !c?.accountsDir || !$.plugin.root) return { text: 'model-mod: Transfer requires an interactive session with an available transcript.' }
  const denied = 'model-mod: Transfer was not confirmed; no transcript was imported.'
  let started = false
  try {
    const choice = await $.ui.ask(`Import this session into Codex account ${cleanDisplay(selected)}? Conversation content will be imported into this account and persist with OpenAI; deleting local content does not remove it. Maximum transcript size: 20 MiB. Repeated imports may create duplicates. Import this session?`, ['Cancel', 'Import session'])
    if (choice !== 'Import session' || signal.aborted) return { text: denied }
    const root = $.plugin.root
    const sep = root.includes('\\') && !root.includes('/') ? '\\' : '/'
    const script = root.replace(/[\\/]+$/, '') + sep + 'helper' + sep + 'delegate.py'
    started = true
    const child = $.process.spawn({ argv: [c.pythonBin ?? 'python3', '-E', '-s', script], cwd: await $.session.cwd(), input: JSON.stringify({ kind: 'transfer', transcript, account: selected, accountsDir: c.accountsDir, directory: accounts.find(a => a.account === selected)!.directory, codexBin: c.codexBin ?? 'codex', cwd: await $.session.cwd() }) })
    let stdout = ''
    const abort = () => { void child.return({ code: null, signal: 'SIGTERM' }).catch(() => {}) }
    signal.addEventListener('abort', abort, { once: true })
    if (signal.aborted) abort()
    try { for await (const chunk of child) { if (chunk.stream === 'stdout') stdout += chunk.text; if (stdout.length > 4096) throw new Error('output too large') } }
    finally { signal.removeEventListener('abort', abort) }
    if (signal.aborted) return { text: 'model-mod: Transfer was not confirmed.' }
    const reply = JSON.parse(stdout) as { text?: string }
    return { text: `Codex (${cleanDisplay(selected)}): ${cleanDisplay(reply.text ?? 'Transfer was not confirmed.')}` }
  } catch { return { text: started ? 'model-mod: Transfer was not confirmed; it may have been imported.' : denied } }
}

type Job = { id: string; state: string; account: string; model: string; kind: string; mode?: string; createdAt: number; errorCode?: string | null }
type Reply = { ok: boolean; error?: string; job?: Job; jobs?: Job[]; text?: string }
const terminal = new Set(['completed', 'failed', 'cancelled', 'interrupted', 'unknown'])
const polling = new Set<string>()
const errors: Record<string, string> = {
  timeout: 'total time limit reached', idle_timeout: 'inactivity time limit reached',
  account_mismatch: 'account verification failed', not_logged_in: 'account is not logged in',
  codex_too_old: 'Codex needs an update', possible_leftover: 'process cleanup could not be confirmed',
  broker_restarted: 'broker restarted', broker_stopped: 'broker stopped', delegation_failed: 'delegation failed',
  runner_start_failed: 'runner could not start', runner_exited: 'runner exited unexpectedly',
}

async function client($: EngineInterface, c: DelegateConfig | undefined, method: string, payload: object): Promise<Reply> {
  const root = $.plugin.root
  if (!root) throw new Error('plugin root unavailable')
  const sep = root.includes('\\') && !root.includes('/') ? '\\' : '/'
  const script = root.replace(/[\\/]+$/, '') + sep + 'helper' + sep + 'delegate.py'
  try {
    const run = await $.process.run([c?.pythonBin ?? 'python3', '-E', '-s', script, 'client', method], { stdin: JSON.stringify(payload), timeoutMs: 5000 })
    const reply = JSON.parse(run.stdout) as Reply
    if (reply.error === 'Background broker unavailable; start a new session to launch it.') reply.error = 'Background jobs need a new session to start the broker; restart Claude Code.'
    return reply
  } catch {
    return { ok: false, error: 'Background jobs need a new session to start the broker; restart Claude Code.' }
  }
}

export function pollJob($: EngineInterface, c: DelegateConfig | undefined, id: string): void {
  if (polling.has(id)) return
  polling.add(id)
  let rounds = 0
  const tick = () => {
    $.clock.after(15_000, () => {
      void (async () => {
        try {
          if (++rounds > 140) { polling.delete(id); return }
          const reply = await client($, c, 'status', { id })
          if (!reply.ok || !reply.job) { polling.delete(id); return }
          if (terminal.has(reply.job.state)) {
            polling.delete(id)
            const short = cleanDisplay(id.slice(0, 12))
            await $.ui.toast(`Codex job ${short} finished (${cleanDisplay(reply.job.state)}); run /model-mod:result ${short}`)
          } else if (rounds >= 140) polling.delete(id)
          else tick()
        } catch { polling.delete(id) }
      })()
    })
  }
  try { tick() } catch { polling.delete(id) }
}

function jobLine(job: Job): string {
  const date = Number.isFinite(job.createdAt) ? new Date(job.createdAt * 1000).toISOString() : 'unknown'
  const error = job.errorCode ? ` — ${errors[job.errorCode] ?? job.errorCode}` : ''
  return cleanDisplay(`${job.id.slice(0, 12)}  ${job.state}  ${job.account}  ${job.model}  ${job.kind}${job.mode === 'write' ? '  write' : ''}  ${date}${error}`)
}

export async function backgroundCommand($: EngineInterface, command: 'jobs' | 'result' | 'cancel', args: string, c: DelegateConfig | undefined): Promise<{ text: string }> {
  try {
    const tokens = args.trim() ? args.trim().split(/\s+/) : []
    let id: string | undefined, all = false, clear = false
    for (const token of tokens) {
      if (command === 'jobs' && token === '--all' && !all) { all = true; continue }
      if (command === 'jobs' && token === '--clear' && !clear) { clear = true; continue }
      if (id || token.startsWith('--')) throw new Error('Unexpected argument: ' + token)
      id = token
    }
    if (id && !/^[0-9a-f]{4,32}$/.test(id)) throw new Error('Invalid job ID; use at least 4 lowercase hexadecimal characters.')
    if (command !== 'jobs' && !id) throw new Error('Provide a job ID from /model-mod:jobs.')
    if (id && (all || clear)) throw new Error('Use a job ID without --all or --clear.')
    const method = command === 'jobs' ? id ? 'status' : 'list' : command
    const payload = method === 'list' ? { cwd: await $.session.cwd(), all, clear } : { id }
    const reply = await client($, c, method, payload)
    if (!reply.ok) return { text: 'model-mod: ' + cleanDisplay(reply.error ?? 'Background request failed.') }
    if (method === 'list') return { text: reply.jobs?.length ? reply.jobs.map(jobLine).join('\n') : 'No jobs found.' }
    if (!reply.job) throw new Error('Invalid broker response.')
    if (method === 'result') return { text: formatOutput(reply.job.account, reply.job.model, reply.text ?? '', reply.job.mode === 'write') }
    return { text: jobLine(reply.job) }
  } catch (error) { return { text: 'model-mod: ' + cleanDisplay(error instanceof Error ? error.message : 'Background request failed.') } }
}
