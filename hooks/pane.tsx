import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'
import type { PickerState, SetupMenu } from '../types'

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

// The setup menus: one question and a short list of fixed answers, no free input. One pane stays open for the whole
// setup and shows each menu in turn ("Working…" between them): a pane opened from the command the person typed is seated
// at any width, one opened later from the flow is not, so the flow opens it once. Esc closes it and counts as no answer.
// A menu that does not fit the body is handed back and the caller asks with the paged dialog.
const CHOICE = 'model-mod-setup'
const MENU = atom({ plugin: 'model-mod', key: 'setupMenu' } as const, { busy: true } as SetupMenu, { shape: 'setup-menu-1' })
const BUSY: SetupMenu = { busy: true }
export type Choice = { question: string; options: readonly string[]; current?: string; initial?: string }
export type ChoiceResult = { picked: string } | 'closed' | 'fallback'
let awaiting: ((result: ChoiceResult) => void) | undefined
let seated = false
// Set when something other than this plugin's own flow closes the setup pane (Esc, the close mark, an unload): the setup
// that was running ends at its next question or write, even if the pane showed "Working…" and no menu was waiting.
let closedFromOutside = false
// True while the flow itself closes the pane (before a dialog, or when it is over): that close is no cancel.
let closing = false

// A new setup starts with a pane nobody has closed yet.
export function beginSetupPane(): void { closedFromOutside = false }
// True once the running setup's pane was closed from outside; the setup then asks nothing more and writes nothing. The
// close hook says so at once; the engine's list of open panes covers a close that raised no hook (an unload, a drawing that
// threw), and answers for it when the list can be read.
export async function setupPaneClosed($: EngineInterface): Promise<boolean> {
  if (closedFromOutside) return true
  if (!seated) return false
  try { if ((await $.ui.panes()).some(pane => pane.id === CHOICE)) return false } catch { return false }
  closedFromOutside = true
  seated = false
  return true
}

async function closeSetupPane($: EngineInterface): Promise<void> {
  closing = true
  try { await close($, CHOICE) } finally { closing = false }
}

// Closes the setup pane from a module that did not open it: the one a reload put in place of the setup that was writing.
export async function closeSetupPaneNow($: EngineInterface): Promise<void> {
  seated = false
  await closeSetupPane($)
}

// The setup pane is gone: Esc, the close mark, an unload, another plugin's close, or this flow's own close. A menu it showed
// is answered 'closed'; a close the flow did not make itself also marks the running setup as cancelled.
function setupPaneGone(): void {
  seated = false
  if (!closing) closedFromOutside = true
  const waiting = awaiting
  awaiting = undefined
  waiting?.('closed')
}

// Closes the pane before a dialog, or when the setup is over. A menu still waiting is answered 'closed', the same as Esc:
// its setup ends as cancelled instead of waiting for an answer that can no longer come.
export async function dismissSetupPane($: EngineInterface): Promise<void> {
  const waiting = awaiting
  awaiting = undefined
  waiting?.('closed')
  if (!seated) return
  seated = false
  await closeSetupPane($)
}

// Shows one menu, opening the pane for it when it is not open yet (`onSeated` is called then, once the surface seats it).
// Resolves with the row pressed, 'closed' (Esc) or 'fallback' (no surface seats the pane, or the list has no room).
export function menuInPane($: EngineInterface, choice: Choice, onSeated: () => void): Promise<ChoiceResult> {
  return new Promise<ChoiceResult>(resolve => {
    if (awaiting) return resolve('fallback')
    awaiting = resolve
    void (async () => {
      try {
        // The menu is in place before the pane is drawn, so its first row takes the focus when it opens.
        await update($, MENU, () => ({ ...choice, options: [...choice.options] }))
        if (!seated) {
          const opened = await $.ui.open({ id: CHOICE, title: 'model-mod setup', focus: true, closeOnEscape: true, holdToasts: true, rows: 16 })
          if (!opened.isPlaced) {
            if (awaiting === resolve) awaiting = undefined
            await closeSetupPane($)
            return resolve('fallback')
          }
          // The menu was dropped while the pane was opening (a dialog took the keyboard, or the person closed it): the
          // answer is already given, so the pane that just opened is closed again instead of being left empty.
          if (awaiting !== resolve) return void await closeSetupPane($)
          seated = true
          onSeated()
        } else {
          // Rows drawn after the pane opened do not take the focus by themselves.
          const key = 'c:' + (choice.initial ?? choice.options[0])
          $.clock.after(40, () => { void $.ui.focus({ requestId: CHOICE, key }).catch(() => {}) })
        }
      } catch {
        if (awaiting === resolve) awaiting = undefined
        resolve('fallback')
      }
    })()
  })
}

export function registerPane(on: Parameters<Register>[0]): void {
  on('ui.close', { id: PANE }, async ($, e, next) => {
    open = undefined
    return next(e)
  })

  on('ui.close', { id: CHOICE }, async ($, e, next) => {
    setupPaneGone()
    return next(e)
  })

  on('ui.render', { component: 'Pane', requestId: CHOICE }, async ($, e, next) => {
    const { Box, Text, Button } = $.ui.resolve(e)
    const state = await read($, MENU)
    if ('busy' in state) return <Box><Text dimColor>Working…</Text></Box>
    const bodyRows = e.props.scroll?.bodyRows ?? 12
    const columns = Math.max(20, e.props.bodyColumns ?? 76)
    // The question (wrapped), the hint row and every answer.
    if (state.options.length + Math.ceil([...state.question].length / columns) + 1 > bodyRows) {
      const waiting = awaiting
      awaiting = undefined
      $.clock.after(0, () => { if (waiting) waiting('fallback') })
      return <Box><Text dimColor>Working…</Text></Box>
    }
    const focused = e.props.isFocused === true
    return <Box flexDirection="column">
      <Text>{state.question}</Text>
      {focused
        ? <Text dimColor>↑↓ move · Enter select · Esc close</Text>
        : <Text color="yellow">Keyboard not captured: press Ctrl+X, then Tab</Text>}
      {state.options.map(label => <Button key={'c:' + label} plain autoFocus={label === (state.initial ?? state.options[0]) ? true : undefined}
        onPress={() => {
          const waiting = awaiting
          if (!waiting) return
          awaiting = undefined
          later(async () => {
            await update($, MENU, () => BUSY)
            waiting({ picked: label })
          })
        }}>
        {(label === state.current ? '✓ ' : '  ') + label}
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
