import type { TrackedAgent } from '../types'

export type Thinking = { type: 'thinking'; thinking: string; signature: string }
export const API_SIGNATURE = /^gAAAA/
export const CODEX_SIGNATURE = /^mmcx1:/

export function buildStepMessages(history: readonly TrackedAgent['turns'][number][], codex: boolean, keepThinking: boolean, stash: ReadonlyMap<string, Thinking[]>) {
  const messages = history.map(message => ({ ...message, content: message.content.filter(block => {
    const type = block.type
    return !['thinking', 'redacted_thinking', 'server_tool_use'].includes(type) && !type.endsWith('_tool_result')
  }) })).filter(message => message.content.length > 0)
  while (messages.length && messages[0]!.role !== 'user') messages.shift()
  let withThinking: typeof messages | undefined
  if (keepThinking && stash.size > 0) {
    let any = false
    withThinking = messages.map(message => {
      if (message.role !== 'assistant') return message
      const ids = message.content.filter(b => b.type === 'tool_use').map(b => String((b as { id?: unknown }).id))
      const kept = ids.map(id => stash.get(id)?.filter(b => (codex ? CODEX_SIGNATURE : API_SIGNATURE).test(b.signature))).find(blocks => blocks?.length)
      if (!kept) return message
      any = true
      return { ...message, content: [...kept, ...message.content] }
    })
    if (!any) withThinking = undefined
  }
  return { messages, withThinking }
}

type StderrState = { httpStatus: number; retryAfter: number | undefined; reasoningRebuilt: boolean }
export function parseStepStderr(line: string, codex: boolean, state: StderrState): StderrState {
  let { httpStatus, retryAfter, reasoningRebuilt } = state
  if (codex && line.replace(/\r$/, '') === 'model-mod-note:Codex login: reasoning discarded; retrying once') reasoningRebuilt = true
  const status = /^model-mod-http:(\d{3})\r?$/.exec(line)
  if (status) httpStatus = Number(status[1])
  if (line.startsWith('model-mod-retry-after:')) {
    const seconds = /^model-mod-retry-after:[ \t]*(\d+)[ \t]*\r?$/.exec(line)
    retryAfter = seconds && Number.isSafeInteger(Number(seconds[1])) ? Number(seconds[1]) : undefined
  }
  return { httpStatus, retryAfter, reasoningRebuilt }
}

const RETRYABLE_HTTP_STATUS = [429, 502, 503, 504, 529]
type StepFailureInput = {
  codex?: { account: string }
  error: { type: unknown } | undefined; exitCode: number | null; httpStatus: number; rawError: string
  retryAfter: number | undefined; streamed: boolean; sendThinking: boolean; attempt: number; retryDelays: readonly number[]
}
type StepDecision = { kind: 'failure'; reason: string; limitFailed: boolean } | { kind: 'not-logged-in' } | { kind: 'thinking' } |
  { kind: 'retry'; delay: number; status?: string; loginRecheck: boolean }
