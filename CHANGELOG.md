# Changelog

All notable changes to this project are listed here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Every release that changes plugin code or manifest files raises the `version` in `.claude-plugin/plugin.json`; installed clients only pick up a release whose version differs from the one they have.

## 0.2.3 - 2026-11-02

### Added
- `/model-mod:doctor` checks the setup in plain language and prints what is wrong and the next step: whether the plugin is active, whether the API upstream answers its model list (host shown only if it is a loopback address, never the key), invalid Codex settings, `workerModel`/`fallbackModel` values that are not accepted, and per Codex account the Codex install, login, quota read and full windows. It sends no prompt and uses no quota; an upstream configured with a header file is reported as not checked.

### Changed
- `workerModel` and `fallbackModel` accept a bare model ID (for example `gpt-6.1-sol`) under Codex login when exactly one Codex account offers it; with several matching accounts the status line lists up to four `<account>/<model>` candidates, and with none it says to use `<account>/<model>`.
- When a Codex account's quota window is full but upstream still reports ordinary usage as allowed, `/model-mod:status` and the diagnostics say so neutrally ("requests may fail") instead of implying the account is usable.

### Not verified
- A real Codex login with a bare `workerModel`; the exact error shapes the client engine returns for a missing interpreter or a failed network request (doctor classifies by message text and falls back to a generic row); `/model-mod:doctor` in Remote Control, desktop and VS Code sessions and on Windows.

## 0.2.2 - 2026-11-01

### Changed
- `/model-mod:status` prints a plain-text report in the order quota, current path and grouped diagnostics: one quota block per Codex account with 5-hour and weekly usage bars, percent used and the reset time (relative and local); a limited account, a failed query and an API upstream without quota data each carry a text marker (`[LIMIT]`, `[!]`, `[--]`) as well as their reason. Warnings come first, including the newest Stop gate warning of this session; line width follows the terminal and `NO_COLOR` or `TERM=dumb` gives `#`/`-` bars. While the Codex quota is read a toast says so; the status line, which holds messages such as the Stop gate warning, is not touched.
- `/model-mod:setup` shows its fixed menus (upstream, endpoint, model scope, confirmations, manage upstreams) in one pane that stays open until setup ends. Esc or the pane's close mark closes the pane and cancels: setup asks nothing more and writes no setting after that. A step that is already running (a model list request, an account logout) cannot be stopped; it finishes first and its result is discarded. A dialog that another command opens while a menu waits closes the pane the same way. Text inputs and menus of more than 12 entries stay dialogs; where no pane can be seated (`-p`, bridge sessions, a body too small) the menus are dialogs and a typed answer that is not a listed option is asked again, three times at most, then setup cancels.
- A second `/model-mod:setup` while one is open is refused.

### Not verified
- The setup pane in Remote Control, desktop and VS Code sessions; arrow-key selection in the pane was not driven in an automated terminal (Tab, Enter and Esc were). Checked on one Mac with Claude Code 2.1.316 only.

## 0.2.1 - 2026-11-01

### Changed
- Forked requests do not retain raw reasoning; disable thread reuse to allow retention.

### Added
- Reuse a short parent thread for Codex login requests with ephemeral forks and full history replay; the option can be disabled.

## 0.2.0 - 2026-10-31

### Added
- Structured manual Codex review gate and an optional, default-off Stop gate with a bounded block count; checked manually on one Mac, with ordering alongside the official Codex plugin unverified. A turn that continues after a block is not reviewed again.
- Keep opaque Codex reasoning in memory during tool exchanges using experimental app-server APIs; replay with a real Codex turn is unverified.
- Codex login supports native web search when permitted, with activity shown as one assistant text line per search.
- Interactive confirmation for workspace-write Codex rescue.
- Confirmed session transfer to a Codex account.
- Read-only Codex delegation: `/model-mod:review` (native review, `--base`, `--adversarial`) and `/model-mod:rescue` run in the foreground or with `--background`; `/model-mod:jobs`, `/model-mod:result` and `/model-mod:cancel` manage background jobs, with best-effort completion notices.
- Guided Codex device authentication during setup, with account directories shown in setup and status.
- Management of configured Codex accounts and API upstreams from setup, including logout and optional account-directory deletion.
- Codex login upstream through the official `codex app-server` and a local Python helper. Models use `<account>/<model>` IDs and display as `<model> @ <account>`; setup offers an upstream choice. Configure `codexAccounts`, `codexModels`, `codexAccountsDir`, `codexBin` and `pythonBin` in plugin options.
- Status reports Codex accounts and usage limits. API and Codex upstreams can coexist; Codex takes precedence for matching IDs.
- Codex login models can generate images on POSIX through a separate isolated app-server session; requested size and quality are not guaranteed.

