import { test, expect } from 'claude-code/testing'
import { classifyModel, networkCategory, renderDoctor } from './doctor.ts'
import { cellWidth } from './status.ts'

test('doctor: classify network and models-list outcomes', () => {
  for (const [message, category] of [['ECONNREFUSED', 'refused'], ['ENOTFOUND', 'dns'], ['ETIMEDOUT', 'timeout'], ['certificate expired', 'tls']] as const) {
    expect(networkCategory(new Error(message))).toBe(category)
    expect(classifyModel({ category }, 'remote').next).toContain('address and network')
  }
  for (const status of [401, 403]) expect(classifyModel({ category: 'http', status }, 'remote').cause).toContain('key was rejected')
  expect(classifyModel({ category: 'http', status: 404 }, 'remote').cause).toBe('The base URL may include /v1 or a wrong path prefix.')
  expect(classifyModel({ category: 'http', status: 429 }, 'remote').cause).toContain('rate limited')
  expect(classifyModel({ category: 'http', status: 503 }, 'remote').cause).toContain('server returned an error')
  expect(classifyModel({ category: 'not-json' }, 'remote').next).toBe('Check that the server offers a /v1/models list, or set models explicitly.')
  for (const result of [{ category: 'http', status: 404 }, { category: 'http', status: 405 }, { category: 'http', status: 501 }, { category: 'not-json' }] as const) {
    expect(classifyModel(result, 'remote', true).mark).toBe('--')
    expect(classifyModel(result, 'remote').mark).toBe('!')
  }
  expect(classifyModel({ category: 'ok' }, 'remote').mark).toBe('OK')
})

test('doctor: mixed results render within 80 columns without colour', () => {
  const text = renderDoctor([{ mark: 'OK', what: 'Plugin active' }, classifyModel({ category: 'http', status: 401 }, 'remote'), { mark: 'LIMIT', what: 'Codex test', cause: 'A window is full.', next: 'Wait for the reset.' }, { mark: '--', what: 'Not checked', next: 'Check status.' }], 80)
  for (const mark of ['[OK]', '[!]', '[LIMIT]', '[--]']) expect(text).toContain(mark)
  expect(text).toContain('2 problems'); expect(text).toContain('docs/TROUBLESHOOTING.md')
  expect(text).not.toContain('\x1b')
  expect(Math.max(...text.split('\n').map(cellWidth))).toBeLessThanOrEqual(80)
})
