# How it works

[繁體中文](HOW-IT-WORKS.zh-TW.md) · [README](../README.md)

The mod answers turns only for the model IDs it owns. For the API path, `models` selects IDs or, when empty, the upstream's chat models. Codex IDs come from the configured accounts and models. IDs containing `claude` or `anthropic` and Claude Code's official aliases are never owned, and image, embedding, speech and moderation models are left out of discovery. Every other model uses Claude Code's normal path.

For an owned model, turns, compaction and `/btw` go to the configured API upstream or Codex login and **never fall back to the subscription**: if the upstream fails, the turn ends with an error message.

## Codex login data flow

```text
client hook -> local Python helper -> codex app-server -> your officially logged-in Codex account
```

The hook sends the Messages request body to the helper on stdin. The helper translates it for app-server and returns Messages SSE on stdout (or JSON for non-streaming calls). Each step starts fresh processes. When app-server requests a client tool, the helper interrupts the turn and returns a `tool_use`; after the client runs the tool, a later step creates a new thread and reconstructs conversation and tool-result history before continuing. The official CLI, signed in with your own account, sends conversation content to OpenAI services and manages its own login; model-mod does not read, copy or forward its credentials. Codex models do not offer `generate_image` or `web_search`. See [Codex login limitations](LIMITATIONS.md#codex-login-limitations) for the soft-isolation boundary.

## Custom prompts

The prompts for compaction, titles, subagents and the worker live in `compact.md`, `title.md`, `subagent-note.md` and `worker.md` in the plugin's `prompts/` directory. Set `promptsDir` to use your own copies (files in the plugin directory are replaced on upgrade). There is no built-in fallback: a missing, empty, unreadable or over-8000-character file counts as unavailable. Without `compact.md`, local compaction is skipped; without `title.md`, the first 50 characters of the prompt become the title; without `worker.md`, there is no worker agent type. `/model-mod:refresh` re-reads the files.

## Limitations, privacy and compliance

- [Limitations](LIMITATIONS.md) lists known differences from a subscription model, what has not been verified, and which Claude Code requests can still reach your subscription.
- On the API path, messages, system instructions (including project instruction files), tool definitions and results, and images are sent to your upstream and any provider behind it. Codex conversations go through the official Codex CLI to OpenAI services. On the API path, search queries go to the upstream and image prompts to the image endpoint; fetch URLs go to the target sites.
- The mod uses plugin hooks, changes no Claude Code binary, intercepts no TLS, reads no subscription credential files and never sends subscription credentials to your upstream. On the API path it uses only the upstream key you configure and never retries one of your model's turns through the subscription. A failed or stalled request is retried only against the same model; the mod never switches to another model because a request failed.
- Auto permission mode sends the full conversation and project instructions to your subscription for classification, even while one of your models is selected. Default or acceptEdits mode with allow rules avoids that. Other requests Claude Code makes by itself can also use your subscription; see [Subscription side requests](LIMITATIONS.md#subscription-side-requests).
- On the API path, the key is passed to curl through the environment, not as a command argument. It is removed from error text, but streamed output is not rewritten, so use an upstream you trust.

This is an independent project, not affiliated with or endorsed by Anthropic or OpenAI. The [compliance notes](COMPLIANCE.md) explain the design limits and point to the current terms for you to read. They do not grant permission under those terms; you are responsible for reading them.

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