### Changed
- Clamp Codex reasoning effort to the model catalog, show quota windows and plan, and support an optional priority service tier.
- Use official Codex rate limits for a configured fallback without automatic account rotation.
- Codex turns use client-provided dynamic tools; other built-in capabilities are disabled, with two MCP resource-list tools still available. Reserved `mcp__` and incompatible tool names use reversible aliases. Codex CLI versions below 0.165.0 are refused.
- The client's built-in ToolSearch is no longer offered to your models (API and Codex); the mod's own `tool_search` loads MCP tool schemas instead. `/model-mod:model` labels each model `(Codex login)` or `(API)`.
- Codex requests use bounded retries and handle upstream 429 responses. Codex uses native search instead of the mod’s `web_search` tool; its context window uses the effective account catalog value, falling back to 128,000 tokens.
- Side-question command messages no longer repeat the client label, and the informational agent message count status is no longer shown.

### Fixed
- Accept Codex workspace-write sandbox responses without explicit writable roots and avoid persisting project trust during rescue. Delegation and Codex image generation refuse enabled or unverifiable project configuration, including when an account already trusts a repository's project configuration.
- Transfer explains when a custom `CLAUDE_CONFIG_DIR` is unsupported.
- Warn instead of silently skipping damaged Git repositories, retain possible-leftover job warnings preferentially, bound process cleanup waits and explain overlong background socket paths.
- Check Codex image output paths before generation and keep image approvals separate for API and Codex upstreams.
- Improve background job cleanup and status messages; avoid appending native search text after a tool call.
- Allow the full device code lifetime during Codex setup and report expired login codes.
- Removing an API upstream disables it without clearing its key from the client’s secure storage; when readding it, setup confirms the host before sending the stored key.
- Explicit Codex `contextWindow` settings are no longer replaced by the default.
- Tool references in Codex tool results are separated from adjacent text.
- Waiting turns check every item for unsupported behavior and retain recognized dynamic tool calls received after interruption.
- Setup and status explain unsupported Codex versions, and model selection reports unavailable account directories.
- Codex turns that invoke built-in sleep or collaboration tools now end normally instead of failing.
- On the Codex path, `tool_reference` blocks in tool results are converted to text, one per line, so a conversation that used the client's tool search no longer fails with an invalid-request error.
- Use UTF-8 for helper standard streams and clarify setup and account-directory error hints.

### Documentation
- Update the English and Traditional Chinese README and documentation for both upstreams. Add a Windows verification checklist; Windows, Python 3.9 and concurrent use of two Codex accounts remain unverified.
- Record the tested Claude Code versions, explain the unrecognized model warning and link to device authentication instructions.
- Clarify Codex and API data flows, isolation limits, setup and refresh behavior, troubleshooting and unverified environments.

## 0.1.2 - 2026-10-30

### Changed
- Retries honour an integer `Retry-After` header on HTTP 429, 502, 503, 504 and 529: a value of 0–15 seconds raises the next wait to at least that value; a larger value ends the turn immediately with the HTTP status and the requested wait. Invalid values and HTTP dates are ignored. The header is read through curl's `--write-out` (curl 7.84 or newer; with an older curl the plain backoff applies), and after a streamed error event the request waits up to 2 seconds for it.
- A streamed request is aborted after about five minutes in which the upstream sends less than one byte per second. The turn is then retried against the same model if nothing was streamed yet.
- Failed requests say more about the cause: a final HTTP 429 reads `upstream rate limited (HTTP 429)`, and curl failures name a connection failure, a timeout or a TLS error with the curl exit code.
- With the plugin options, a session no longer waits up to 8 seconds for the upstream's model list. With cached models the list is refreshed in the background; without them the session waits at most 2 seconds. The image tool is registered when a background refresh finds an image model.
- `/model-mod:status` shows the host name only for loopback addresses (`localhost`, 127.0.0.0/8, `[::1]` and IPv4-mapped 127.0.0.0/8) and `host=remote` otherwise. It warns when plain HTTP sends the API key to a non-loopback host and when the configured `headerFile` is missing.
- Command replies no longer repeat the `model-mod:` label that Claude Code already adds. When the mod is inactive and `MODEL_MOD_CONFIG` is set, the message points to that file.
- `generate_image` creates the output file exclusively and refuses an existing file or symbolic link at the target even if one appears while the image is downloaded. A failed write removes the partial file, and the temporary file is removed when the call is interrupted. A target directory that cannot be resolved is reported as such.

### Documentation
- The marketplace description says the plugin does not modify the Claude Code binary.
- Documented the `Retry-After` handling and the `status` host and warning output; the status example in Troubleshooting shows the client's `model-mod:` label.
- Documented that a failed request is only ever retried against the same model.

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
