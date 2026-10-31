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

async function close($: EngineInterface, id: string = PANE): Promise<void> {
  try { await $.ui.close({ id }) } catch { /* already gone */ }
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

// The setup menus: one question and a short list of fixed answers, no free input. Esc closes the pane and counts as no answer.
// The list is not scrolled: a menu that does not fit the body is handed back, and the caller asks with the paged dialog.
const CHOICE = 'model-mod-setup'
// `current` gets a check mark; `initial` is the row focused first (the first one when absent).
export type Choice = { title: string; question: string; options: readonly string[]; current?: string; initial?: string }
export type ChoiceResult = { picked: string } | 'closed' | 'fallback'
type PendingChoice = Choice & { settle: (result: ChoiceResult) => void }
let pending: PendingChoice | undefined

// Opens the menu and returns at once with whether the pane was seated. `settle` is called once, later, with the pick, with
// 'closed' (Esc or another close) or with 'fallback' (seated, but the body turned out too small). A pane that is not seated
// calls nothing: the caller goes on with the dialog.
export async function openChoice($: EngineInterface, choice: Choice, settle: (result: ChoiceResult) => void): Promise<'shown' | 'fallback'> {
  if (pending) return 'fallback'
  let done = false
  const once = (result: ChoiceResult) => { if (!done) { done = true; if (pending === mine) pending = undefined; settle(result) } }
  const mine: PendingChoice = { ...choice, settle: once }
  pending = mine
  try {
    const opened = await $.ui.open({ id: CHOICE, title: choice.title, focus: true, closeOnEscape: true, holdToasts: true, rows: Math.min(20, choice.options.length + 4) })
    if (opened.isPlaced) return 'shown'
  } catch { /* fall back below */ }
  if (pending === mine) pending = undefined
  done = true
  await close($, CHOICE)
  return 'fallback'
}

// The answer of one menu. `onShown` is called once the pane is seated: a command hook that is still waiting for the flow
// must answer then, because it may not wait for a person (its own time is capped at 10 s).
export async function chooseInPane($: EngineInterface, choice: Choice, onShown?: () => void): Promise<ChoiceResult> {
  return new Promise<ChoiceResult>(resolve => {
    void openChoice($, choice, resolve).then(seat => { if (seat === 'shown') onShown?.(); else resolve('fallback') })
  })
}

export function registerPane(on: Parameters<Register>[0]): void {
  on('ui.close', { id: PANE }, async ($, e, next) => {
    open = undefined
    return next(e)
  })

  on('ui.close', { id: CHOICE }, async ($, e, next) => {
    pending?.settle('closed')
    return next(e)
  })

  on('ui.render', { component: 'Pane', requestId: CHOICE }, async ($, e, next) => {
    const current = pending
    if (!current) return next(e)
    const bodyRows = e.props.scroll?.bodyRows ?? 12
    const columns = Math.max(20, e.props.bodyColumns ?? 76)
    // One row for the hint, the wrapped question, and every answer.
    const questionRows = Math.ceil([...current.question].length / columns)
    if (current.options.length + questionRows + 1 > bodyRows) {
      pending = undefined
      $.clock.after(0, () => { later(async () => { await close($, CHOICE); current.settle('fallback') }) })
      return next(e)
    }
    const { Box, Text, Button } = $.ui.resolve(e)
    const focused = e.props.isFocused === true
    return <Box flexDirection="column">
      <Text>{current.question}</Text>
      {focused
        ? <Text dimColor>↑↓ move · Enter select · Esc close</Text>
        : <Text color="yellow">Keyboard not captured: press Ctrl+X, then Tab</Text>}
      {current.options.map(label => <Button key={'c:' + label} plain autoFocus={label === (current.initial ?? current.options[0]) ? true : undefined}
        onPress={() => {
          pending = undefined
          later(async () => {
            await close($, CHOICE)
            current.settle({ picked: label })
          })
        }}>
        {(label === current.current ? '✓ ' : '  ') + label}
      </Button>)}
    </Box>
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
