import type { TurnStepChunk, TurnStepInput, TurnStepResult, TurnUsage } from 'claude-code'

/** Incremental Messages SSE decoder; keeps only an unfinished event and tool inputs. */
export class MessagesStream {
  private buffer = ''
  private tools = new Map<number, { id: string; name: string; json: string; input: unknown }>()
  private reasoning = new Map<number, { thinking: string; signature: string }>()
  answer = ''
  complete = false
  error: { type: unknown } | undefined
  nextIndex = 0
  stopReason: TurnStepResult['stopReason'] = 'end_turn'
  usage: TurnUsage

  constructor(model: string) {
    this.usage = { model, input_tokens: 0, output_tokens: 0,
      cache_read_input_tokens: 0, cache_creation_input_tokens: 0 }
  }

  push(piece: string): TurnStepChunk[] {
    if (this.error) return []
    this.buffer += piece
    const chunks: TurnStepChunk[] = []
    for (;;) {
      const boundary = /\r?\n\r?\n/.exec(this.buffer)
      if (!boundary) break
      const frame = this.buffer.slice(0, boundary.index)
      this.buffer = this.buffer.slice(boundary.index + boundary[0].length)
      const lines = frame.split(/\r?\n/)
      const event = lines.find(line => line.startsWith('event:'))?.slice(6).trim()
      if (!event || !['message_start', 'content_block_start', 'content_block_delta',
        'content_block_stop', 'message_delta', 'message_stop', 'error'].includes(event)) continue
      const data = lines.filter(line => line.startsWith('data:')).map(line => line.slice(5).trimStart()).join('\n')
      const value = JSON.parse(data)
      if (event === 'error') {
        this.error = { type: value.error?.type }
        this.buffer = ''
        break
      }
      if (event === 'message_start') this.addUsage(value.message?.usage)
      if (event === 'message_delta') {
        this.addUsage(value.usage)
        const reason = value.delta?.stop_reason
        if (['end_turn', 'max_tokens', 'stop_sequence', 'tool_use', 'pause_turn',
          'compaction', 'refusal', 'model_context_window_exceeded'].includes(reason)) this.stopReason = reason
      }
      const index: number = value.index ?? 0
      if (event.startsWith('content_block_')) this.nextIndex = Math.max(this.nextIndex, index + 1)
      if (event === 'content_block_start') {
        const block = value.content_block
        if (block?.type === 'thinking') {
          this.reasoning.set(index, { thinking: '', signature: typeof block.signature === 'string' ? block.signature : '' })
        } else if (block?.type === 'tool_use') {
          this.tools.set(index, { id: block.id, name: block.name, json: '', input: block.input ?? {} })
          chunks.push({ kind: 'tool', index, id: block.id, name: block.name })
        } else if (block?.type === 'text' && block.text) {
          this.answer += block.text
          chunks.push({ kind: 'text', index, text: block.text })
        }
      }
      if (event === 'content_block_delta') {
        const delta = value.delta
        if (delta?.type === 'text_delta') {
          this.answer += delta.text
          chunks.push({ kind: 'text', index, text: delta.text })
        } else if (delta?.type === 'signature_delta' && this.reasoning.has(index) && typeof delta.signature === 'string') {
          this.reasoning.get(index)!.signature += delta.signature
        } else if (delta?.type === 'thinking_delta' && this.reasoning.has(index) && typeof delta.thinking === 'string') {
          this.reasoning.get(index)!.thinking += delta.thinking
        } else if (delta?.type === 'input_json_delta' && this.tools.has(index)) {
          this.tools.get(index)!.json += delta.partial_json
          chunks.push({ kind: 'input', index, json: delta.partial_json })
        }
      }
      if (event === 'content_block_stop') {
        const tool = this.tools.get(index)
        if (tool) {
          if (tool.json) tool.input = JSON.parse(tool.json)
          else chunks.push({ kind: 'input', index, json: JSON.stringify(tool.input) })
        }
      }
      if (event === 'message_stop') {
        this.complete = true
        // Validate all inputs before emitting the final stop.
        for (const tool of this.tools.values()) if (tool.json) tool.input = JSON.parse(tool.json)
        chunks.push({ kind: 'stop', stopReason: this.stopReason, usage: { ...this.usage } })
      }
    }
    return chunks
  }

  private addUsage(value: Record<string, unknown> | undefined) {
    if (!value) return
    for (const key of ['input_tokens', 'output_tokens', 'cache_read_input_tokens',
      'cache_creation_input_tokens'] as const) {
      if (typeof value[key] === 'number') this.usage[key] = value[key]
    }
  }

  /** The signed thinking blocks of this response (what the model must be given back inside a tool loop). */
  thinkingBlocks(): { type: 'thinking'; thinking: string; signature: string }[] {
    return [...this.reasoning.values()].filter(r => r.signature)
      .map(r => ({ type: 'thinking' as const, thinking: r.thinking, signature: r.signature }))
  }

  /** The id of the first tool call, which keys the thinking blocks that came with it. */
  firstToolId(): string | undefined {
    return [...this.tools.values()][0]?.id
  }

  /** The assistant message this stream built, as Messages API content blocks. */
  blocks(): { type: string; [key: string]: unknown }[] {
    return [...(this.answer ? [{ type: 'text', text: this.answer }] : []),
      ...[...this.tools.values()].map(tool => ({ type: 'tool_use', id: tool.id, name: tool.name, input: tool.input }))]
  }

  result(e: Pick<TurnStepInput, 'turnId' | 'index'>): TurnStepResult {
    return { turnId: e.turnId, index: e.index, answer: this.answer,
      toolUses: [...this.tools.values()].map(tool => ({ name: tool.name, input: tool.input })),
      stopReason: this.stopReason, usage: { ...this.usage } }
  }
}
