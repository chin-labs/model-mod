# Changelog

All notable changes to this project are listed here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Every release that changes plugin code or manifest files raises the `version` in `.claude-plugin/plugin.json`; installed clients only pick up a release whose version differs from the one they have.

## 0.1.1 - 2026-10-24

### Fixed
- A tool call that the upstream stream cut off before the end of its block is no longer handed to the client as a partial call. Tool chunks are now held until the block stops, so an interrupted tool call ends the turn cleanly or is retried instead of making the client resend the request on every turn.
- `generate_image` works with the BSD `sed` that macOS ships.

### Changed
- `generate_image` refuses a path that resolves outside the working directory (including through a symbolic link) and does not overwrite an existing file. The permission prompt shows the path.
- The four `/model-mod:*` commands can no longer be invoked by the model through the Skill tool; they remain available to you.
- A tool block whose `content_block_stop` is missing is emitted when `message_stop` arrives. Events after `message_stop` are ignored.

### Documentation
- Traditional Chinese limitations and features pages brought in line with the English pages.
- Documented that SDK and `-p` callers must check for a result starting with `model-mod:`, when the four tool definitions are registered, and that Claude Code 2.1.310 was tested.

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