export function classifyStepFailure(input: StepFailureInput): StepDecision {
  let { codex, error, exitCode, httpStatus, rawError, retryAfter, streamed, sendThinking, attempt, retryDelays } = input
  const curlError = [6, 7].includes(exitCode ?? 0) ? `could not connect (curl ${exitCode})` :
    exitCode === 28 ? 'request timed out (curl 28)' : [35, 60, 51, 58, 59].includes(exitCode ?? 0) ? `TLS error (curl ${exitCode})` : 'curl failed'
  // A body the stream parser could not read says nothing about the HTTP status, which is 200 here.
  const unreadable = error?.type === 'invalid_stream' && httpStatus < 400
  let reason = httpStatus === 429 ? 'upstream rate limited (HTTP 429)' : unreadable ? 'upstream sent an unreadable response' :
    error || exitCode === 22 ? 'HTTP error' : exitCode !== 0 ? curlError : 'incomplete upstream response'
  let type: unknown = error?.type
  if (!error) {
    try { type = JSON.parse(rawError).error?.type } catch { /* SSE, not JSON */ }
  }
  if (['api_error', 'authentication_error', 'permission_error', 'not_found_error',
    'invalid_request_error', 'rate_limit_error', 'overloaded_error'].includes(type as string)) reason += ` (${type})`
  let errorCode: string | undefined
  let errorMessage = ''
  if (codex) {
    try {
      const match = /event: error\r?\n(?:[^\n]*\n)*?data: ([^\n]+)/.exec(rawError)
      const value = JSON.parse(match ? match[1]! : rawError)
      errorCode = value.error?.code
      errorMessage = typeof value.error?.message === 'string' ? value.error.message : ''
    } catch { /* no structured error */ }
    const prefix = `Codex login (${codex.account}): `
    if (errorCode === 'codex_rejected_request') return { kind: 'failure', reason: prefix + 'request rejected by Codex; update model-mod or report this', limitFailed: false }
    if (errorCode === 'unsupported_item') {
      const kind = /unsupported codex behavior: ([A-Za-z0-9_-]{1,64})/.exec(errorMessage)?.[1] ?? 'unknown'
      return { kind: 'failure', reason: prefix + `Codex used a built-in tool that model-mod does not support (${kind}); try again, and report it if it keeps happening`, limitFailed: false }
    }
    if (errorCode === 'protocol' || exitCode === 65) return { kind: 'failure', reason: prefix + 'incompatible app-server protocol; update or check Codex', limitFailed: false }
    if (errorCode === 'codex_unavailable' || exitCode === 66) return { kind: 'failure', reason: prefix + 'codex unavailable; install Codex or configure codexBin', limitFailed: false }
    if (errorCode === 'codex_too_old' || exitCode === 67) return { kind: 'failure', reason: prefix + 'codex too old; upgrade to 0.165.0 or newer', limitFailed: false }
    if (errorCode === 'codex_not_logged_in' || exitCode === 68) return { kind: 'not-logged-in' }
    if (errorCode === 'invalid_home' || exitCode === 69) return { kind: 'failure', reason: prefix + 'account directory missing; run /model-mod:setup', limitFailed: false }
    if (exitCode === 78) return { kind: 'failure', reason: prefix + 'Python too old; install Python 3.9 or newer', limitFailed: false }
    reason = prefix + (httpStatus === 429 ? 'rate limited; check the account quota or try again later' : httpStatus === 504 ? 'app-server timed out; try again in a moment' : 'app-server request failed; check Codex and try again')
  }
  const transient = codex
    ? (errorCode === undefined || errorCode === 'bridge_error' || errorCode === 'timeout') && (RETRYABLE_HTTP_STATUS.includes(httpStatus) || httpStatus >= 500)
    : error || exitCode === 22
      ? RETRYABLE_HTTP_STATUS.includes(httpStatus) || ['rate_limit_error', 'overloaded_error', 'api_error'].includes(type as string)
      : exitCode === 0 || (exitCode !== null && [6, 7, 18, 28, 35, 52, 55, 56].includes(exitCode))
  // Only an answer that is itself a rate limit or overload carries a meaningful Retry-After; on a 200 whose stream broke it is ignored.
  if (!RETRYABLE_HTTP_STATUS.includes(httpStatus)) retryAfter = undefined
  const limitFailed = !!codex && (httpStatus === 429 || type === 'rate_limit_error')
  if (!streamed && transient && retryAfter !== undefined && retryAfter > 15) {
    return { kind: 'failure', reason: `${reason}${httpStatus && httpStatus !== 429 ? ` (HTTP ${httpStatus})` : ''}, retry after ${retryAfter}s`, limitFailed }
  }
  if (!codex && !streamed && sendThinking && type === 'invalid_request_error') return { kind: 'thinking' }
  if (!streamed && transient && attempt < retryDelays.length) {
    return { kind: 'retry', loginRecheck: !!codex && attempt === retryDelays.length - 1 && !(httpStatus >= 400 && httpStatus < 500),
      ...(!codex ? { status: `${reason}; retrying (${attempt + 1}/${retryDelays.length})` } : {}),
      delay: Math.max(retryDelays[attempt]!, (retryAfter ?? 0) * 1000) }
  }
  return { kind: 'failure', reason, limitFailed }
}
