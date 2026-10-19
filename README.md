# model-mod

Use your own API models in Claude Code.

[![Version](https://img.shields.io/github/v/release/chin-labs/model-mod)](https://github.com/chin-labs/model-mod/releases)
[![License](https://img.shields.io/github/license/chin-labs/model-mod)](LICENSE)
[![Claude Code plugin](https://img.shields.io/badge/Claude_Code-plugin-gray)](https://code.claude.com/docs/en/plugins)

[繁體中文](README.zh-TW.md)

model-mod is a plugin (a "mod") for Claude Code that puts models from your own Messages-compatible API alongside the built-in models—for example, CLIProxyAPI with your own Codex login. Pick one with `/model-mod:model` to route that session to your upstream; use `/model` to go back to a subscription model. Subscription models, `ANTHROPIC_BASE_URL` and Remote Control keep Claude Code's normal connection.

## Requirements

- Claude Code with mod support, tested on **Claude Code 2.1.299 to 2.1.301**; other versions are untested.
- Your own running Messages-compatible upstream and its API key. CLIProxyAPI is the tested upstream; model-mod does not install or run it.
- `curl` and `bash`; web fetch and image generation need additional system tools listed in [Configuration](docs/CONFIGURATION.md#set-up-your-upstream-first).

## Quick start

[Prepare your upstream](docs/CONFIGURATION.md#set-up-your-upstream-first) first, then run these in an interactive Claude Code session:

```text
/plugin marketplace add chin-labs/model-mod
/plugin install model-mod@model-mod
/plugin configure model-mod@model-mod
/model-mod:setup
/model-mod:model
```

Enter your upstream API key in the configuration dialog; it is stored as a secret and never typed into chat. `/model-mod:setup` confirms the upstream URL and lets you choose models; `/model-mod:model` lists them. If the plugin is not active after configuring, run `/reload-plugins` or restart Claude Code.

Alternatively, add and install from a shell:

```bash
claude plugin marketplace add chin-labs/model-mod
claude plugin install model-mod@model-mod
claude plugin configure model-mod@model-mod
```

The last shell command lists options and which are unset; use `/plugin configure model-mod@model-mod` in Claude Code to edit them, or [configure from a private file](docs/CONFIGURATION.md#installation-alternatives). To install from a local clone, use its path instead of `chin-labs/model-mod`.

Run `/model-mod:status` to check activation, then select your model and send a short message. An upstream failure ends the turn with an error; it is never retried through your subscription.

## Features

- Your models alongside subscription models, switched per session with `/model-mod:model`.
- Streaming, tool calls, Skills, MCP servers, subagents and Workflow agents.
- Web search, web fetch, image generation and tool search for your models.
- Automatic retry of transient upstream errors and Claude Code's five effort levels.
- Compaction through your selected model and optional automatic switching at your subscription's usage limit.

## Commands

| Command | What it does |
|---|---|
| `/model-mod:setup` | Confirm the upstream URL and choose the models to offer. Cancelling changes nothing. |
| `/model-mod:model` | List your models and switch to the one you pick (↑↓ to move, Enter to select, Esc to close). On a short terminal, Remote Control or mobile, a paged menu is used instead. |
| `/model-mod:refresh` | Re-read the prompts and the upstream's model list. |
| `/model-mod:status` | Show whether the mod is active, how many models it offers and how its tools are set up. |
| `/model` | Claude Code's own command, unchanged: subscription models. Typing one of your model IDs (`/model <id>`) also works. |
| `/btw <question>` | With one of your models selected, answered through your upstream with read-only context and no tools. |

## Documentation

- [Configuration](docs/CONFIGURATION.md): upstream setup, every option and default, external configuration files and `--values-stdin`.
- [How it works](docs/HOW-IT-WORKS.md): routing, custom prompts, development and security reporting.
- [What your models can do](docs/FEATURES.md): streaming, tools, agents, effort, compaction and automatic switching.
- [Troubleshooting](docs/TROUBLESHOOTING.md): activation checks, common errors, updates and uninstalling.

## Limitations, privacy and compliance

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
