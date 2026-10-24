# What your models can do

[繁體中文](FEATURES.zh-TW.md) · [README](../README.md)

- **Streaming and tools.** Text and tool calls stream. Before any output has arrived, HTTP 429, 502, 503, 504 and 529 and other transient errors are retried after 2, 6 and 15 seconds (three retries at most). Once output has started, a broken stream ends the turn without replaying it.
- **Built-in tools, Skills and MCP.** They work as usual. Tool input schemas are not passed on, so Claude Code validates arguments itself.
- **Subagents and Workflow.** From a subscription session, hand a task to one of your models with the `model-mod:local-worker` agent type (needs `workerModel` or `fallbackModel`), or give a Workflow agent `model: "<your-model-id>"`. A session on one of your models can still delegate to a subscription model; that request uses the subscription.
- **Web search and fetch.** `web_search` runs through your upstream. `web_fetch` downloads public HTTP(S) pages itself and checks every DNS answer at each hop, refusing private and special-use addresses (five redirects at most).
- **Image generation.** `generate_image` calls the upstream's `/v1/images/generations` and saves a PNG in the working directory. It needs an image model.
- **Tool search.** `tool_search` finds MCP tools whose schemas were deferred.
- **Effort.** Claude Code's five levels (`low`, `medium`, `high`, `xhigh`, `max`) are sent as a model suffix such as `model(high)`. Ultracode is a separate workflow toggle and does not change the level.
- **Compaction.** `/compact` and automatic compaction use your model. A summary keeps what the model keeps; it is not a lossless archive.
- **Images and PDF.** Images are forwarded. A one-page PDF is read as an image.
- **Prompt cache.** Cache usage reported by the upstream is passed through.
- **Automatic switch (off by default).** Set `fallbackModel` and, once a turn ends with your subscription usage at `fallbackPercent` and a reset time ahead, the session switches to that model with a notice and switches back after the reset. It does not resend the turn that hit the limit, reset any limit or run during a tool loop or in subagents. A manual model change cancels the switch back. While switched, your conversation goes to your upstream.

`web_search`, `web_fetch`, `generate_image` and `tool_search` are registered while model-mod is active (`generate_image` only with an image model, `tool_search` unless tool search is off), adding up to about 3 KB of tool definitions to requests on subscription models. They refuse calls on subscription models; use Claude Code's built-in tools there. They follow Claude Code's permission rules. How a model behaves is up to the model; this plugin does not make it equal to a subscription model.
