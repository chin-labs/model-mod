// Layout of /model-mod:status. Pure functions: register.ts gathers the data and passes it in, so the layout can be
// tested at any width without an engine.
//
// A slash command's text is a plain transcript row in the terminal (no Markdown, no colour), so the layout is plain
// aligned text and every state is spelled out as well: `[OK]`, `[!]`, `[LIMIT]` and `[--]` in a margin, never colour alone.
// The text starts with a line break: the client puts "model-mod:" in front of the first line, and this keeps the title
// from sitting behind it.
// No line is wider than the width given: the longest reset text decides the bar length, text that still does not fit
// moves to its own line, and wide terminals widen the bars and put the diagnostic groups in two columns instead of
// stretching the rows.

export type Mark = 'ok' | 'warn' | 'limit' | 'none'
export type QuotaWindow = { label: string; used: number | null; resetsAt: number | null }
export type QuotaBlock = {
  title: string
  // "plus", "logged in": shown after the title.
  details?: string[]
  windows: QuotaWindow[]
  credits?: string
  // Set when the account may not be used now: the reason from rateLimitReachedType, or '' when there is none.
  limit?: string
  allowedButFull?: boolean
  // Why the numbers could not be read; the block then shows a fixed "無法取得" line.
  failed?: string
  // An upstream that reports no quota (an API server).
  noData?: boolean
}
export type Row = { label: string; value: string; warn?: boolean }
export type Group = { title: string; rows: Row[] }
export type StatusView = { title: string; warnings: string[]; quota: QuotaBlock[]; path: Row[]; groups: Group[] }
export type RenderOptions = {
  // The terminal's width as the command runs (CommandPresentation.columns).
  columns: number
  // No box-drawing or block glyphs: `#`/`-` bars. Set when NO_COLOR is set or the terminal is dumb.
  ascii: boolean
  // Epoch seconds.
  now: number
}

export const NEAR_LIMIT = 90

const MARK_TEXT: Record<Mark, string> = { ok: '[OK]', warn: '[!]', limit: '[LIMIT]', none: '[--]' }
const MARGIN = 8
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
// East Asian wide and fullwidth blocks take two cells.
const WIDE = /[ᄀ-ᅟ⺀-꓏가-힣豈-﫿︰-﹯＀-｠￠-￦]/

export function cellWidth(text: string): number {
  let n = 0
  for (const ch of text) n += WIDE.test(ch) ? 2 : 1
  return n
}

const padEnd = (text: string, width: number) => text + ' '.repeat(Math.max(0, width - cellWidth(text)))
const padStart = (text: string, width: number) => ' '.repeat(Math.max(0, width - cellWidth(text))) + text
// A line break or control character in a value must not split a row.
const clean = (text: string) => text.replace(/[\x00-\x1f\x7f]/g, ' ')

// Breaks text at spaces into lines of at most `width` cells; a word longer than a line is cut.
export function wrap(text: string, width: number): string[] {
  const max = Math.max(2, width)
  const lines: string[] = []
  let line = ''
  const flush = () => { if (line) { lines.push(line); line = '' } }
  for (const word of clean(text).split(' ').filter(Boolean)) {
    let rest = word
    while (cellWidth(rest) > max) {
      flush()
      let head = '', used = 0
      for (const ch of rest) {
        const w = cellWidth(ch)
        if (used + w > max) break
        head += ch; used += w
      }
      lines.push(head); rest = rest.slice(head.length)
    }
    if (!line) line = rest
    else if (cellWidth(line) + 1 + cellWidth(rest) <= max) line += ' ' + rest
    else { flush(); line = rest }
  }
  flush()
  return lines.length ? lines : ['']
}

const two = (n: number) => String(n).padStart(2, '0')

function relative(seconds: number): string {
  if (seconds < 60) return '<1m'
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes}m`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h ${minutes % 60}m`
  return `${Math.floor(hours / 24)}d ${hours % 24}h`
}

