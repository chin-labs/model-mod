// Values the mod keeps in the host's session state instead of module variables, so that a hot reload of the plugin
// (saving a file while a session loads it with --plugin-dir) does not lose them.

// What `applyWindow` knows about the two environment variables it overrides while a bridge model is selected.
// A missing key means "not read / not applied yet"; `null` means the variable was unset.
export type EnvMemo = {
  originalWindow?: string | null
  appliedWindow?: string | null
  originalSide?: string | null
  appliedSide?: string | null
}

// The model a rate-limit fallback switched away from, the one it switched to and when the limit resets (ms).
// `suppressUntil`: the person chose a model by hand after a switch; no automatic switch until that window resets.
// Empty: no switch of this mod is in effect.
export type FallbackMemo = { from?: string; to?: string; until?: number; suppressUntil?: number }

// The first row of the picker pane's scrolling window.
export type PickerState = { offset: number }

export type TrackedBlock = { type: string; [key: string]: unknown }
export type TrackedTurn = { role: 'user' | 'assistant'; content: TrackedBlock[] }
// The conversation of a workflow agent that runs on a bridge model (`$.session.messages` cannot read it).
export type TrackedAgent = {
  turns: TrackedTurn[]
  pending: string[]
  results: Record<string, { text: string; isError: boolean }>
}

declare module 'claude-code' {
  interface PluginState {
    'model-mod': {
      env: EnvMemo
      fallback: FallbackMemo
      // Model of every agent loop seen in turn.step, by agent id.
      agentModel: StateFamily<string>
      tracked: StateFamily<TrackedAgent>
      picker: PickerState
    }
  }
}
