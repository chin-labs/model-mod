import { test, expect } from 'claude-code/testing'
import { formatOutput, parseDelegate } from './delegate.ts'

test('delegate parser handles quotes, separator, repeats and unknown flags', () => {
  expect(parseDelegate('review', `--base 'feature/test' --adversarial -- "focus text" 'and more'`)).toEqual({ base: 'feature/test', adversarial: true, text: 'focus text and more' })
  expect(parseDelegate('rescue', `--model "gpt test" -- --account literal`)).toEqual({ model: 'gpt test', text: '--account literal' })
  expect(() => parseDelegate('review', '--base a --base b')).toThrow()
  expect(() => parseDelegate('review', '--unknown')).toThrow()
  expect(() => parseDelegate('rescue', `-- 'unterminated`)).toThrow()
})

test('delegate output has a warning and strips terminal controls', () => {
  const text = formatOutput('test', 'chat', '\x1b[31mhello\x1b[0m\x01')
  expect(text).toContain('no file writes; read-only commands may still run')
  expect(text).toContain('Codex output is unverified')
  expect(text).not.toContain('\x1b')
  expect(text).not.toContain('\x01')
})
