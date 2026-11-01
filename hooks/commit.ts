import { atom, read, update } from 'claude-code'
import type { EngineInterface } from 'claude-code'
import type { SetupTail } from '../types'
import { closeSetupPaneNow } from './pane.tsx'

// The write phase of a setup. A write that changes a plugin option reloads this plugin: the module that made the write is
// unloaded (every later `$` call of it fails) unless a hook of it is still running, and then it is unloaded whenever the
// last of those hooks ends. A setup whose pane is open runs after its command hook answered, so it cannot finish what comes
// after its first changing write: the other writes, the restore after a refusal, the follow-up, the text for the person and
// the closing of the pane. The plan is therefore kept in the session's state before the first write, and exactly one module
// carries it out at a time: the one named in the plan's `runner`.
//   - The module that began the setup runs the plan up to the first write that changes an option. Before that write it
//     releases the plan (`runner` unset), because after the write it may be unloaded, and an unloaded module can release
//     nothing. When the write was made, the plan is no longer its: the module loaded by the reload takes it up from its
//     `session.start` (`resumeCommit`; a hook in flight, so it may reload the plugin again), whether or not the module that
//     began the setup is still loaded. When the write was refused nothing was reloaded, and the module takes the plan back.
//   - Every change to the plan is made only while its writer is still the `runner`, so a module that lost the plan cannot
//     write, restore, follow up or report any more.
// Every step is safe to repeat: a write whose option already holds the value is skipped when a plan is carried on.
const TAIL = atom({ plugin: 'model-mod', key: 'setupTail' } as const, null as SetupTail | null, { shape: 'setup-tail-1' })
// A plan that nobody carried out in this time belongs to a session that ended; it is not taken up again.
const STALE_MS = 120_000
// A module that is still loaded after the write it released the plan for waits this long for the reloaded plugin to take the
// plan up. None comes when the write changed nothing the plugin reloads for; the module then takes the plan back.
const TAKE_UP_POLL_MS = 250
const TAKE_UP_POLLS = 24

export type Plan = Pick<SetupTail, 'steps' | 'undo' | 'ok' | 'after'>
// `handed`: the plan is another module's (the module was unloaded by one of its writes, or another module took it up); that
// module reports and closes the pane.
export type Committed = { text: string; ok: boolean; handed?: true }

const HANDED: Committed = { text: '', ok: false, handed: true }
async function row($: EngineInterface, key: string): Promise<unknown> { return (await $.config.list()).find(r => r.key === key)?.value }
// Only this error of a `$` call means the module was replaced; any other one is a failure of the call.
const unloaded = (err: unknown): boolean => /environment is unloaded/.test(String((err as { message?: unknown } | null)?.message ?? ''))
const newRunner = (): string => Math.random().toString(36).slice(2)

// Changes the plan while `me` is its runner. Resolves whether it was: a plan that was taken up by another module,
// replaced by another setup's or already finished is left as it is.
async function mutate($: EngineInterface, me: string, change: (tail: SetupTail) => SetupTail): Promise<boolean> {
  let mine = false
  await update($, TAIL, current => {
    mine = current !== null && current.runner === me
    return current !== null && mine ? change(current) : current
  })
  return mine
}
async function holds($: EngineInterface, me: string): Promise<boolean> { return (await read($, TAIL))?.runner === me }
// Makes `me` the runner of a plan nobody runs. Resolves whether it did.
async function claim($: EngineInterface, me: string): Promise<boolean> {
  let won = false
  await update($, TAIL, current => {
    won = current !== null && current.runner === undefined
    return current !== null && won ? { ...current, runner: me } : current
  })
  return won
}

// The plan was released for a write that changed an option. Resolves true when it is now another module's: the plugin that
// the reload loaded took it up (or it is gone). Resolves false when none came in time and `me` has taken the plan back.
// Every round starts with a call that fails once this module was unloaded; the plan can then only be that plugin's.
async function takenUp($: EngineInterface, me: string, loaded: () => Promise<unknown>): Promise<boolean> {
  for (let i = 0; i < TAKE_UP_POLLS; i++) {
    try {
      await loaded()
      const held = await read($, TAIL)
      if (!held || held.runner !== undefined) return true
    } catch (err) {
      if (unloaded(err)) return true
    }
    await $.clock.sleep(TAKE_UP_POLL_MS)
  }
  return !await claim($, me)
}

