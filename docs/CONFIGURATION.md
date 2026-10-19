# Configuration

[繁體中文](CONFIGURATION.zh-TW.md) · [README](../README.md)

## Set up your upstream first

Your own upstream must offer a Messages-compatible streaming API at `/v1/messages`, and you need its API key. CLIProxyAPI is the tested upstream. A `/v1/models` list lets setup discover models; without it you enter model IDs by hand.

model-mod has no models of its own. It sends a session to an *upstream*: a server that accepts Messages-style streaming requests at `/v1/messages` and checks an API key. Before you install:

1. **Get an upstream.** CLIProxyAPI is the tested one. Install it and sign in to your own provider account as its documentation describes; model-mod does not install, start or configure it.
2. **Make sure it is running** and reachable from the machine where you run Claude Code. This check reads the same model list that `/model-mod:setup` uses (replace the address and set the key in your shell first); `200` means the address and key work:

   ```bash
   printf 'header = "Authorization: Bearer %s"\n' "$UPSTREAM_API_KEY" | curl -s -o /dev/null -w '%{http_code}\n' -K - http://127.0.0.1:8317/v1/models
   ```

3. **Find the two values the mod needs.** `baseUrl` is the server's address without `/v1`; CLIProxyAPI listens on port 8317 by default, which is why the default `baseUrl` is `http://127.0.0.1:8317`. If your upstream runs elsewhere, enter its address when you configure. `apiKey` is a key your upstream accepts from clients (for CLIProxyAPI, one defined in its own configuration), never a key of Claude Code's subscription.

## System tools

`curl` and `bash` are required. Web fetch also needs `uname` and a system resolver (`getent` on Linux, `dscacheutil` on macOS); image generation also needs `sed`, `grep`, `tr`, `mktemp` and `base64`.

## Plugin options

These options appear in the configuration dialog (`/plugin configure model-mod@model-mod`).

Only `apiKey` and `baseUrl` are essential: without a key the mod stays inactive, and `baseUrl` needs changing unless your upstream listens at its default address. Every other option is optional.

| Option | What it does | Default |
|---|---|---|
| `baseUrl` | Base URL of your upstream, without `/v1`. HTTP or HTTPS only; URLs with credentials, queries or fragments, and `anthropic.com` or `claude.ai` hosts, are refused. | `http://127.0.0.1:8317` |
| `apiKey` | Your upstream's API key (secret). Without it the mod stays inactive. | none |
| `models` | Comma-separated model IDs the mod answers for. Empty: every chat model the upstream lists. | empty |
| `imageModel` | Model for `generate_image`. Empty: `gpt-image-2`, or the first `gpt-image*` the upstream lists. `none` turns the tool off. | empty |
| `contextWindow` | Input tokens assumed for a model whose window is unknown (minimum 32000). | `272000` |
| `fallbackModel` | One of your models to switch to when the subscription limit is reached. Empty: no automatic switch. | empty |
| `fallbackPercent` | Used share of a rate-limit window (50–100) at which the switch happens. Only read when `fallbackModel` is set. | `100` |
| `workerModel` | Model for the `model-mod:local-worker` agent type. Empty: the fallback model; if both are empty there is no worker type. | empty |
| `promptsDir` | Absolute directory with your own `compact.md`, `title.md`, `subagent-note.md` and `worker.md`. Empty: the plugin's `prompts/` directory. | empty |

Advanced options are not shown in the dialog. Set them in the plugin's `options` object under `pluginConfigs` in your Claude Code settings (key `model-mod@model-mod`, or `model-mod@inline` when loaded with `--plugin-dir`). Keep the API key itself in the secret field.

| Advanced option | What it does | Default |
|---|---|---|
| `maxTokens` | Sent as `max_tokens`. | `32000` |
| `effortMode` | `suffix` sends `model(level)` for the effort level in use; `none` sends the plain model ID, for an upstream that rejects the suffix. | `suffix` |
| `sideModel` | Official model for Claude Code's own side requests while one of your models is selected. `none` leaves it alone; a value already in your environment wins. | `claude-haiku-5-5` |
| `keepThinking` | Hands Codex-style encrypted reasoning back within a tool loop. Set `false` for an upstream that does not accept it. | `true` |
| `localTitle` | Names the session from the first prompt through your upstream. `false` sends that prompt to the official `sideModel`. | `true` |
| `localContext` | Answers `/context` with Claude Code's local estimate. `false` asks the subscription endpoint to count tokens. | `true` |
| `toolSearch` | Defers large MCP tool schemas: `auto`, `on` or `off`. | `auto` |
| `toolSearchPercent` | Share of the model's context window (1–90) at which `auto` starts deferring. | `10` |

### Advanced: external configuration file

For scripts and test setups, the mod can read its settings from a JSON file instead of the plugin options. Set the environment variable `MODEL_MOD_CONFIG` to the file's absolute path before starting Claude Code. The plugin options take precedence: the file is read only when `apiKey` is not set in them, and an `apiKey` that cannot be used leaves the mod inactive instead of falling back to the file. The mod never reads credentials from Claude Code's own credential files.

Instead of `apiKey`, the file names a `headerFile`: a file of HTTP header lines for your upstream (the authorization line) that the mod hands to curl with `-H @file`. Only the file's path appears in process arguments; the key itself does not.

| Key | What it does |
|---|---|
| `baseUrl` (required) | Same meaning and checks as the `baseUrl` option. |
| `headerFile` (required) | Absolute path of the header file described above. |
| `models` (required) | Array of model IDs the mod answers for. `[]`: every chat model the upstream lists. |
| `maxTokens` (required) | Positive integer sent as `max_tokens`. |
| `toolsFile` | JSON file `{"tools": [{"name", "description", "input_schema"}]}` with Claude Code's built-in tools and their input schemas. Without it, the mod lists the tools with an open object schema. |
| `refresh` | Command run by `/model-mod:refresh` to rewrite `toolsFile`: an array of 4 to 64 strings whose first two items are absolute paths (the program and its script). Anything else is ignored. |
| `effortMode`, `imageModel`, `sideModel`, `keepThinking`, `localTitle`, `localContext`, `toolSearch`, `toolSearchPercent`, `promptsDir` | Same as the options of the same name. The defaults differ in the file: `effortMode` is `none` unless set to `suffix`, `imageModel` has no automatic choice (the tool is off without it) and `sideModel` has no default. |
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
