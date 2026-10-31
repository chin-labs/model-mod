# model-mod

Use your own Codex login or API models in Claude Code.

[![Version](https://img.shields.io/github/v/release/chin-labs/model-mod)](https://github.com/chin-labs/model-mod/releases)
[![License](https://img.shields.io/github/license/chin-labs/model-mod)](LICENSE)
[![Claude Code plugin](https://img.shields.io/badge/Claude_Code-plugin-gray)](https://code.claude.com/docs/en/plugins)

[繁體中文](README.zh-TW.md)

model-mod is a plugin (a "mod") for Claude Code that puts models from your own Codex login or Messages-compatible API alongside the built-in models. Both upstreams can be configured together. Pick one with `/model-mod:model` to route that session to your upstream; use `/model` to go back to a subscription model. Subscription models, `ANTHROPIC_BASE_URL` and Remote Control keep Claude Code's normal connection.

## Requirements

- Claude Code with mod support: Codex login and the API upstream were tested on **Claude Code 2.1.314**; the API upstream was also tested on 2.1.299 to 2.1.310. A manual end-to-end check on one Mac used 2.1.316 with Codex 0.166.0. Other versions are untested.
- Codex login: Python 3.9 or newer and an installed `codex` CLI (minimum supported version 0.165.0; lower versions are refused). The Codex context window comes from the account's model catalog (effective percentage applied), falling back to 128,000 tokens; `contextWindow` overrides it. Or use your own running Messages-compatible API and its API key; CLIProxyAPI is one tested API upstream example. model-mod does not install or run the API server.
- `curl` and `bash`; web fetch and image generation need additional system tools listed in [Configuration](docs/CONFIGURATION.md#system-tools).

## Quick start

Codex login is the main path. Install Python 3.9+ and the official `codex` CLI, then in an interactive Claude Code session run:

```text
/plugin marketplace add chin-labs/model-mod
/plugin install model-mod@model-mod
```

If `/model-mod:setup` does not respond or reports that hooks are not loaded, run `/reload-plugins` first. Then run:

```text
/model-mod:setup
/model-mod:model
```

Choose **Codex login**, select an account and, if prompted, open the displayed link, enter the one-time code and select **Continue (after logging in)**. Choose models. Setup creates the account directory and writes the account and model settings; `/plugin configure` is not needed for this path. The code expires after about 15 minutes. See [Troubleshooting](docs/TROUBLESHOOTING.md) for manual login.

Alternatively, if you already have a [Messages-compatible API server](docs/CONFIGURATION.md#set-up-your-upstream-first), use `/plugin configure model-mod@model-mod` to set `baseUrl` and `apiKey` before `/model-mod:setup`, then choose **Compatible API server**. The key is stored as a secret, not typed into chat. Both upstreams can coexist. For a local clone or private configuration file, see [installation alternatives](docs/CONFIGURATION.md#installation-alternatives).

First checks:

- Hooks not loaded: run `/reload-plugins` or restart Claude Code.
- Not logged in: rerun `/model-mod:setup` and complete device login, or follow the terminal login command in the error.
- `codex` not on `PATH`: install the official CLI or configure `codexBin`, then retry setup.
- `model-mod: Codex login: device code expired; run /model-mod:setup again to get a new code.`: rerun setup.
- `model-mod: no local models. Run /model-mod:setup to add them.`: run setup and select models; use `/model-mod:status` to check activation.

Send a short message after selecting a model. An upstream failure ends the turn with an error; it is never retried through your subscription.

## Features

- Your models alongside subscription models, switched per session with `/model-mod:model`.
- Streaming, tool calls, Skills, MCP servers, subagents and Workflow agents.
- Codex login uses native web search (`codexWebSearch`) and image generation on POSIX; the API path uses the mod’s search, fetch and image-generation tools. Web fetch and tool search are also available to Codex.
- Automatic retry of transient upstream errors with bounded `Retry-After` handling, and Claude Code's five effort levels.
- Compaction through your selected model and optional `fallbackModel` switching at subscription or Codex login rate limits; accounts are not rotated automatically, and API upstream models have no official rate-limit switching.

## Commands

| Command | What it does |
|---|---|
| `/model-mod:setup` | Configure an upstream and select models, or manage configured upstreams. In the terminal the fixed menus open in one pane; Esc or cancelling leaves the configuration unchanged. |
| `/model-mod:model` | List your models and switch to the one you pick (↑↓ to move, Enter to select, Esc to close). On a short terminal, Remote Control or mobile, a paged menu is used instead. |
| `/model-mod:refresh` | Reload prompts and check Codex login status, CLI version and quota. If a schema-refresh command is configured, run it to refresh tool schemas (Codex status is not displayed in that branch); otherwise display Codex status and refresh the API model list when an API key is configured. Changed options need `/reload-plugins`. |
| `/model-mod:status` | Show Codex quota per account (usage bars with reset times), the current model path and grouped diagnostics: activation, model count, tool setup and settings. Loopback hostnames are shown; other hosts appear as `host=remote`. Warns when plain HTTP sends the API key unencrypted to a non-loopback host. |
| `/model-mod:review` | Review changes with Codex; `--gate` requests a structured verdict, `--adversarial` reviews a diff, and `--background` starts a job. |
| `/model-mod:rescue` | Ask Codex for help; `--write` requests workspace write access and `--background` starts a job. |
| `/model-mod:jobs` | List or clear background jobs. |
| `/model-mod:result` | Read a job result by ID. |
| `/model-mod:cancel` | Cancel a job by ID. |
| `/model-mod:transfer` | Import the current session to Codex after confirmation. |
| `/model` | Claude Code's own command, unchanged: subscription models. Typing one of your model IDs (`/model <id>`) also works. |
| `/btw <question>` | With one of your models selected, answered through your upstream with read-only context and no tools. |

## Documentation

- [Configuration](docs/CONFIGURATION.md): upstream setup, every option and default, external configuration files and `--values-stdin`.
- [How it works](docs/HOW-IT-WORKS.md): routing, custom prompts, development and security reporting.
- [What your models can do](docs/FEATURES.md): streaming, tools, agents, effort, compaction and automatic switching.
- [Troubleshooting](docs/TROUBLESHOOTING.md): activation checks, common errors, updates and uninstalling.

## Limitations, privacy and compliance

- [Windows checklist](docs/WINDOWS.md) covers the unverified platform.
- [Limitations](docs/LIMITATIONS.md) lists known differences, unverified behavior and [subscription side requests](docs/LIMITATIONS.md#subscription-side-requests).
- Conversations, system instructions (including project instructions), tool definitions and results, and images go to your upstream and any provider behind it. Search queries, fetch URLs and image prompts go to their respective destinations.
- Auto permission mode sends the full conversation and project instructions to your subscription for classification, even on your models. Default or acceptEdits mode with allow rules avoids that; other side requests can still use your subscription.
- The mod uses plugin hooks: it does not modify the Claude Code binary, intercept TLS, read subscription credential files or send subscription credentials to your upstream. Use an upstream you trust; streamed output is not rewritten to mask keys.

This is an independent project, not affiliated with or endorsed by Anthropic or OpenAI. The [compliance notes](docs/COMPLIANCE.md) describe design limits and link to current terms; they do not grant permission. You are responsible for reading the terms that apply to you.

## Development

```bash
claude plugin validate .
claude plugin test .
```

Tests use fake credentials and need Claude Code with mod support. See [development notes](docs/HOW-IT-WORKS.md#development) for trying a working copy.

## Issues and security

[Bugs and questions](https://github.com/chin-labs/model-mod/issues) and pull requests are welcome; there is no guaranteed response time. Report vulnerabilities privately through the repository's Security tab, never in a public issue. See [reporting guidelines](docs/HOW-IT-WORKS.md#issues-and-security); do not include keys, subscription credentials, private paths or internal endpoints.

## License

[MIT](LICENSE).