function clock(epoch: number, now: number): string {
  const at = new Date(epoch * 1000), today = new Date(now * 1000)
  const time = `${two(at.getHours())}:${two(at.getMinutes())}`
  const sameDay = at.getFullYear() === today.getFullYear() && at.getMonth() === today.getMonth() && at.getDate() === today.getDate()
  return sameDay ? time : `${MONTHS[at.getMonth()]} ${at.getDate()} ${time}`
}

// "resets in 2h 14m (14:30)": relative first, the local wall-clock time in brackets.
export function resetText(resetsAt: number | null, now: number): string {
  if (resetsAt === null) return 'reset time unavailable'
  const left = resetsAt - now
  return left <= 0 ? `reset due (${clock(resetsAt, now)})` : `resets in ${relative(left)} (${clock(resetsAt, now)})`
}

export function windowMark(window: QuotaWindow): Mark {
  if (window.used === null) return 'warn'
  return window.used >= 100 ? 'limit' : window.used >= NEAR_LIMIT ? 'warn' : 'ok'
}

export function blockMark(block: QuotaBlock): Mark {
  if (block.noData) return 'none'
  if (block.limit !== undefined || block.windows.some(w => windowMark(w) === 'limit')) return 'limit'
  if (block.failed !== undefined || block.windows.some(w => windowMark(w) === 'warn')) return 'warn'
  return 'ok'
}

// A bar that is full only at 100% and empty only at 0%.
export function bar(used: number, inner: number, ascii: boolean): string {
  const clamped = Math.min(100, Math.max(0, used))
  let filled = Math.round(clamped / 100 * inner)
  if (clamped < 100 && filled >= inner) filled = inner - 1
  if (clamped > 0 && filled < 1) filled = 1
  return '[' + (ascii ? '#' : '█').repeat(filled) + (ascii ? '-' : '░').repeat(inner - filled) + ']'
}

const margin = (mark: Mark | undefined) => padEnd(mark && mark !== 'ok' ? MARK_TEXT[mark] : '', MARGIN)

function quotaLines(blocks: QuotaBlock[], o: RenderOptions, width: number): string[] {
  const dot = o.ascii ? ' | ' : ' · '
  const windows = blocks.flatMap(b => b.windows)
  const labelWidth = Math.min(10, Math.max(6, ...windows.map(w => cellWidth(clean(w.label)))))
  const longest = Math.max(0, ...windows.map(w => cellWidth(resetText(w.resetsAt, o.now))))
  // margin, label and a space, bar with brackets, two spaces, "100% used", two spaces, reset text
  const inner = Math.min(28, Math.max(10, width - (MARGIN + labelWidth + 1 + 2 + 2 + 9 + 2) - longest))
  const lines: string[] = []
  for (const block of blocks) {
    if (lines.length) lines.push('')
    const mark = blockMark(block)
    const head = [clean(block.title), ...(block.details ?? []).map(clean)].join(dot)
    const headLines = wrap(head, width - MARGIN)
    headLines.forEach((text, i) => lines.push((i === 0 ? padEnd(MARK_TEXT[mark], MARGIN) : margin(undefined)) + text))
    if (block.noData) lines.push(margin(undefined) + '沒有額度資料 (this upstream reports no quota)')
    for (const w of block.windows) {
      const wm = windowMark(w)
      const label = padEnd(clean(w.label), labelWidth)
      const reset = resetText(w.resetsAt, o.now)
      if (w.used === null) {
        lines.push(margin(wm) + label + ' usage unavailable')
        continue
      }
      const used = Math.round(Math.min(100, Math.max(0, w.used)))
      const head = margin(wm) + label + ' ' + bar(used, inner, o.ascii) + '  ' + padStart(`${used}% used`, 9)
      if (cellWidth(head) + 2 + cellWidth(reset) <= width) lines.push(head + '  ' + reset)
      else { lines.push(head); lines.push(' '.repeat(MARGIN + labelWidth + 1) + reset) }
    }
    if (block.limit !== undefined) {
      wrap(block.limit ? `limit reached: ${block.limit}` : 'ordinary usage is not allowed now', width - MARGIN).forEach((text, i) => lines.push(margin(i === 0 ? 'limit' : undefined) + text))
    }
    if (block.allowedButFull) {
      wrap('upstream still reports usage allowed; a window is full, so requests may fail', width - MARGIN).forEach((text, i) => lines.push(margin(i === 0 ? 'limit' : undefined) + text))
    }
    if (block.credits) lines.push(margin(undefined) + padEnd('credits', labelWidth) + ' ' + clean(block.credits))
    if (block.failed !== undefined) {
      wrap(`無法取得: ${block.failed}`, width - MARGIN).forEach((text, i) => lines.push(margin(i === 0 ? 'warn' : undefined) + text))
    }
  }
  return lines
}

