import { wrap } from './status.ts'

export type NetworkCategory = 'refused' | 'dns' | 'timeout' | 'tls' | 'unreachable'
export type ModelResult = { category: NetworkCategory | 'not-json' | 'http'; status?: number } | { category: 'ok' }
export type Check = { mark: 'OK' | '!' | 'LIMIT' | '--'; what: string; cause?: string; next?: string }

// Only the category escapes this function; an exception can contain a URL or credentials.
export function networkCategory(error: unknown): NetworkCategory {
  const e = error as { message?: unknown; code?: unknown; cause?: { message?: unknown; code?: unknown } } | null
  const text = [e?.message, e?.code, e?.cause?.message, e?.cause?.code].filter(x => typeof x === 'string').join(' ').toLowerCase()
  if (/econnrefused|connection refused/.test(text)) return 'refused'
  if (/enotfound|eai_again|dns|name resolution|getaddrinfo/.test(text)) return 'dns'
  if (/timeout|timed out|etimedout|aborterror/.test(text)) return 'timeout'
  if (/tls|ssl|certificate|cert_|self.signed/.test(text)) return 'tls'
  return 'unreachable'
}

export function classifyModel(result: ModelResult, host: string): Check {
  const what = `API models list (${host})`
  if (result.category === 'ok') return { mark: 'OK', what }
  let cause: string, next: string
  if (result.category === 'http' && (result.status === 401 || result.status === 403)) {
    cause = 'The API key was rejected.'; next = 'Check the API key in plugin settings.'
  } else if (result.category === 'http' && result.status === 404) {
    cause = 'The base URL may have a missing or extra /v1.'; next = 'Set the base URL without /v1; see the setup documentation.'
  } else if (result.category === 'http' && result.status === 429) {
    cause = 'The API server rate limited the request.'; next = 'Wait and try again.'
  } else if (result.category === 'http' && (result.status ?? 0) >= 500) {
    cause = 'The API server returned an error.'; next = 'Try again later.'
  } else if (result.category === 'not-json') {
    cause = 'The server did not return a valid, non-empty models list.'; next = 'Check that this is an OpenAI-compatible server.'
  } else if (result.category === 'http') {
    cause = `The API server returned HTTP ${result.status ?? 'error'}.`; next = 'Check the upstream server configuration.'
  } else {
    const names = { refused: 'Connection refused', dns: 'DNS lookup failed', timeout: 'The connection timed out', tls: 'TLS verification failed', unreachable: 'The connection failed' }
    cause = `${names[result.category]}: the URL is unreachable.`; next = 'Check the address and network.'
  }
  return { mark: '!', what, cause, next }
}

export function renderDoctor(checks: Check[], columns = 80): string {
  const width = Math.max(20, Math.min(80, columns))
  const lines: string[] = []
  for (const check of checks) {
    const prefix = `[${check.mark}]  `
    wrap(check.what, width - prefix.length).forEach((line, i) => lines.push((i ? ' '.repeat(prefix.length) : prefix) + line))
    for (const [label, value] of [['cause', check.cause], ['next', check.next]] as const) {
      if (!value) continue
      const indent = `  ${label}: `
      wrap(value, width - indent.length).forEach((line, i) => lines.push((i ? ' '.repeat(indent.length) : indent) + line))
    }
  }
  const problems = checks.filter(c => c.mark === '!' || c.mark === 'LIMIT').length
  lines.push(problems ? `${problems} problem${problems === 1 ? '' : 's'}; see docs/TROUBLESHOOTING.md` : 'no problems found')
  return '\n' + lines.join('\n')
}
