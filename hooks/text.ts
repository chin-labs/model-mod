// HTML (or any text) to plain text for the web_fetch tool. Scripts, styles, noscript and svg are dropped, block tags
// become line breaks, character references are decoded, whitespace is collapsed and the result is cut at `limit`
// characters. One forward pass over the input: every position is looked at a bounded number of times (no
// backtracking pattern, no rescans of the whole text).
const SKIPPED = new Set(['script', 'style', 'noscript', 'svg'])
// Raw-text elements: their content is not markup, so it is skipped up to the matching close tag. Like the HTML
// parser, a `/` before the `>` does not make them empty.
const RAW_TEXT = new Set(['script', 'style'])
const BLOCKS = new Set(['p', 'br', 'div', 'li', 'tr', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'pre'])
const NAMED: Record<string, string> = {
  amp: '&', lt: '<', gt: '>', quot: '"', apos: "'", hellip: '…', mdash: '—', ndash: '–', lsquo: '‘', rsquo: '’',
  ldquo: '“', rdquo: '”', bull: '•', trade: '™', euro: '€', larr: '←', rarr: '→', uarr: '↑', darr: '↓',
}
// The Latin-1 names, in code point order from U+00A0.
const LATIN1 = ('nbsp iexcl cent pound curren yen brvbar sect uml copy ordf laquo not shy reg macr deg plusmn sup2 sup3 ' +
  'acute micro para middot cedil sup1 ordm raquo frac14 frac12 frac34 iquest Agrave Aacute Acirc Atilde Auml Aring ' +
  'AElig Ccedil Egrave Eacute Ecirc Euml Igrave Iacute Icirc Iuml ETH Ntilde Ograve Oacute Ocirc Otilde Ouml times ' +
  'Oslash Ugrave Uacute Ucirc Uuml Yacute THORN szlig agrave aacute acirc atilde auml aring aelig ccedil egrave ' +
  'eacute ecirc euml igrave iacute icirc iuml eth ntilde ograve oacute ocirc otilde ouml divide oslash ugrave uacute ' +
  'ucirc uuml yacute thorn yuml').split(' ')
LATIN1.forEach((name, i) => { NAMED[name] = String.fromCharCode(0xa0 + i) })
const LEGACY = new Set([...LATIN1, 'amp', 'lt', 'gt', 'quot'])  // also valid without the closing semicolon

function decode(text: string): string {
  if (!text.includes('&')) return text
  return text.replace(/&(?:#(\d{1,7});?|#[xX]([0-9a-fA-F]{1,6});?|([A-Za-z][A-Za-z0-9]{1,8})(;|(?![A-Za-z0-9])))/g,
    (whole, dec, hex, name, semicolon) => {
      if (name !== undefined) return semicolon === ';' || LEGACY.has(name) ? NAMED[name] ?? whole : whole
      const code = dec !== undefined ? Number(dec) : parseInt(hex, 16)
      return code > 0 && code <= 0x10ffff && !(code >= 0xd800 && code <= 0xdfff) ? String.fromCodePoint(code) : whole
    })
}

const isLetter = (c: string | undefined) => c !== undefined && /[A-Za-z]/.test(c)
const isNameChar = (c: string | undefined) => c !== undefined && /[A-Za-z0-9:-]/.test(c)

export function htmlToText(input: string, limit = 60_000): string {
  let raw = input
  if (raw.slice(0, 2000).includes('<')) {
    const out: string[] = []
    const n = raw.length
    let skip = 0
    let i = 0
    while (i < n) {
      const lt = raw.indexOf('<', i)
      if (lt < 0) { if (!skip) out.push(decode(raw.slice(i))); break }
      if (lt > i && !skip) out.push(decode(raw.slice(i, lt)))
      i = lt
      if (raw.startsWith('<!--', i)) {
        const end = raw.indexOf('-->', i + 4)
        i = end < 0 ? n : end + 3
        continue
      }
      const c1 = raw[i + 1]
      if (raw.startsWith('<![CDATA[', i) || c1 === '!' || c1 === '?') {
        const end = raw.indexOf(raw.startsWith('<![CDATA[', i) ? ']]>' : '>', i)
        i = end < 0 ? n : end + (raw.startsWith('<![CDATA[', i) ? 3 : 1)
        continue
      }
      const closing = c1 === '/'
      if (!isLetter(closing ? raw[i + 2] : c1)) {
        if (!skip) out.push('<')  // a lone `<` is text
        i++
        continue
      }
      let j = i + (closing ? 2 : 1)
      const nameStart = j
      while (isNameChar(raw[j])) j++
      const name = raw.slice(nameStart, j).toLowerCase()
      // Attributes up to the closing `>`, quoted values may hold one; markup that never ends swallows the rest.
      let end = -1
      while (j < n) {
        const c = raw[j]
        if (c === '>') { end = j; break }
        if (c === '"' || c === "'") {
          const close = raw.indexOf(c, j + 1)
          if (close < 0) break
          j = close + 1
        } else j++
      }
      if (end < 0) break
      const selfClosing = raw[end - 1] === '/'
      i = end + 1
      if (!closing && RAW_TEXT.has(name)) {
        const closer = new RegExp(`</${name}(?=[\\s/>]|$)`, 'gi')
        closer.lastIndex = i
        const hit = closer.exec(raw)
        if (!hit) break
        const close = raw.indexOf('>', hit.index)
        i = close < 0 ? n : close + 1
        continue
      }
      if (SKIPPED.has(name) && !(selfClosing && !closing)) skip = closing ? Math.max(0, skip - 1) : skip + 1
      else if (!closing && BLOCKS.has(name)) out.push('\n')
    }
    raw = out.join('')
  }
  const lines = raw.split('\n').map(line => line.split(/\s+/).filter(Boolean).join(' '))
  return lines.filter(Boolean).join('\n').slice(0, limit)
}
