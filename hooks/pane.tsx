import type { EngineInterface, Register } from 'claude-code'
import type { PickerState } from '../types'

// The /model-mod:model picker pane: the local models in one scrolling list. Official models stay with the client's own /model.
// The arrow keys move between rows, Enter picks and Esc closes.
const PANE = 'model-mod-picker'
const REF = { plugin: 'model-mod', key: 'picker' } as const
// The smallest body that holds the hint row, one model and the two "more" rows.
const MIN_BODY_ROWS = 5

export type PaneHandlers = {
  pick: (id: string) => Promise<void>
  // The pane turned out too small once drawn; the caller asks with the paged menu instead.
  fallback: () => Promise<void>
}

// Short neutral descriptions written for this plugin, not taken from any provider's catalog.
// A model without one shows only its ID.
const DESCRIPTIONS: Record<string, string> = {
  'gpt-6-sol': 'General-purpose model.',
  'gpt-6-luna': 'Quick, lower-cost option.',
  'gpt-5.6-sol': 'Legacy general-purpose model.',
  'gpt-5.6-terra': 'Legacy balanced option.',
  'gpt-5.6-luna': 'Legacy lightweight option.',
}

function describe(id: string): string | undefined {
  return DESCRIPTIONS[id]
}

type Open = {
  local: readonly string[]
  current: string
  handlers: PaneHandlers
}
let open: Open | undefined
// Rows the window shows; the render writes it and the focus hook reads it.
let windowSize = 6

async function close($: EngineInterface): Promise<void> {
  try { await $.ui.close({ id: PANE }) } catch { /* already gone */ }
}

function later(task: () => Promise<void>): void {
  void task().catch(() => {})
}

// Opens the pane and returns at once: the person's choice reaches the handlers, which run after the command hook ended
// (a hook's own time is capped at 10 s, a person may take longer). Resolves 'fallback' when the pane cannot be seated.
export async function openPane($: EngineInterface, input: { local: readonly string[]; current: string },
  handlers: PaneHandlers): Promise<'shown' | 'fallback'> {
  open = undefined
  try {
    await $.state.set(REF, { offset: 0 })
    open = { ...input, handlers }
    const opened = await $.ui.open({ id: PANE, title: 'Select model', focus: true, closeOnEscape: true, holdToasts: true, rows: 20 })
    if (opened.isPlaced) return 'shown'
  } catch { /* fall back below */ }
  open = undefined
  await close($)
  return 'fallback'
}

export function registerPane(on: Parameters<Register>[0]): void {
  on('ui.close', { id: PANE }, async ($, e, next) => {
    open = undefined
    return next(e)
  })

  // Focus reaching a "more" row scrolls the window and moves focus to the row that came into view.
  on('ui.focus', { requestId: PANE }, async ($, e, next) => {
    const { value } = await $.state.get(REF)
    if (!open || !value || (e.element !== 'more-down' && e.element !== 'more-up')) return next(e)
    const ids = [...open.local]
    const down = e.element === 'more-down'
    const offset = Math.max(0, Math.min(ids.length - windowSize, value.offset + (down ? 1 : -1)))
    await $.state.set(REF, { ...value, offset })
    const target = down ? ids[Math.min(ids.length - 1, offset + windowSize - 1)] : ids[offset]
    if (target !== undefined) $.clock.after(30, () => { void $.ui.focus({ requestId: PANE, key: 'm:' + target }).catch(() => {}) })
    return { deny: 'window scrolled' }
  })

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e, next) => {
    const current = open
    if (!current) return next(e)
    const bodyRows = e.props.scroll?.bodyRows ?? 12
    if (bodyRows < MIN_BODY_ROWS) {
      open = undefined
      $.clock.after(0, () => { later(async () => { await close($); await current.handlers.fallback() }) })
      return next(e)
    }
    const { Box, Text, Button } = $.ui.resolve(e)
    const { value = { offset: 0 } as PickerState } = await $.state.get(REF)
    const ids = [...current.local]
    const focused = e.props.isFocused === true
    // The drawing must fit inside bodyRows: on overflow the arrow keys scroll the pane instead of moving focus.
    const listRows = bodyRows - 1
    windowSize = ids.length <= listRows ? ids.length : Math.max(1, listRows - 2)
    const offset = Math.max(0, Math.min(ids.length - windowSize, value.offset))
    const shown = ids.slice(offset, offset + windowSize)
    return <Box flexDirection="column">
      {focused
        ? <Text dimColor>↑↓ move · Enter select · Esc close</Text>
        : <Text color="yellow">Keyboard not captured: press Ctrl+X, then Tab</Text>}
      {offset > 0 ? <Button key="more-up" label={'▲ ' + offset + ' more'} plain dimColor onPress={() => {}} /> : null}
      {shown.map((id, i) => {
        const text = describe(id)
        return <Button key={'m:' + id} plain autoFocus={i === 0 && offset === 0 ? true : undefined}
          onPress={() => {
            open = undefined
            later(async () => {
              await close($)
              await current.handlers.pick(id)
            })
          }}>
          {(id === current.current ? '✓ ' : '  ') + id}{text ? <Text dimColor>{'  ' + text}</Text> : null}
        </Button>
      })}
      {offset + windowSize < ids.length
        ? <Button key="more-down" label={'▼ ' + (ids.length - offset - windowSize) + ' more'} plain dimColor onPress={() => {}} />
        : null}
    </Box>
  })
}
