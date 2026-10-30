# What your models can do

[繁體中文](FEATURES.zh-TW.md) · [README](../README.md)

- **Streaming and tools.** Text and tool calls stream. Before any output has arrived, HTTP 429, 502, 503, 504 and 529 and other transient errors are retried after 2, 6 and 15 seconds (three retries at most). An integer `Retry-After` of 0–15 seconds raises the next wait to at least that value; a larger value ends the turn immediately with the HTTP status and requested wait. Invalid values and HTTP dates are ignored. Once output has started, a broken stream ends the turn without replaying it.
- **Built-in tools, Skills and MCP.** They work as usual. Tool input schemas are not passed on, so Claude Code validates arguments itself.
- **Subagents and Workflow.** From a subscription session, hand a task to one of your models with the `model-mod:local-worker` agent type (needs `workerModel` or `fallbackModel`), or give a Workflow agent `model: "<your-model-id>"`. A session on one of your models can still delegate to a subscription model; that request uses the subscription.
- **Web search and fetch.** On the API path, `web_search` runs through the API upstream. Codex login uses native web search when `codexWebSearch` is on and WebSearch is available in the session. `web_fetch` downloads public HTTP(S) pages itself and checks every DNS answer at each hop, refusing private and special-use addresses (five redirects at most).
- **Image generation.** `generate_image` saves a PNG in the working directory. The API path uses `/v1/images/generations` and a configured image model; Codex login uses its built-in image generation without `imageModel`.
- **Codex reasoning continuity.** Opaque reasoning items may be retained in memory during tool loops using experimental app-server APIs; replay with a real Codex turn is unverified. See [limitations](LIMITATIONS.md#codex-login-limitations).
- **Tool search.** `tool_search` finds MCP tools whose schemas were deferred.
- **Effort.** Claude Code's five levels (`low`, `medium`, `high`, `xhigh`, `max`) are sent as a model suffix such as `model(high)`. For Codex login the helper converts the suffix to app-server effort, including `max`; `effortMode` applies only to the API path. Ultracode is a separate workflow toggle and does not change the level.
- **Compaction.** `/compact` and automatic compaction use your model. A summary keeps what the model keeps; it is not a lossless archive.
- **Images and PDF.** Images are forwarded. A one-page PDF is read as an image.
- **Prompt cache.** API cache usage is passed through; Codex usage is derived from app-server token usage. Cache accounting semantics have not been fully verified.
- **Automatic switch (off by default).** Set `fallbackModel` and, once a turn ends with your subscription usage at `fallbackPercent` and a reset time ahead, the session switches to that model with a notice and switches back after the reset. It does not resend the turn that hit the limit, reset any limit or run during a tool loop or in subagents. A manual model change cancels the switch back. While switched, your conversation goes to your upstream.

For Codex models, the tool list excludes the mod’s `web_search`; native search activity is shown as text lines in the assistant response, not the built-in “Searched” block. Real-client rendering has not been verified; `generate_image`, `web_fetch` and `tool_search` remain available. Codex automatic compaction items are unsupported; see [limitations](LIMITATIONS.md#codex-login-limitations).

`web_search`, `web_fetch`, `generate_image` and `tool_search` are registered while model-mod is active (`generate_image` with an API image model or a configured Codex account, `tool_search` unless tool search is off), adding up to about 3 KB of tool definitions to requests on subscription models. They refuse calls on subscription models; use Claude Code's built-in tools there. They follow Claude Code's permission rules. How a model behaves is up to the model; this plugin does not make it equal to a subscription model.

## Background Codex delegation

Use `--background` with `/model-mod:review` or `/model-mod:rescue` to start a job without waiting. By default it makes no file writes; read-only commands may still run. `/model-mod:rescue --write` enables workspace-write only after an interactive confirmation, in the foreground or background. `/model-mod:jobs [ID] [--all]` lists the current workspace or all workspaces, or inspects one job; `/model-mod:result ID` reads its output, `/model-mod:cancel ID` cancels it, and `/model-mod:jobs --clear` removes finished jobs and results for the current workspace. IDs may be unique hexadecimal prefixes of at least four characters. Completion notices are best effort.
