import { test, expect } from 'claude-code/testing'
import { renderStatus, cellWidth, wrap, resetText, bar } from './status.ts'
import type { StatusView } from './status.ts'

// Local wall-clock times, so the expected "(14:14)" does not depend on the machine's time zone.
const at = (hour: number, minute = 0, day = 1) => Math.floor(new Date(2026, 10, day, hour, minute, 0).getTime() / 1000)
const NOW = at(12)

const VIEW: StatusView = {
  title: 'model-mod 0.2.2: picker=active; 2 warnings',
  warnings: ['headerFile not found', 'plain http to a non-loopback host sends the API key unencrypted'],
  quota: [
    { title: 'Codex main', details: ['plus plan', 'logged in'], credits: 'available (5)',
      windows: [{ label: '5h', used: 48, resetsAt: at(14, 14) }, { label: 'weekly', used: 19, resetsAt: at(8, 0, 5) }] },
    { title: 'Codex backup', details: ['pro plan', 'logged in'], limit: 'rate limit reached',
      windows: [{ label: '5h', used: 100, resetsAt: at(13, 5) }, { label: 'weekly', used: 40, resetsAt: at(8, 0, 6) }] },
    { title: 'Codex team', details: ['team plan', 'logged in'],
      windows: [{ label: '5h', used: 30, resetsAt: at(15) }, { label: 'weekly', used: 100, resetsAt: at(8, 0, 3) }] },
    { title: 'Codex flaky', details: ['login unknown'], windows: [], failed: 'rate-limit request did not complete' },
    { title: 'API 127.0.0.1', details: ['key configured'], windows: [], noData: true },
  ],
  path: [{ label: 'Session model', value: 'main/gpt-6.1-terra' }, { label: 'Route', value: 'Codex login' }],
  groups: [
    { title: 'Picker', rows: [{ label: 'picker', value: 'active' }, { label: 'models', value: '3' }] },
    { title: 'Tools', rows: [{ label: 'tools', value: 'missing', warn: true }] },
    { title: 'Prompts', rows: [{ label: 'files', value: 'compact, title' }] },
  ],
}

const lines = (text: string) => text.split('\n')
const longest = (text: string) => Math.max(...lines(text).map(cellWidth))
const render = (columns: number, ascii = false) => renderStatus(VIEW, { columns, ascii, now: NOW })

test('status: one block per account with percent used, reset time and text markers', () => {
  const text = render(80)
  expect(text).toContain('Codex main · plus plan · logged in')
  expect(text).toMatch(/5h +\[\S+\] +48% used +resets in 2h 14m \(14:14\)/)
  expect(text).toMatch(/weekly +\[\S+\] +19% used +resets in 3d 20h \(Nov 5 08:00\)/)
  expect(text).toMatch(/credits +available \(5\)/)
  expect(text.indexOf('QUOTA')).toBeLessThan(text.indexOf('CURRENT PATH'))
  expect(text.indexOf('CURRENT PATH')).toBeLessThan(text.indexOf('DIAGNOSTICS'))
})

test('status: exhausted and limited accounts are marked in text with the reason', () => {
  const text = lines(render(80))
  const backup = text.findIndex(l => l.includes('Codex backup'))
  expect(text[backup]).toMatch(/^\[LIMIT\] /)
  expect(text[backup + 1]).toMatch(/^\[LIMIT\] +5h .*100% used/)
  expect(text.slice(backup, backup + 6).join('\n')).toContain('limit reached: rate limit reached')
  // Only the weekly window of the next account is exhausted; its 5h row carries no marker.
  const team = text.findIndex(l => l.includes('Codex team'))
  expect(text[team]).toMatch(/^\[LIMIT\] /)
  expect(text[team + 1]).toMatch(/^ {8}5h /)
  expect(text[team + 2]).toMatch(/^\[LIMIT\] +weekly .*100% used/)
  expect(text.find(l => l.includes('Codex main'))).toMatch(/^\[OK\] /)
})

test('status: upstream allowed but full window warns that requests may fail', () => {
  const view: StatusView = { ...VIEW, quota: [{ title: 'Codex test', windows: [{ label: 'weekly', used: 100, resetsAt: null }], allowedButFull: true }] }
  const text = renderStatus(view, { columns: 100, ascii: true, now: NOW })
  expect(text).toContain('upstream still reports usage allowed; a window is full, so requests may fail')
  expect(text).toContain('[LIMIT] Codex test')
})