// Carries the plan in the state out: the writes in order, else the restore of the earlier writes and of the store and
// environment values, then the follow-up of a success. `me` must be the plan's runner and is checked before every step; a
// plan that is not (any more) its is left alone (`HANDED`). Any `$` call fails when the module was unloaded meanwhile, and the
// caller then leaves the plan for the module that replaced it. `resuming`: a plan another module began. `handoff`: the
// module may be unloaded by a write, so the plan is released before one that changes an option.
async function carryOut($: EngineInterface, me: string, resuming: boolean, handoff: boolean): Promise<Committed> {
  const held = await read($, TAIL)
  if (!held || held.runner !== me) return HANDED
  let tail: SetupTail = held
  const save = () => { const next = tail; return mutate($, me, () => next) }
  // A `$` call that fails means a refused or failed write only while the module is still loaded; this call tells which.
  const loaded = () => $.config.list()
  if (!tail.failure) {
    for (let i = 0; i < tail.steps.length; i++) {
      if (!await holds($, me)) return HANDED
      const step = tail.steps[i]!
      const current = await row($, step.key)
      if (resuming && current === step.value) continue
      const reloads = handoff && current !== step.value
      if (reloads && !await mutate($, me, ({ runner: _, ...plan }) => plan)) return HANDED
      let outcome: 'denied' | 'failed' | undefined
      try { if ('deny' in await $.config.set({ key: step.key, value: step.value })) outcome = 'denied' } catch { outcome = 'failed' }
      if (reloads) {
        // Written: the plugin was reloaded and takes the plan up. Not written: nothing was reloaded, the plan is `me` again.
        if (!outcome) { if (await takenUp($, me, loaded)) return HANDED; continue }
        await loaded()
        if (!await claim($, me)) return HANDED
      }
      if (outcome) {
        await loaded()
        tail = { ...tail, failure: { index: i, kind: outcome, rollbackFailed: false } }
        if (!await save()) return HANDED
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
      if (!await holds($, me)) return HANDED
      const step = tail.steps[i]!
      if (resuming && await row($, step.key) === step.previous) continue
      let refused = false
      try { refused = 'deny' in await $.config.set({ key: step.key, value: step.previous }) } catch { await loaded(); refused = true }
      if (refused) {
        rollbackFailed = true
        tail = { ...tail, failure: { ...failure, rollbackFailed } }
        if (!await save()) return HANDED
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
    // The follow-up is made once: the plan has one runner, and this one still is.
    let note = ''
    if (tail.after) {
      if (!await holds($, me)) return HANDED
      try { if ((await $.process.run(tail.after.argv, { timeoutMs: tail.after.timeoutMs })).exitCode !== 0) note = tail.after.failed } catch { await loaded(); note = tail.after.failed }
    }
    text = tail.ok + note
  }
  if (!await holds($, me)) return HANDED
  return { text, ok: !failure }
}

// Drops the plan of `me`, once its text is out; another module's plan stays.
async function forget($: EngineInterface, me: string): Promise<void> {
  try { await update($, TAIL, current => current?.runner === me ? null : current) } catch { /* a stale plan is dropped by its age */ }
}

// Writes `plan` and reports how it went. `handoff`: the module may be unloaded by a write (its command hook has answered),
// so the reloaded plugin may take the plan up (`resumeCommit`); else this module is the only one that carries it out.
export async function commitSettings($: EngineInterface, plan: Plan, handoff: boolean): Promise<Committed> {
  const me = handoff ? newRunner() : 'inline'
  try {
    const at = await $.clock.now()
    await update($, TAIL, () => ({ ...plan, at, runner: me }))
    const done = await carryOut($, me, false, handoff)
    if (!done.handed) await forget($, me)
    return done
  } catch (err) {
    // Only an unload hands the rest to the plugin that replaced this module; a failure of a `$` call while it is loaded ends here.
    if (handoff && unloaded(err)) return HANDED
    await forget($, me)
    return { text: 'model-mod: setup could not complete; check the settings in /plugin.', ok: false }
  }
}

// `session.start` of a plugin that was reloaded while a setup was writing: carries the plan on, then reports it and closes
// the setup pane (the module that began it can no longer do either). `report` shapes the text for the transcript.
export async function resumeCommit($: EngineInterface, report: (text: string) => string): Promise<void> {
  try {
    const held = await read($, TAIL)
    if (!held || held.runner !== undefined || await $.clock.now() - held.at > STALE_MS) return
    const me = newRunner()
    if (!await claim($, me)) return
    let text = 'model-mod: setup did not complete; check the settings in /plugin.'
    try {
      const done = await carryOut($, me, true, false)
      // The plan is another module's now: that module reports it and closes the pane.
      if (done.handed) return
      text = done.text || text
    } catch { /* the settings stay as they are; the text says to check them */ }
    void Promise.resolve($.ui.log(report(text))).catch(() => {})
    await closeSetupPaneNow($)
    await forget($, me)
  } catch { /* nothing to carry on */ }
}
