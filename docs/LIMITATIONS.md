# Limitations

[繁體中文](LIMITATIONS.zh-TW.md)

This page lists where your models differ from a subscription model, what has not been verified, and which Claude Code requests can still reach your subscription. It applies to models routed by model-mod; subscription models keep Claude Code's normal route. CLIProxyAPI is one tested API upstream example; Codex login is a separate upstream. See the [README](../README.md) for setup.

## Parent thread privacy and cleanup

With `codexThreadReuse` on, the parent rollout in the account directory contains a fixed synthetic turn and tool definitions (which may include MCP tool names), but not conversation messages or system prompts. It also contains fixed developer instructions selected by the web-search setting. On November 1, 2026, a check of rollout, SQLite and log files in one Mac's account directory found no conversation, history or overridden instructions; this is not a guarantee that local traces never remain. Content is still sent to OpenAI, as it is with this feature off. The account directory is private (0700). Each session incurs one extra short synthetic turn per parent; switching settings can create another. The registry holds hashes, thread IDs, timestamps and numeric parent usage totals, not conversation content. Different tool lists can have separate parents; at most four active parents are retained per session and account, with least-recently-used parents deleted first. A six-hour idle TTL is checked opportunistically on later requests; replacement and session end also attempt `thread/delete`. This is not a precise timer or a deletion guarantee: failures are retried on later requests to that account, and removed accounts cannot be cleaned automatically. On unsupported platforms or when reuse fails, the bridge uses a new ephemeral thread. Set `codexThreadReuse` to `off` to use only ephemeral threads and avoid the registry.

## Tested versions

