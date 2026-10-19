# model-mod

[繁體中文](README.zh-TW.md)

model-mod is a plugin (a "mod") for Claude Code. It adds the models of your own Messages-compatible API, such as CLIProxyAPI with your own Codex login, next to Claude Code's built-in models. Pick one of your models from `/model-mod:model` and the session talks to your upstream; pick a subscription model with Claude Code's normal `/model` and nothing changes.

## Features

- Your models alongside the subscription models, switched per session with `/model-mod:model`.
- Subscription models, `ANTHROPIC_BASE_URL` and Remote Control stay on Claude Code's normal connection.
- Streaming, tool calls, Skills, MCP servers, subagents and Workflow agents work with your models.
- Web search, web fetch, image generation and tool search for your models.
- Automatic retry of transient upstream errors, and Claude Code's five effort levels.
- Optional automatic switch to one of your models when your subscription's usage limit is reached.

## Requirements

- Claude Code with mod support. Tested on Claude Code 2.1.299 to 2.1.301; other versions are untested. See [Limitations](docs/LIMITATIONS.md#tested-versions).
- Your own upstream that offers a Messages-compatible streaming API at `/v1/messages`, and its API key. CLIProxyAPI is the tested upstream. A `/v1/models` list lets setup discover models; without it you enter model IDs by hand.
- `curl` and `bash`. Web fetch also needs `uname` and a system resolver (`getent` on Linux, `dscacheutil` on macOS); image generation also needs `sed`, `grep`, `tr`, `mktemp` and `base64`.

## Set up your upstream first

model-mod has no models of its own. It sends a session to an *upstream*: a server that accepts Messages-style streaming requests at `/v1/messages` and checks an API key. Before you install:

1. **Get an upstream.** CLIProxyAPI is the tested one. Install it and sign in to your own provider account as its documentation describes; model-mod does not install, start or configure it.
2. **Make sure it is running** and reachable from the machine where you run Claude Code. This check reads the same model list that `/model-mod:setup` uses (replace the address and set the key in your shell first); `200` means the address and key work:

   ```bash
   printf 'header = "Authorization: Bearer %s"\n' "$UPSTREAM_API_KEY" | curl -s -o /dev/null -w '%{http_code}\n' -K - http://127.0.0.1:8317/v1/models
   ```

3. **Find the two values the mod needs.** `baseUrl` is the server's address without `/v1`; CLIProxyAPI listens on port 8317 by default, which is why the default `baseUrl` is `http://127.0.0.1:8317`. If your upstream runs elsewhere, enter its address when you configure. `apiKey` is a key your upstream accepts from clients (for CLIProxyAPI, one defined in its own configuration), never a key of the client's subscription.

## Install

Run the first three lines in a shell and the last two in an interactive Claude Code session. Enter your upstream API key in the configuration dialog; it is stored as a secret and never typed into chat.

```text
claude plugin marketplace add chin-labs/model-mod
claude plugin install model-mod@model-mod
claude plugin configure model-mod@model-mod
/model-mod:setup
/model-mod:model
```

`/model-mod:setup` confirms the upstream URL and lets you choose which models to offer. `/model-mod:model` then lists them. If the plugin is not active after configuring, run `/reload-plugins` or restart Claude Code.

To install from a local clone, use the clone's path instead of `chin-labs/model-mod`.

To configure without the dialog, put your values in a private one-line JSON file outside the repository (for example `{"apiKey": "...", "baseUrl": "..."}`), then run:

```bash
chmod 600 /path/to/private-config.json
claude plugin configure model-mod@model-mod --values-stdin < /path/to/private-config.json
```

Never put a key in `--config` arguments (they can show up in process listings) or paste it into a message. In organization-managed Claude Code, personally installed plugins may not receive every hook unless the organization lists the plugin in its managed settings.

## Check that it works

After `/model-mod:setup`:

1. Run `/model-mod:status`. When the mod is active it answers with one line such as `model-mod <version>: picker=active; host=127.0.0.1; config=…; models=3; …`, where `models` is the number of models offered. `model-mod: inactive; …` means there is no usable key or URL (see Troubleshooting). If the reply is a text saying that the plugin hooks are not loaded, the plugin is not active in this session: run `/reload-plugins` or restart Claude Code.
2. Run `/model-mod:model`, pick one of your models and send a short message. The answer comes from your upstream. If the upstream is down or rejects the key, the turn ends with an error message; it is never retried on your subscription.

## Configuration

These options appear in the configuration dialog (`claude plugin configure model-mod@model-mod`).

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

## Commands

| Command | What it does |
|---|---|
| `/model-mod:setup` | Confirm the upstream URL and choose the models to offer. Cancelling changes nothing. |
| `/model-mod:model` | List your models and switch to the one you pick (↑↓ to move, Enter to select, Esc to close). On a short terminal, Remote Control or mobile, a paged menu is used instead. |
| `/model-mod:refresh` | Re-read the prompts and the upstream's model list. |
| `/model-mod:status` | Show whether the mod is active, how many models it offers and how its tools are set up. |
| `/model` | Claude Code's own command, unchanged: subscription models. Typing one of your model IDs (`/model <id>`) also works. |
| `/btw <question>` | With one of your models selected, answered through your upstream with read-only context and no tools. |

To go back to a subscription model, use `/model`.

## How it works

The mod answers turns only for the model IDs it owns. With `models` set, those IDs are the owned set; otherwise it is the upstream's chat models. IDs containing `claude` or `anthropic` and Claude Code's official aliases are never owned, and image, embedding, speech and moderation models are left out of discovery. Every other model uses Claude Code's normal path.

For an owned model, turns, compaction and `/btw` go to your upstream and **never fall back to the subscription**: if the upstream fails, the turn ends with an error message.

## What your models can do

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

`web_search`, `web_fetch`, `generate_image` and `tool_search` exist only for your models; with a subscription model selected, use Claude Code's built-in tools. They follow Claude Code's permission rules. How a model behaves is up to the model; this plugin does not make it equal to a subscription model.

### Custom prompts

The prompts for compaction, titles, subagents and the worker live in `compact.md`, `title.md`, `subagent-note.md` and `worker.md` in the plugin's `prompts/` directory. Set `promptsDir` to use your own copies (files in the plugin directory are replaced on upgrade). There is no built-in fallback: a missing, empty, unreadable or over-8000-character file counts as unavailable. Without `compact.md`, local compaction is skipped; without `title.md`, the first 50 characters of the prompt become the title; without `worker.md`, there is no worker agent type. `/model-mod:refresh` re-reads the files.

## Troubleshooting

| Symptom | Likely cause | What to do |
|---|---|---|
| Status shows `inactive`, or no models are listed | No key, a refused URL, or the plugin is not loaded | Configure the key and a permitted URL, run `/reload-plugins`, then `/model-mod:setup`. |
| Model-list error during setup | Network, authentication or server problem | Check the upstream and key. Setting `models` explicitly lets you proceed without discovery. |
| `model is not in the allowlist` | The ID is outside `models` | Choose an allowed ID or update the list. |
| Errors after selecting a model | Model unavailable, upstream down or key rejected | Fix the upstream, model or key, then `/model-mod:refresh`. There is no subscription fallback. |
| Effort suffix rejected | The upstream does not understand `model(level)` | Set the advanced option `effortMode` to `none`. |
| Image tool missing or refused | No image model, or no model of yours selected | Set `imageModel` and select one of your models. |
| `web_fetch` refuses a URL | Not HTTP(S), or a private destination | Use a public HTTP(S) URL. |
| Compacts too early, or long input is rejected | The assumed window differs from the model's real one | Adjust `contextWindow`. |
| Actions blocked in auto permission mode although the upstream works | The classifier runs on your subscription and failed | Use default or acceptEdits mode with allow rules. |
| Claude Code starts on an unusable model after uninstalling | Claude Code saved your last model selection | Run `/model sonnet`, or remove the saved `model` entry from your settings. |

## Update

```bash
claude plugin marketplace update
claude plugin update model-mod@model-mod
```

Then restart Claude Code to apply the update. An update arrives only when the release has a new version (see the [changelog](CHANGELOG.md)). Updating replaces the files in the installed plugin directory, so keep custom prompts in a directory set with `promptsDir`; your configuration is stored outside the plugin directory.

## Uninstall

1. Select a subscription model (for example `/model sonnet`). Claude Code saves interactive model choices as its default, so a saved local default would otherwise survive the uninstall.
2. Run `/plugin uninstall model-mod@model-mod` in a session, or `claude plugin uninstall model-mod@model-mod` in a shell, then restart. Claude Code leaves the plugin cache in place.

## Limitations, privacy and compliance

- [Limitations](docs/LIMITATIONS.md) lists known differences from a subscription model, what has not been verified, and which Claude Code requests can still reach your subscription.
- Messages, system instructions (including project instruction files), tool definitions and results, and images are sent to your upstream and any provider behind it. Search queries go to the upstream, fetch URLs to the target sites, image prompts to the image endpoint.
- The mod uses plugin hooks, changes no Claude Code binary, intercepts no TLS, reads no subscription credential files and never sends subscription credentials to your upstream. It uses only the upstream key you configure and never retries one of your model's turns through the subscription.
- Auto permission mode sends the full conversation and project instructions to your subscription for classification, even while one of your models is selected. Default or acceptEdits mode with allow rules avoids that. Other requests Claude Code makes by itself can also use your subscription; see [Subscription side requests](docs/LIMITATIONS.md#subscription-side-requests).
- The key is passed to curl through the environment, not as a command argument. It is removed from error text, but streamed output is not rewritten, so use an upstream you trust.

This is an independent project, not affiliated with or endorsed by Anthropic or OpenAI. The [compliance notes](docs/COMPLIANCE.md) explain the design limits and point to the current terms for you to read. They do not grant permission under those terms; you are responsible for reading them.

## Development

```bash
claude plugin validate .
claude plugin test .
```

The source imports a module provided by Claude Code, so type-checking and tests need Claude Code with mod support. Tests use fake credentials. To try a working copy, start Claude Code with `--plugin-dir .`. Do not redistribute Claude Code's generated API declarations or any credentials.

## Issues and security

- Bugs and questions: [GitHub Issues](https://github.com/chin-labs/model-mod/issues). Pull requests are welcome, but there is no guaranteed response time.
- Pull requests: accepted changes are integrated upstream and published as release snapshots. This repository's `main` branch only receives release snapshots, so a pull request may be closed with a reference to the commit that includes the change instead of being merged here.
- Security problems: use GitHub's private vulnerability reporting (the repository's Security tab → Report a vulnerability). Do not post exploit details in a public issue.
- Never include keys, subscription credentials, unredacted transcripts, private paths or internal endpoints in a report. Include Claude Code and plugin versions, a minimal reproduction using fake credentials, and the expected versus actual behavior.

## Community references

These two links are included for background context only and have not been verified by this project. They do not grant permission; the terms you use this under remain the current terms that you read yourself.

- https://x.com/thsottiaux/status/2076119366647894371
- https://x.com/thsottiaux/status/2093573575869698091

## License

[MIT](LICENSE).
