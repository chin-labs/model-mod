import { test, expect } from 'claude-code/testing'
import { htmlToText } from './text.ts'

test('htmlToText keeps visible text, drops scripts and styles, decodes references', () => {
  const html = '<!doctype html><html><head><title>T</title><style>p{color:red}</style>' +
    '<script>if (a<b) { document.write("x") }</script></head><body><h1>Head &amp; tail</h1>' +
    '<p>one &#39;two&#x27; <b>three</b></p><noscript>no js</noscript><svg><text>glyph</text></svg>' +
    '<ul><li>a</li><li>b</li></ul><!-- hidden --><pre>x\n  y</pre><p>&nbsp;caf&eacute;&bogus;</p></body></html>'
  expect(htmlToText(html)).toBe("T\nHead & tail\none 'two' three\na\nb\nx\ny\ncafé&bogus;")
})

test('htmlToText passes plain text through and cuts at the limit', () => {
  expect(htmlToText('  just   some\n\n\ntext  ')).toBe('just some\ntext')
  expect(htmlToText('<p>' + 'a'.repeat(100) + '</p>', 10)).toBe('a'.repeat(10))
})

test('htmlToText is linear on hostile input and ends a script only at its own close tag', () => {
  const started = Date.now()
  expect(htmlToText('<' + 'a'.repeat(300_000))).toBe('')
  expect(htmlToText('<p>x</p>' + '<script>a</script>'.repeat(60_000))).toBe('x')
  expect(Date.now() - started).toBeLessThan(2000)
  expect(htmlToText('<script>const s="</scriptx>";SECRET()</script><p>visible</p><style>a{}</stylesheet>b{}</style>ok'))
    .toBe('visibleok')
  expect(htmlToText('<script/>HIDDEN()</script>seen')).toBe('seen')
  expect(htmlToText('<script>HIDDEN</script_>LEAK</script>seen')).toBe('seen')
  expect(htmlToText('<style>x</style=bad>LEAK</style>seen')).toBe('seen')
  expect(htmlToText('<script>HIDDEN</script >seen')).toBe('seen')
})