// "    label       value" with the value wrapped under itself; anomalies carry `[!]` in the 4-cell margin.
function rowLines(rows: Row[], width: number, indent: string): string[] {
  const labelWidth = Math.min(18, Math.max(0, ...rows.map(r => cellWidth(clean(r.label)))))
  const lines: string[] = []
  for (const row of rows) {
    const lead = indent + (row.warn ? '[!] ' : '    ') + padEnd(clean(row.label), labelWidth) + '  '
    const wrapped = wrap(row.value, Math.max(8, width - cellWidth(lead)))
    wrapped.forEach((text, i) => lines.push((i === 0 ? lead : ' '.repeat(cellWidth(lead))) + text))
  }
  return lines
}

function groupLines(group: Group, width: number): string[] {
  return [clean(group.title), ...rowLines(group.rows, width, '  ')]
}

function section(title: string, ascii: boolean, width: number): string {
  const fill = Math.max(2, width - cellWidth(title) - 4)
  return `${ascii ? '--' : '──'} ${title} ${(ascii ? '-' : '─').repeat(fill)}`
}

export function renderStatus(view: StatusView, o: RenderOptions): string {
  // The Markdown view wraps a few cells before the terminal edge; leave that room and cap the width so a wide
  // terminal gets longer bars and a second diagnostic column, not stretched rows.
  const columns = Number.isFinite(o.columns) && o.columns > 0 ? Math.floor(o.columns) : 80
  const width = Math.min(100, Math.max(30, columns - 6))
  const out: string[] = [...wrap(view.title, width)]
  if (view.warnings.length) {
    out.push('', section('WARNINGS', o.ascii, width))
    for (const w of view.warnings) wrap(w, width - 4).forEach((text, i) => out.push((i === 0 ? '[!] ' : '    ') + text))
  }
  if (view.quota.length) out.push('', section('QUOTA', o.ascii, width), ...quotaLines(view.quota, o, width))
  if (view.path.length) out.push('', section('CURRENT PATH', o.ascii, width), ...rowLines(view.path, width, ''))
  if (view.groups.length) {
    out.push('', section('DIAGNOSTICS', o.ascii, width))
    if (width >= 90) {
      const column = Math.floor((width - 3) / 2)
      for (let i = 0; i < view.groups.length; i += 2) {
        const left = groupLines(view.groups[i]!, column)
        const right = view.groups[i + 1] ? groupLines(view.groups[i + 1]!, column) : []
        for (let n = 0; n < Math.max(left.length, right.length); n++) {
          const l = left[n] ?? '', r = right[n]
          out.push(r === undefined ? l : padEnd(l, column) + (o.ascii ? ' | ' : ' │ ') + r)
        }
      }
    } else {
      view.groups.forEach((group, i) => { if (i) out.push(''); out.push(...groupLines(group, width)) })
    }
  }
  return '\n' + out.join('\n')
}
