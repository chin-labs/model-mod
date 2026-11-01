import { atom, read, update } from 'claude-code'
import type { EngineInterface } from 'claude-code'
import type { SetupTail } from '../types'
import { closeSetupPaneNow } from './pane.tsx'

// The write phase of a setup. A write that changes a plugin option reloads this plugin: the module that made the write is
// unloaded (every later `$` call of it fails) unless a hook of it is still running. A setup whose pane is open runs after
// its command hook answered, so it cannot finish what comes after its first changing write: the writes, the restore after a
// refusal, the text for the person and the closing of the pane. The plan is therefore kept in the session's state before
// the first write; the module that made it carries it out as far as it can, and the module loaded by the reload carries on
// from its `session.start` (a hook in flight, so it may reload the plugin again). Every step is safe to repeat: a write
// whose option already holds the value is skipped when a plan is carried on.
const TAIL = atom({ plugin: 'model-mod', key: 'setupTail' } as const, null as SetupTail | null, { shape: 'setup-tail-1' })
// A plan that nobody carried out in this time belongs to a session that ended; it is not taken up again.
const STALE_MS = 120_000

export type Plan = Pick<SetupTail, 'steps' | 'undo' | 'ok' | 'after'>
// `handed`: the module was unloaded by one of its writes; the reloaded plugin reports and closes the pane.
export type Committed = { text: string; ok: boolean; handed?: true }

const HANDED: Committed = { text: '', ok: false, handed: true }
async function row($: EngineInterface, key: string): Promise<unknown> { return (await $.config.list()).find(r => r.key === key)?.value }

// Carries the plan in the state out: the writes in order, else the restore of the earlier writes and of the store and
// environment values, then the follow-up of a success. Any `$` call fails when the module was unloaded meanwhile, and the
// caller then leaves the plan for the module that replaced it. `resuming`: a plan another module began.
async function carryOut($: EngineInterface, resuming: boolean): Promise<Committed> {
  const held = await read($, TAIL)
  if (!held) return HANDED
  let tail: SetupTail = held
  const save = async () => { const next = tail; await update($, TAIL, () => next) }
  // A `$` call that fails means a refused or failed write only while the module is still loaded; this call tells which.
  const loaded = () => $.config.list()
  if (!tail.failure) {
    for (let i = 0; i < tail.steps.length; i++) {
      const step = tail.steps[i]!
      const current = await row($, step.key)
      if (resuming && current === step.value) continue
      let outcome: 'denied' | 'failed' | undefined
      try { if ('deny' in await $.config.set({ key: step.key, value: step.value })) outcome = 'denied' } catch { outcome = 'failed' }
      if (outcome) {
        await loaded()
        tail = { ...tail, failure: { index: i, kind: outcome, rollbackFailed: false } }
        await save()
        break
      }
    }
    await loaded()
  }
  const failure = tail.failure
  let text: string
  if (failure) {
    let rollbackFailed = failure.rollbackFailed
    // A write that threw may have been made; one that was refused was not.
    for (let i = (failure.kind === 'failed' ? failure.index + 1 : failure.index) - 1; i >= 0; i--) {
      const step = tail.steps[i]!
      if (resuming && await row($, step.key) === step.previous) continue
      let refused = false
      try { refused = 'deny' in await $.config.set({ key: step.key, value: step.previous }) } catch { await loaded(); refused = true }
      if (refused) {
        rollbackFailed = true
        tail = { ...tail, failure: { ...failure, rollbackFailed } }
        await save()
      }
    }
    await loaded()
    try {
      for (const [key, value] of Object.entries(tail.undo?.store ?? {})) await $.store.set(key, value)
      const custom = tail.undo?.customModelOption
      if (custom !== undefined && (await $.env.set('ANTHROPIC_CUSTOM_MODEL_OPTION', custom))?.deny) throw new Error('environment restore refused')
    } catch { await loaded(); rollbackFailed = true }
    const step = tail.steps[failure.index]!
    text = rollbackFailed ? step.rollbackFailed : failure.kind === 'denied' ? step.denied : step.failed
  } else {
    let note = ''
    if (tail.after) {
      try { if ((await $.process.run(tail.after.argv, { timeoutMs: tail.after.timeoutMs })).exitCode !== 0) note = tail.after.failed } catch { await loaded(); note = tail.after.failed }
    }
    text = tail.ok + note
  }
  return { text, ok: !failure }
}

async function forget($: EngineInterface): Promise<void> { try { await update($, TAIL, () => null) } catch { /* a stale plan is dropped by its age */ } }

// Writes `plan` and reports how it went. `handoff`: the module may be unloaded by a write (its command hook has answered),
// so the reloaded plugin may take the plan up (`resumeCommit`); else this module is the only one that carries it out.
export async function commitSettings($: EngineInterface, plan: Plan, handoff: boolean): Promise<Committed> {
  try {
    const at = await $.clock.now()
    await update($, TAIL, () => ({ ...plan, at, ...(handoff ? {} : { runner: 'inline' }) }))
    const done = await carryOut($, false)
    if (!done.handed) await forget($)
    return done
  } catch {
    // The module was unloaded by a write: whatever is left is the reloaded plugin's.
    if (handoff) return HANDED
    await forget($)
    return { text: 'model-mod: setup could not complete; check the settings in /plugin.', ok: false }
  }
}

// `session.start` of a plugin that was reloaded while a setup was writing: carries the plan on, then reports it and closes
// the setup pane (the module that began it can no longer do either). `report` shapes the text for the transcript.
export async function resumeCommit($: EngineInterface, report: (text: string) => string): Promise<void> {
  try {
    const held = await read($, TAIL)
    if (!held || held.runner !== undefined || await $.clock.now() - held.at > STALE_MS) return
    const me = Math.random().toString(36).slice(2)
    let won = false
    await update($, TAIL, current => {
      won = current !== null && current.runner === undefined
      return current !== null && won ? { ...current, runner: me } : current
    })
    if (!won) return
    let text = 'model-mod: setup did not complete; check the settings in /plugin.'
    try { text = (await carryOut($, true)).text || text } catch { /* the settings stay as they are; the text says to check them */ }
    void Promise.resolve($.ui.log(report(text))).catch(() => {})
    await closeSetupPaneNow($)
    await forget($)
  } catch { /* nothing to carry on */ }
}