Codex login and the API upstream were tested on **Claude Code 2.1.314**. The API upstream was also tested on 2.1.299 to 2.1.310; on 2.1.310, plugin loading, unit tests, turns and the update path were checked. A manual end-to-end check on one Mac used Claude Code 2.1.316 with Codex 0.166.0 (see [Not verified](#not-verified)). Other versions have not been tested, so do not assume they work. These checks used a test configuration rather than the normal secret-option flow, so they say nothing about how your key is stored (see [Not verified](#not-verified)).

Marketplace installs were tested from a local clone and from a Git server over the standard HTTP protocol. Claude Code does not support installing from a plain ("dumb") HTTP Git server, and it leaves the plugin cache behind after an uninstall.

## Unrecognized model warning

At startup Claude Code may warn that a non-Claude model ID is not recognized and that its context is assumed to be 200k. This is client behavior that model-mod cannot suppress. After a model is selected, model-mod applies its own context window; Codex uses the effective catalog window or 128,000 tokens if unavailable.

## Codex login limitations

- The last tested Codex CLI version is **0.166.0**; the minimum is **0.165.0**, and older versions are rejected. Newer versions run but have not been verified individually. Before updating the tested-version record, run the manual live contract test against the new version.
- Isolation is **not a strict tool whitelist**. The helper uses a dedicated home, read-only sandbox, no approvals and disabled features, but the two MCP resource-list tools can still run. Runtime item checks stop a turn on disallowed or unknown items that arrive before the turn is interrupted, or together with a wait item in the same list, with the message `Codex used a built-in tool that model-mod does not support (<type>); try again, and report it if it keeps happening`. If a `sleep` or `collabAgentToolCall` item appears despite disabled features, the helper interrupts the turn and ends it normally; subsequent non-tool items are discarded while recognized dynamic tool calls are retained. Before starting a thread, `config/read` checks effective settings; if a new version changes those settings or the protocol, the helper fails closed. A protocol incompatibility reports `incompatible app-server protocol; update or check Codex`. Check configuration and Codex compatibility before retrying.
- Codex built-in shell, network and browser tools, sleep, subagents, apps, plugins and goals are disabled. Patch and file operations are blocked by the read-only sandbox and item whitelist; item handling follows the checks above. Dynamic tools come from the client, with the MCP resource-list exceptions above. The model receives brief developer instructions to use only provided function tools, avoid built-in sleep, wait, collaboration and subagent tools, and end the turn when waiting for background work; it is not told the read-only isolation details.
- Codex reserves names beginning with `mcp__` and restricts tool names. The bridge sends affected names as `bridge_` plus a hash and restores the original name on return.
- `max_tokens` is accepted but ignored. `tool_choice`, `temperature`, `top_p`, `stop_sequences`, `cache_control` and thinking budgets are ignored. The helper writes internal `model-mod-note:` diagnostic lines, which are discarded and not shown to users. Do not rely on these controls being enforced.
- `codexKeepReasoning` defaults to `on`. Reasoning is not retained on forked requests with thread reuse; set `codexThreadReuse` to `off` to allow retention. The bridge uses the experimental `experimentalRawEvents` and `thread/inject_items` interfaces in Codex 0.165.0; these APIs may change, and replay has not been verified with a real Codex turn. OpenAI's opaque reasoning item can contain encrypted data; its signature is limited to 256 KiB per item and 1 MiB per response, with excess discarded. Only reasoning before the first assistant text or tool call is retained; later interleaved reasoning is discarded to preserve replay order. It is kept in memory for tool exchanges in the same session and is lost on reload or restart. Changing account or model can invalidate it; if rejected before output, the request is rebuilt once without reasoning. This does not guarantee equivalence to the API path.
- Codex native search is enabled only when `codexWebSearch` is on and WebSearch is present in the session tool list. Native search and openPage run at OpenAI and are not constrained by Claude permission domain rules (allowed or blocked domains); model-mod makes no `allowed_domains` security claim. Queries are sent to OpenAI. Native searches do not prompt through Claude for each search, and the displayed search text enters assistant history. Search activity is shown as one assistant text line per search, not an expandable tool result or the built-in “Searched” block; the assistant text line was seen once in a real client on one Mac, and opaque results are not displayed. The mod’s `web_search` is not offered to Codex; `generate_image` and `web_fetch` remain available. Codex image generation uses its built-in image model and sends the prompt and generated image content to OpenAI. Size and quality are requests in the prompt, not guarantees; quota accounting is unverified. Images over 20 MiB are rejected. Even with a read-only sandbox, app-server writes its own image under `CODEX_HOME/generated_images`. After obtaining the bytes, model-mod attempts to remove that literal path without following symlinks; failure is noted internally and does not fail the call. Saved output is exclusively created with mode 0600. Codex context defaults to the account catalog's window multiplied by its effective percentage, or 128,000 tokens if unavailable; an explicit `contextWindow` overrides it. The helper sets the Codex auto-compaction threshold above the client window and notes compaction events internally. This does not guarantee Codex compaction is disabled or disable model-mod's own compaction.
- Each call starts a local helper process and `codex app-server`, adding latency; startup latency has not been measured. Windows is **not verified**; see the [Windows checklist](WINDOWS.md). Codex image generation is POSIX only.
- Codex quotas and rate limits are determined by your own subscription. model-mod does not rotate accounts when a limit is reached.
- An account name containing `claude` or `anthropic` causes its model IDs to be filtered. When a valid API key is configured with a refused `baseUrl`, the entire mod, including Codex, is inactive.

## Known limitations

Previously saved legacy `/model` custom rows may remain visible after an upstream is removed; selecting a removed model is refused, so choose another model or remove the old row from your settings. APIs supplied by `MODEL_MOD_CONFIG` cannot be removed from setup; edit that file yourself. Removing an API disables it but leaves its key in the client’s secure storage; model-mod cannot clear the key. When readding it, setup confirms the host before sending the stored key.

| Area | What to expect | Workaround |
|---|---|---|
| Output length and context | `maxTokens` defaults to 32000, and CLIProxyAPI with Codex did not enforce a smaller value; the true maximum output is unknown. For API models the default context window is 272000 (set `contextWindow`, minimum 32000). A very small window makes Claude Code's auto-compact threshold negative, so it compacts over and over. | Set `contextWindow` to the model's real limit. |
| Request content | Turns send `model`, `max_tokens`, `stream`, `messages`, `system` and optional `tools`. Claude Code's other request fields are not sent. | None needed. |
| Reasoning | On the API path, only Codex-style encrypted reasoning signatures are handed back within a tool loop. Other thinking and server-tool blocks are dropped. A rejected signature is retried once without it. | Set `keepThinking: false` if your upstream rejects signatures. |
| Effort | On the API path the five levels are sent as a model suffix, such as `model(high)`; on Codex login the helper clamps to the model catalog, maps `max` to its highest declared effort and never sends `minimal`; if the catalog is unavailable it preserves the requested value. Without an effort suffix, `low` is used when available, otherwise the model default. That confirms the names reach the upstream, not that reasoning strength changes. Ultracode is a separate toggle and leaves the level unchanged; `/effort ultra` is rejected by Claude Code itself. | Set `effortMode: none` if your upstream rejects the suffix. |
| Failures | Before any output, HTTP 429, 502, 503, 504, 529 and recognized transient errors (including an early `overloaded_error` event) are retried after 2, 6 and 15 seconds (three retries at most). An integer `Retry-After` of 0–15 seconds raises the next wait to at least that value; a larger value ends the turn immediately with the HTTP status and requested wait. Invalid values and HTTP dates are ignored. After output has started, a dropped stream ends the turn without replay. A failed turn is never retried on another model or on the subscription. | Re-send the message, or switch models with `/model`. |
| Compaction | Uses the prompt files in `prompts/` only; a missing file skips local compaction. Summary quality depends on the model. The transcript sent for summarizing is capped (600000 characters in total, 20000 per message, 1500 per tool result). Compaction inside agents has not been verified. | Keep important facts in project instructions, not only in the conversation. |
| Tools | Tool schemas are open (names and descriptions only). On API models, `web_search` and `web_fetch` replace the native WebSearch and WebFetch; Codex models retain `web_fetch` and use native search instead of the mod’s `web_search`, and `web_fetch` returns the page without a model summary. The four mod tools (`web_search`, `web_fetch`, `generate_image`, `tool_search`) refuse calls on subscription models; use the built-in tools there. `web_fetch` refuses some public IPv6 literals, and special IPv6 transition forms are not fully covered. | Use another URL form, or fetch with another tool. |
| Subagents and Workflow | Subagents get the session system prompt plus a delegation note. A subscription session cannot name one of your model IDs in an Agent call; use the `model-mod:local-worker` agent type or a Workflow agent. The context-window override follows the main session. | Set `workerModel` and use `model-mod:local-worker`. |
| Images and PDF | Images work. A one-page PDF becomes an image. Native document blocks and multi-page PDFs have not been verified. | Convert pages to images. |
| Usage display | Requests to your upstream do not change the subscription usage display, and CLIProxyAPI replies carry no rate-limit fields. | Check your upstream's own usage page. |
| Saved default model | Claude Code saves interactive model choices as its default. Uninstalling with a local model saved leaves an unusable default. | Select a subscription model first, or remove the saved `model` setting. |
| Model picker | `/model-mod:model` lists your models. Claude Code's own `/model` panel and `/config` Model do not, and `--model <id>` at startup bypasses the picker (it works with one of your IDs). | Use `/model-mod:model`, or type `/model <id>`. |
| Organization-managed Claude Code | Title, model-switch and compaction hooks skip personally installed plugins unless the organization lists them. This setup has not been tested. | Ask your administrator to list the plugin. |

SDK and `-p` callers must check whether the result text starts with `model-mod:`: failed turns deliberately end with a text message and `end_turn`, with `is_error` set to `false`, because throwing an exception would make the engine use the subscription endpoint.

## Not verified

These behaviors have not been verified. Do not assume they work.

- Real-client setup and Remote Control have not been verified end to end. Manual checks on one Mac (Claude Code 2.1.316, Codex 0.166.0, one account) covered foreground review and rescue, Ctrl+C and Esc interruption, and completion toasts in the originating session.
- Windows as a whole is unverified; use the [Windows checklist](WINDOWS.md).
- Hook time budgets, reload behavior and `$.store` permissions are unverified.
- Experimental reasoning replay is unverified: two real turns with tool exchanges ran without errors, but no thinking blocks appeared in the transcript. Real image generation and native search were checked once on one account.
- Strict adherence to review `outputSchema`, which the Stop gate depends on, is unverified; pass, block and unknown results were each observed once with a real Codex.
- Commentary event ordering and the real ordering of `classic.Stop` with official plugin hooks are unverified.
- Coexistence with the official `openai/codex-plugin-cc` rests on a static comparison of upstream commit `db52e28f4d9d`; the plugins have not been run side by side. Use fully qualified command names (`/codex:review`, `/model-mod:review`) and enable at most one Stop review gate. Their default Codex homes are separate, but explicitly pointing both at the same `CODEX_HOME` can make account settings and trust records interact.
- Switching on exhausted Codex quota and `priority` billing and actual `codexServiceTier` service are unverified; a real turn with `priority` was accepted.
- Continuing a transferred session with `codex resume` is unverified; the import itself and a multi-file workspace-write rescue with `apply_patch` were checked once.
- Linux was verified offline only: helper tests, fake Codex flows and the socket path limit passed in a Linux arm64 container (Python 3.12, Git 2.34, no network). Hook tests, real account turns, the `/proc` fallback and the Git 2.54 configured-hook checks were not run there. exFAT is unverified.
- **Codex environments.** Windows, a real run on Python 3.9, live SIGHUP cleanup, and individual newer Codex versions have not been verified. Startup latency has not been measured. The `max` effort level has only been tested with a fake Codex.
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

Codex accounts are not rotated when quota is exhausted; configure a fallback model on another account or upstream. API upstreams have no official rateLimits and are not covered by Codex fallback.

Codex reasoning retention is experimental: signatures are filtered by prefix and cached under the first tool-call ID, not a full conversation identity. Real Codex replay is unverified.

## Review gate limitations

The Stop gate is off by default. Structured verdict quality, missed findings and whether a real Codex honors `outputSchema` are unverified; the gate is not a security or compliance guarantee. Ordering alongside the official Codex gate is unverified. A turn that continues because of a block is not reviewed again: the status then says the changes were not re-reviewed, so a limit of two blocks does not mean the fix gets a second review. Pressing Esc during a gate review ends the helper and allows ending with the unverified warning. A pass is cached in memory for a matching session and fingerprint; module reload resets the pass cache and gate block counts. The automatic gate silently skips directories without `.git` in their ancestry; repositories without HEAD and Git errors produce an unverified warning. It has no base ref; if changes are committed within the turn, it can silently skip them. Binary or unavailable untracked files, dirty submodules and oversized diffs cannot be reviewed by this gate. A changed workspace needs a fresh review, and concurrent changes can occur after the snapshot check. Unknown, error and timeout allow ending with a human-review warning; after the configured maximum of one or two blocks, a further block also allows ending without a pass.

Transfer supports only the default Claude configuration directory (`~/.claude`); offline tests with Codex 0.166 found that its import detection searches `HOME/.claude`, not a custom `CLAUDE_CONFIG_DIR`.

## Background delegation limitations

- Background commands are unsupported on Windows; foreground delegation remains available. Ctrl+C and `/reload-plugins` left the broker running in a manual check on macOS.
- If the broker dies, jobs are interrupted rather than resumed and are marked `interrupted` on recovery. Cleanup is best effort: macOS `ps lstart` has second-level resolution, PID reuse and TOCTOU windows exist, and grandchildren that call `setsid` may escape cleanup. If cleanup cannot be confirmed, the error is `possible_leftover`. Completion notices are best effort and appear only in the session that started the job; use `/model-mod:jobs` and `/model-mod:result` from another session.
- The background broker exits after 30 minutes without activity when no job is running; a leftover broker process can remain until then.
- Background delegation supports the default accounts root only; use foreground delegation for a custom accounts root. `codexBin` must be executable in the broker's environment.
- In write mode, Codex may run commands and modify your real working directory; there is no automatic backup. Commit or stash changes first. Sandbox restrictions apply to Codex commands and file writes, not all external side effects. Disabling network access has not been verified across platforms.
- Codex can record project trust in the account's `config.toml` when starting workspace-write. model-mod requests an untrusted project override for the thread; in offline tests with Codex 0.166.0 this avoided the persistent trust record. Delegation and image generation refuse an enabled or unverifiable project configuration layer, including one enabled by existing account trust. Write delegation also refuses a trusted project record for the working directory after thread start; an explicit `untrusted` record is accepted. To remove that trust, untrust the project in the account's Codex settings.
- The read-only sandbox does not confine reads to the workspace: commands may read files outside it. This differs from the Messages bridge above, where the built-in shell is disabled.
