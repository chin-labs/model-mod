# Configuration

[繁體中文](CONFIGURATION.zh-TW.md) · [README](../README.md)

## Choose an upstream

Codex login is the main path; an existing Messages-compatible API server is an alternative, and both can coexist. For Codex, install Python 3.9+ and the official `codex` CLI, then use `/model-mod:setup` and select **Codex login**. If login is needed, setup creates a dedicated account directory and runs `codex login --device-auth`. Open the displayed link, enter the code and select **Continue (after logging in)**, then choose models. If the link is unavailable, setup displays manual terminal commands instead. For an API server, follow the next section and choose **Compatible API server** in setup.

Choose **Manage configured upstreams** in setup to log out or remove a Codex account, or remove an API from plugin options. Logout retains the account settings and directory. Removal retains the directory by default; deleting it requires a second confirmation and is limited to that account's directory. An API supplied by `MODEL_MOD_CONFIG` must be removed by editing that file yourself. Removing an API disables it but leaves its key in the client’s secure storage; model-mod cannot clear the key. When readding it, setup confirms the host before sending the stored key.

## Set up your upstream first

Your own upstream must offer a Messages-compatible streaming API at `/v1/messages`, and you need its API key. CLIProxyAPI is the tested upstream. A `/v1/models` list lets setup discover models; without it you enter model IDs by hand.

For the API-server path, model-mod sends a session to a server that accepts Messages-style streaming requests at `/v1/messages` and checks an API key. Before you install:

1. **Use your upstream.** Any compatible server may be used; CLIProxyAPI is one tested example. model-mod does not install, start or configure it.
2. **Make sure it is running** and reachable from the machine where you run Claude Code. This check reads the same model list that `/model-mod:setup` uses (replace the address and set the key in your shell first); `200` means the address and key work:

   ```bash
   printf 'header = "Authorization: Bearer %s"\n' "$UPSTREAM_API_KEY" | curl -s -o /dev/null -w '%{http_code}\n' -K - http://127.0.0.1:8317/v1/models
   ```

3. **Find the two values the mod needs.** `baseUrl` is the server's address without `/v1`; CLIProxyAPI listens on port 8317 by default, which is why the default `baseUrl` is `http://127.0.0.1:8317`. If your upstream runs elsewhere, enter its address when you configure. `apiKey` is a key your upstream accepts from clients (for CLIProxyAPI, one defined in its own configuration), never a key of Claude Code's subscription.

## System tools

`curl` and `bash` are required. Web fetch also needs `uname` and a system resolver (`getent` on Linux, `dscacheutil` on macOS); API image generation also needs `sed`, `grep`, `tr`, `mktemp`, `ln` and `base64`. Codex image generation uses Python and the official Codex CLI.

## Plugin options

These options appear in the configuration dialog (`/plugin configure model-mod@model-mod`).

The mod activates with either a valid `apiKey` or a valid combination of `codexAccounts` and `codexModels`. Both can coexist. An invalid API key disables the API side, not a valid Codex configuration. For the API path, change `baseUrl` if your server does not use the default address.