test('status: a failed account shows only the fixed text and its reason, and the others stay', () => {
  const text = render(80)
  const flaky = lines(text).findIndex(l => l.includes('Codex flaky'))
  expect(lines(text)[flaky]).toMatch(/^\[!\] /)
  expect(lines(text)[flaky + 1]).toContain('無法取得: rate-limit request did not complete')
  expect(lines(text)[flaky + 1]).not.toMatch(/% used|\[[█░#-]+\]/)
  expect(text).toContain('Codex main'); expect(text).toContain('Codex backup')
})

test('status: an API upstream says there is no quota data and draws no bar', () => {
  const text = lines(render(80))
  const api = text.findIndex(l => l.includes('API 127.0.0.1'))
  expect(text[api]).toMatch(/^\[--\] /)
  expect(text[api + 1]).toContain('沒有額度資料')
  expect(text[api + 1]).not.toMatch(/% used|\[[█░#-]+\]/)
})

test('status: warnings come first and are always shown', () => {
  const text = render(80)
  expect(text.indexOf('WARNINGS')).toBeLessThan(text.indexOf('QUOTA'))
  expect(text).toContain('[!] headerFile not found')
  expect(text).toContain('[!] plain http to a non-loopback host sends the API key unencrypted')
  expect(renderStatus({ ...VIEW, warnings: [] }, { columns: 80, ascii: false, now: NOW })).not.toContain('WARNINGS')
  // An anomaly in a diagnostic row is marked in its margin.
  expect(text).toMatch(/\[!\] tools +missing/)
})

test('status: no line is wider than the terminal at 80, 60 and 140 columns', () => {
  for (const columns of [80, 60, 140]) {
    const text = renderStatus({ ...VIEW,
      warnings: ['a long warning '.repeat(12) + 'x'.repeat(120)],
      groups: [...VIEW.groups, { title: 'Codex main', rows: [{ label: 'dir', value: '/fake-home/.config/model-mod/accounts/' + 'deep/'.repeat(20) }] }] },
    { columns, ascii: false, now: NOW })
    expect(longest(text)).toBeLessThanOrEqual(Math.min(columns - 6, 100))
  }
})

test('status: a wide terminal gets longer bars and two diagnostic columns, not stretched rows', () => {
  const narrow = render(80), wide = render(140)
  const barLength = (text: string) => /\[([█░]+)\]/.exec(text.split('\n').find(l => l.includes('48% used'))!)![1]!.length
  expect(barLength(wide)).toBeGreaterThan(barLength(narrow))
  expect(longest(wide)).toBeLessThanOrEqual(100)
  expect(wide.split('\n').some(l => l.includes('Picker') && l.includes(' │ ') && l.includes('Tools'))).toBe(true)
  expect(narrow).not.toContain(' │ ')
})

test('status: ascii mode has plain bars, no escape codes in either mode, and states stay in text', () => {
  for (const ascii of [false, true]) {
    const text = render(80, ascii)
    expect(text).not.toContain('\x1b')
    for (const marker of ['[OK]', '[!]', '[LIMIT]', '[--]']) expect(text).toContain(marker)
  }
  const plain = render(80, true)
  const barLines = lines(plain).filter(l => l.includes('% used'))
  expect(barLines.length).toBeGreaterThan(0)
  for (const l of barLines) expect(l).toMatch(/^[\x20-\x7e]*$/)
  expect(plain).not.toMatch(/[█░─│·]/)
  expect(render(80)).toMatch(/[█░]/)
})

test('status: a line break or control character in a value stays inside its row', () => {
  const text = renderStatus({ ...VIEW, groups: [{ title: 'Codex x', rows: [{ label: 'dir', value: '/a/b\nc\x1b[31md' }] }] }, { columns: 80, ascii: false, now: NOW })
  expect(text).not.toContain('\x1b')
  expect(lines(text).filter(l => l.includes('/a/b'))).toHaveLength(1)
  expect(lines(text).find(l => l.includes('/a/b'))).toContain('/a/b c [31md')
})

test('status helpers: wide characters count twice, reset text is relative plus local time, bars are full only at 100%', () => {
  expect(cellWidth('無法取得')).toBe(8)
  expect(wrap('a'.repeat(25), 10)).toEqual(['a'.repeat(10), 'a'.repeat(10), 'a'.repeat(5)])
  expect(resetText(at(12, 0, 1) + 30, NOW)).toBe('resets in <1m (12:00)')
  expect(resetText(at(12, 45), NOW)).toBe('resets in 45m (12:45)')
  expect(resetText(at(11), NOW)).toBe('reset due (11:00)')
  expect(resetText(null, NOW)).toBe('reset time unavailable')
  expect(bar(99.6, 10, true)).toBe('[#########-]')
  expect(bar(100, 10, true)).toBe('[##########]')
  expect(bar(0.4, 10, true)).toBe('[#---------]')
  expect(bar(0, 10, true)).toBe('[----------]')
})
