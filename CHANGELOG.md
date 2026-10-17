# Changelog

All notable changes to this project are listed here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Every release that changes plugin code or manifest files raises the `version` in `.claude-plugin/plugin.json`; installed clients only pick up a release whose version differs from the one they have.

## 0.1.0 - 2026-10-17 — first public release

### Added
- Models from your own Messages-compatible API next to the client's built-in models, chosen per session with `/model-mod:model`.
- `/model-mod:setup`, `/model-mod:refresh` and `/model-mod:status` commands.
- Streaming, tool calls, Skills, MCP servers, subagents and Workflow agents with your models, with retry of transient upstream errors before any output.
- `web_search`, `web_fetch` (with per-hop address checks), `generate_image` and `tool_search` for your models.
- The client's five effort levels, sent as a model suffix.
- Local compaction, session titles and `/btw` through your upstream, with prompts you can replace through `promptsDir`.
- Optional automatic switch to one of your models when the subscription's usage limit is reached (`fallbackModel`, `fallbackPercent`) and a `model-mod:local-worker` agent type (`workerModel`).
- Nine configuration options (`baseUrl`, `apiKey`, `models`, `imageModel`, `contextWindow`, `fallbackModel`, `fallbackPercent`, `workerModel`, `promptsDir`) and eight advanced options.

### Known limitations
- Tested on client versions 2.1.299 to 2.1.301. See [docs/LIMITATIONS.md](docs/LIMITATIONS.md) for differences from a subscription model and for behavior that has not been verified.
