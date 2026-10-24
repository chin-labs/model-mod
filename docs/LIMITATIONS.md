# Limitations

[繁體中文](LIMITATIONS.zh-TW.md)

This page lists where your models differ from a subscription model, what has not been verified, and which Claude Code requests can still reach your subscription. It applies to models routed by model-mod; subscription models keep Claude Code's normal route. The tested upstream is CLIProxyAPI with your own Codex login. See the [README](../README.md) for setup.

## Tested versions

model-mod was tested on **Claude Code 2.1.299 to 2.1.310**. On 2.1.310, plugin loading, unit tests, turns and the update path were checked. Other versions have not been tested, so do not assume they work. These checks used a test configuration rather than the normal secret-option flow, so they say nothing about how your key is stored (see [Not verified](#not-verified)).

Marketplace installs were tested from a local clone and from a Git server over the standard HTTP protocol. Claude Code does not support installing from a plain ("dumb") HTTP Git server, and it leaves the plugin cache behind after an uninstall.

## Known limitations

| Area | What to expect | Workaround |
|---|---|---|
| Output length and context | `maxTokens` defaults to 32000, and CLIProxyAPI with Codex did not enforce a smaller value; the true maximum output is unknown. The default context window is 272000 (set `contextWindow`, minimum 32000). A very small window makes Claude Code's auto-compact threshold negative, so it compacts over and over. | Set `contextWindow` to the model's real limit. |
| Request content | Turns send `model`, `max_tokens`, `stream`, `messages`, `system` and optional `tools`. Claude Code's other request fields are not sent. | None needed. |
| Reasoning | Only Codex-style encrypted reasoning signatures are handed back within a tool loop. Other thinking and server-tool blocks are dropped. A rejected signature is retried once without it. | Set `keepThinking: false` if your upstream rejects signatures. |
| Effort | The five levels are sent as a model suffix, such as `model(high)`. That confirms the names reach the upstream, not that reasoning strength changes. Ultracode is a separate toggle and leaves the level unchanged; `/effort ultra` is rejected by Claude Code itself. | Set `effortMode: none` if your upstream rejects the suffix. |
| Failures | Before any output, HTTP 429, 502, 503, 504, 529 and recognized transient errors (including an early `overloaded_error` event) are retried after 2, 6 and 15 seconds (three retries at most). After output has started, a dropped stream ends the turn without replay. A failed turn is never retried on another model or on the subscription. | Re-send the message, or switch models with `/model`. |
| Compaction | Uses the prompt files in `prompts/` only; a missing file skips local compaction. Summary quality depends on the model. The transcript sent for summarizing is capped (600000 characters in total, 20000 per message, 1500 per tool result). Compaction inside agents has not been verified. | Keep important facts in project instructions, not only in the conversation. |
| Tools | Tool schemas are open (names and descriptions only). On your models, `web_search` and `web_fetch` replace the native WebSearch and WebFetch, and `web_fetch` returns the page without a model summary. The four mod tools (`web_search`, `web_fetch`, `generate_image`, `tool_search`) refuse calls on subscription models; use the built-in tools there. `web_fetch` refuses some public IPv6 literals, and special IPv6 transition forms are not fully covered. | Use another URL form, or fetch with another tool. |
| Subagents and Workflow | Subagents get the session system prompt plus a delegation note. A subscription session cannot name one of your model IDs in an Agent call; use the `model-mod:local-worker` agent type or a Workflow agent. The context-window override follows the main session. | Set `workerModel` and use `model-mod:local-worker`. |
| Images and PDF | Images work. A one-page PDF becomes an image. Native document blocks and multi-page PDFs have not been verified. | Convert pages to images. |
| Usage display | Requests to your upstream do not change the subscription usage display, and CLIProxyAPI replies carry no rate-limit fields. | Check your upstream's own usage page. |
| Saved default model | Claude Code saves interactive model choices as its default. Uninstalling with a local model saved leaves an unusable default. | Select a subscription model first, or remove the saved `model` setting. |
| Model picker | `/model-mod:model` lists your models. Claude Code's own `/model` panel and `/config` Model do not, and `--model <id>` at startup bypasses the picker (it works with one of your IDs). | Use `/model-mod:model`, or type `/model <id>`. |
| Organization-managed Claude Code | Title, model-switch and compaction hooks skip personally installed plugins unless the organization lists them. This setup has not been tested. | Ask your administrator to list the plugin. |

SDK and `-p` callers must check whether the result text starts with `model-mod:`: failed turns deliberately end with a text message and `end_turn`, with `is_error` set to `false`, because throwing an exception would make the engine use the subscription endpoint.

## Not verified

These behaviors have not been verified. Do not assume they work.

- **Automatic switch.** Switching back after a real usage reset, the rate-limit data after a real rejected request, and triggering from Remote Control.
- **Remote Control and mobile.** Only short sessions were tried. Long sessions and choosing a model from mobile are untested.
- **Real upstream rate limits.** Retries were tested, but not failover between exhausted upstream credentials, nor the effect of cached tokens on your quota.
- **Versions and key storage.** Versions other than those above, the normal secret-option flow with macOS keychain storage, and keeping the key and settings across a Claude Code upgrade.
- **GitHub-hosted marketplace.** Installing directly from a marketplace hosted on GitHub has not been tested end to end; use a local clone if it fails.
- **Long or complex work.** Long sessions with repeated compaction, compaction inside agents, long Workflows, multi-page PDFs and native document blocks, continuing a signed-reasoning conversation in a later session, and continuing agents across sessions.
- **Fetch network defenses.** Address and redirect restrictions are unit-tested; real DNS rebinding and external redirect attacks have not been tested end to end.
- **Other side requests.** Claude Code requests listed at the end of the next section.

## Subscription side requests

Claude Code makes some requests on its own, independently of the model you selected. With the defaults (`localTitle: true`, `localContext: true`, `sideModel: claude-haiku-5-5`), the table below shows which of them reach your subscription endpoint. It covers only the paths that were checked, not every Claude Code request, so it is not a complete privacy guarantee.

| Feature or setting | What is sent to your subscription | Notes |
|---|---|---|
| First-prompt title with `localTitle: false` | The first user prompt | Goes to the official `sideModel`; the default (`true`) names the session through your upstream. |
| Auto permission mode | The conversation, project instructions and command or tool inputs | A separate classifier model on your subscription, not `sideModel`. Default and acceptEdits modes made no classifier request for the command tested. |
| `Agent(model: 'haiku')` | The subtask prompt and project instructions | Runs on the official model. `model-mod:local-worker` uses your upstream. |
| `/rename` without a name | The session's user and assistant messages, even with `localTitle: true` | Known limitation, not fixed. Use `/rename <name>`. |
| `/context` with `localContext: false` | Category contents (including some project instructions) and the model ID | Uses the subscription's token counting. The default local estimate sends nothing. |
| Claude Code's native WebFetch summarizer | The fetched page text and the summarizing prompt | Normal turns on your models use `web_fetch`, which has no summary. |
| `/btw` on one of your models | Nothing | Answered through your upstream with read-only context. |

Not triggered or inconclusive when checked, so treat them as unverified: tool-use summaries, prompt suggestions, away summaries, agent progress summaries, memory extraction, selection and synthesis, LLM-based prompt or agent hooks, subagent compaction, native WebSearch, subscription usage and quota requests, cache touch, and model or key validation.

## Out of scope

| Area | Boundary |
|---|---|
| Global API replacement | model-mod does not change `ANTHROPIC_BASE_URL`, modify the Claude Code binary or rewrite every Claude Code request. |
| Subscription credentials | The mod neither reads nor forwards them. |
| claude.ai connectors | Standard MCP servers are supported; connectors that need a claude.ai login are not. |
| Model equivalence | Routing does not give your upstream model another model's capabilities or identity. |
| Getting around usage limits | The optional switch only changes which model the next message uses. It does not reset or bypass subscription limits. |