| Option | What it does | Default |
|---|---|---|
| `baseUrl` | Base URL of your upstream, without `/v1`. HTTP or HTTPS only; URLs with credentials, queries or fragments, and `anthropic.com` or `claude.ai` hosts, are refused. | `http://127.0.0.1:8317` |
| `apiKey` | Your API upstream's key (secret). Required for the API path. | none |
| `models` | Comma-separated model IDs the mod answers for. Empty: every chat model the upstream lists. | empty |
| `imageModel` | API image model for `generate_image`. Empty: `gpt-image-2`, or the first `gpt-image*` the upstream lists. `none` disables the API image path. Codex uses its built-in image model independently of this setting. | empty |
| `contextWindow` | Input tokens assumed for a model whose window is unknown (minimum 32000). An explicit value overrides the Codex catalog window (see [Limitations](LIMITATIONS.md#codex-login-limitations)). | `272000` (API); catalog effective window or 128,000 (Codex) |
| `fallbackModel` | Model to switch to when a subscription or Codex login quota is reached; no account rotation, and the same account cannot be the fallback. Empty: off. | empty |
| `fallbackPercent` | Used share of a rate-limit window (50–100) at which the switch happens. Only read when `fallbackModel` is set. | `100` |
| `workerModel` | Model for the `model-mod:local-worker` agent type. Empty: the fallback model; if both are empty there is no worker type. | empty |
| `promptsDir` | Absolute directory with your own `compact.md`, `title.md`, `subagent-note.md` and `worker.md`. Empty: the plugin's `prompts/` directory. | empty |

### Codex login options

| Option | Format and default |
|---|---|
| `codexAccounts` | Comma-separated account names; empty by default. Each is 1–32 characters, starts with `[a-z0-9]`, and otherwise uses `[a-z0-9-]`. |
| `codexModels` | Comma-separated model names; empty by default. Each is 1–64 characters, starts with `[A-Za-z0-9]`, and otherwise uses `[A-Za-z0-9._-]`; names containing `claude` or `anthropic` are rejected, case-insensitively. |
| `codexAccountsDir` | Absolute directory; default `~/.config/model-mod/accounts`, or `%APPDATA%\model-mod\accounts` on Windows (unverified). Each account has a separate subdirectory. |
| `codexBin` | Executable name or absolute path; default `codex`. |
| `pythonBin` | Executable name or absolute path; default `python3`. On Windows use `python` (unverified). |
| `codexKeepReasoning` | `on` (default) or `off`; invalid values use `on` and appear in status. Uses experimental APIs; real Codex replay is unverified. |
| `codexServiceTier` | `default` (default) or `priority`; actual service tier and billing are unverified. |
| `codexWebSearch` | `on` (default) or `off`; invalid values use `on` and appear in status. Search is disabled when WebSearch is absent from the session tool list. |
| `codexStopGate` | `off` (default) or `on`, case-insensitive; invalid values use `off` and appear in status. On may start a read-only Codex review after a main-session turn, send the diff and full contents of untracked, non-ignored files to OpenAI and block ending. Gitignored files are not sent. |
| `codexStopGateBlocks` | Maximum blocks per session: `1` (default) or `2`; invalid values use `1` and appear in status. Once the limit is reached, an unpassed result allows ending with a human-review warning. |

Codex effort is clamped to levels declared by the model: `max` selects the highest supported level; an unsupported explicit level selects the highest supported level at or below it, or the lowest if none is lower. `minimal` is never sent. If no explicit level is given, the supported model default is used when needed.

`/model-mod:review --adversarial` supports focus text and effort; `--gate` requests a structured verdict. The Stop gate is configured independently through `codexStopGate` and `codexStopGateBlocks`; see [review gate](FEATURES.md#codex-review-gate).

Native search and openPage run at OpenAI and are not constrained by Claude permission domain rules (allowed or blocked domains); model-mod makes no `allowed_domains` security claim. Queries are sent to OpenAI.

Paths and commands cannot contain NUL or newline; a command name may contain only letters, digits, `.`, `_` and `-`. An account and a model form ID `<account>/<model>`, displayed as `<model> @ <account>`. Every account is paired with every configured model. When an API model has the same ID, Codex takes precedence. `/model-mod:setup` merges and deduplicates accounts but **replaces the entire** `codexModels` setting with the selected models for all accounts; reselect the complete desired model set when adding an account. `fallbackModel` and `workerModel` may refer to a valid Codex ID.

Advanced options are not shown in the dialog. Set them in the plugin's `options` object under `pluginConfigs` in your Claude Code settings (key `model-mod@model-mod`, or `model-mod@inline` when loaded with `--plugin-dir`). Keep the API key itself in the secret field.

| Advanced option | What it does | Default |
|---|---|---|
| `maxTokens` | Sent as `max_tokens`. | `32000` |
| `effortMode` | API path only: `suffix` sends `model(level)` for the effort level in use; `none` sends the plain model ID, for an upstream that rejects the suffix. | `suffix` |
| `sideModel` | Official model for Claude Code's own side requests while one of your models is selected. `none` leaves it alone; a value already in your environment wins. | `claude-haiku-5-5` |
| `keepThinking` | On the API path, hands Codex-style encrypted reasoning back within a tool loop. Set `false` for an upstream that does not accept it. | `true` |
| `localTitle` | Names the session from the first prompt through your upstream. `false` sends that prompt to the official `sideModel`. | `true` |
| `localContext` | Answers `/context` with Claude Code's local estimate. `false` asks the subscription endpoint to count tokens. | `true` |
| `toolSearch` | Defers large MCP tool schemas: `auto`, `on` or `off`. | `auto` |
| `toolSearchPercent` | Share of the model's context window (1–90) at which `auto` starts deferring. | `10` |

### Advanced: external configuration file

For scripts and test setups, the mod can read its settings from a JSON file instead of the plugin options. Set the environment variable `MODEL_MOD_CONFIG` to the file's absolute path before starting Claude Code. The plugin options take precedence: the file is read only when neither usable plugin-option upstream is configured, and an `apiKey` that cannot be used leaves the mod inactive instead of falling back to the file. The mod never reads credentials from Claude Code's own credential files.

Instead of `apiKey`, the file names a `headerFile`: a file of HTTP header lines for your upstream (the authorization line) that the mod hands to curl with `-H @file`. Only the file's path appears in process arguments; the key itself does not.

| Key | What it does |
|---|---|
| `baseUrl` (required) | Same meaning and checks as the `baseUrl` option. |
| `headerFile` (required) | Absolute path of the header file described above. |
| `models` (required) | Array of model IDs the mod answers for. `[]`: every chat model the upstream lists. |
| `maxTokens` (required) | Positive integer sent as `max_tokens`. |
| `toolsFile` | JSON file `{"tools": [{"name", "description", "input_schema"}]}` with Claude Code's built-in tools and their input schemas. Without it, the mod lists the tools with an open object schema. |
| `refresh` | Command run by `/model-mod:refresh` to rewrite `toolsFile`: an array of 4 to 64 strings whose first two items are absolute paths (the program and its script). Anything else is ignored. |
| `effortMode`, `imageModel`, `sideModel`, `keepThinking`, `localTitle`, `localContext`, `toolSearch`, `toolSearchPercent`, `promptsDir` | Same as the options of the same name. The defaults differ in the file: `effortMode` is `none` unless set to `suffix`, `imageModel` has no automatic choice (the API image path is off without it) and `sideModel` has no default. |
| `contextWindows` | Object mapping a model ID from `models` to its context window in tokens (32000 to 4000000). |

`contextWindow`, `fallbackModel`, `fallbackPercent` and `workerModel` are read only from the plugin options.

## Installation alternatives

To install from a local clone, use the clone's path instead of `chin-labs/model-mod`.

Use `/plugin configure model-mod@model-mod` in an interactive Claude Code session to configure the plugin. The shell command `claude plugin configure model-mod@model-mod` lists the options and which are unset; it does not open the interactive dialog.

To configure without the dialog, put your values in a private one-line JSON file outside the repository (for example `{"apiKey": "...", "baseUrl": "..."}`), then run:

```bash
chmod 600 /path/to/private-config.json
claude plugin configure model-mod@model-mod --values-stdin < /path/to/private-config.json
```

Never put a key in `--config` arguments (they can show up in process listings) or paste it into a message. In organization-managed Claude Code, personally installed plugins may not receive every hook unless the organization lists the plugin in its managed settings.

For example, a Codex-only `/model-mod:status` begins `model-mod: <version>: picker=active`, followed by account details. `rate-limits` supplies window percentages, reset times and credits; `account-info` supplies the plan when available.

Codex status shows remaining percentages, reset times, credits, plan and `ordinaryUsageAllowed`; unavailable fields are marked unavailable. Codex quota is checked at most once per account every five minutes, or immediately after a quota error; no automatic switch occurs without a future reset time. API upstreams have no official rateLimits and are not covered. Accounts are not rotated automatically; configure a `fallbackModel` on another upstream or account.

`codexServiceTier` is `default` (the default) or `priority`; invalid values use `default`. `priority` requires a supported Codex plan and may respond faster while consuming quota faster; actual tier and billing are unverified.

## Background job storage and limits

The SessionStart hook starts a local broker. After all sessions close, an idle broker can remain alive for up to 30 minutes. Up to 50 jobs are retained for seven days; when admitting job 51, the oldest terminal record and result are evicted first; if none is terminal, admission is refused; each account can have at most two running and five queued, with at most one active write job. Background execution has a 30-minute total and five-minute inactivity limit; foreground delegation has five-minute total and two-minute inactivity limits. Use `/model-mod:jobs --clear` to remove terminal jobs and results for the current workspace.

Job output is stored locally under `$XDG_STATE_HOME/model-mod/delegate/v1` (when unset, use the `state` directory inside the hidden `local` directory in the home directory) (directories 0700, files 0600). Results can contain your prompt or code fragments: redaction matches prompt or diff strings exactly only when they are at least 32 characters long, and cannot recognize model paraphrases. Local records are retained for seven days. Deleting local records does not delete Codex threads or provider-side records. Status records themselves do not store prompts, diffs, reasoning, account-directory paths, or environment variables.
