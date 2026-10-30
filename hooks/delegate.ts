import type { EngineInterface } from 'claude-code'

type Account = { account: string; model: string; directory: string }
type DelegateConfig = { codex?: Map<string, Account>; accountsDir?: string; codexBin?: string; pythonBin?: string }
type Options = { account?: string; model?: string; effort?: string; base?: string; adversarial?: boolean; text: string }

function cleanDisplay(value: string): string {
  return value.replace(/\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07\x1b]*(?:\x07|\x1b\\)|.)/g, '').replace(/[\x00-\x08\x0b-\x1f\x7f-\x9f]/g, '')
}
export function formatOutput(account: string, model: string, text: string): string {
  return `Codex (${cleanDisplay(account)}, ${cleanDisplay(model)}) — no file writes; read-only commands may still run. Codex output is unverified.\n${cleanDisplay(text)}`
}

export function parseDelegate(kind: 'review' | 'rescue', input: string): Options {
  const tokens: string[] = []
  let word = '', quote = '', active = false
  for (let i = 0; i < input.length; i++) {
    const ch = input[i]!
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
  const result: Options = { text: '' }, seen = new Set<string>()
  for (let i = 0; i < tokens.length; i++) {
    const flag = tokens[i]!
    if (flag === '--') { result.text = tokens.slice(i + 1).join(' '); break }
    const allowed = ['--account', '--model', '--effort', ...(kind === 'review' ? ['--base', '--adversarial'] : [])]
    if (!allowed.includes(flag)) throw new Error('Unknown flag or text before --: ' + flag)
    if (seen.has(flag)) throw new Error('Repeated flag: ' + flag)
    seen.add(flag)
    if (flag === '--adversarial') { result.adversarial = true; continue }
    const value = tokens[++i]
    if (!value || value.startsWith('--')) throw new Error('Missing value for ' + flag)
    if (flag === '--account') result.account = value
    else if (flag === '--model') result.model = value
    else if (flag === '--effort') result.effort = value
    else result.base = value
  }
  if (result.effort && !['low', 'medium', 'high', 'xhigh'].includes(result.effort)) throw new Error('Invalid effort; use low, medium, high or xhigh.')
  if (kind === 'rescue' && !result.text.trim()) throw new Error('A task after -- is required.')
  if (kind === 'review' && !result.adversarial && result.effort) throw new Error('Native review does not support --effort; use --adversarial.')
  if (kind === 'review' && !result.adversarial && result.text) throw new Error('Review focus is supported only with --adversarial.')
  return result
}

export async function delegate($: EngineInterface, kind: 'review' | 'rescue', args: string, c: DelegateConfig | undefined, signal: AbortSignal): Promise<{ text: string }> {
  try {
    const options = parseDelegate(kind, args)
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
    const cwd = await $.session.cwd()
    if (signal.aborted) throw new Error('cancelled')
    const child = $.process.spawn({ argv: [c.pythonBin ?? 'python3', '-E', '-s', script],
      input: JSON.stringify({ kind, options, account: selected, accountsDir: c.accountsDir, directory: account.directory, codexBin: c.codexBin ?? 'codex', model, cwd }), cwd })
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
    return { text: formatOutput(selected, model, reply.text ?? 'Delegation failed.') }
  } catch (error) {
    const message = error instanceof Error && /^(Unclosed quote|Unknown flag|Repeated flag|Missing value|Invalid effort|A task|Native review|Review focus)/.test(error.message) ? error.message : 'Delegation failed or was cancelled; the result is incomplete. Longer jobs will require the future background feature.'
    return { text: 'model-mod: ' + message }
  }
}
