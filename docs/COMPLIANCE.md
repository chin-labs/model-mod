# Compliance notes

[繁體中文](COMPLIANCE.zh-TW.md)

model-mod is a plugin for Claude Code. This is an independent project, not affiliated with or endorsed by Anthropic or OpenAI. This page describes how the plugin is built to stay within its own limits. It does not claim that the terms of any provider authorize this use, and it says nothing about how an account will be treated. **No permission for this use has been obtained by this project.** You are responsible for reading the terms that apply to you.

## What the plugin does and does not do

| Rule | In practice |
|---|---|
| Unmodified Claude Code | Works through plugin hooks. It does not modify the Claude Code binary or intercept TLS. |
| No endpoint replacement | Never sets `ANTHROPIC_BASE_URL`. Subscription models and Remote Control keep Claude Code's own connection. Only your own model IDs are prepared, through the session's `ANTHROPIC_CUSTOM_MODEL_OPTION`. |
| No subscription credentials | Does not read credential files, keychains or subscription tokens, does not request session authorization and does not forward authenticated Claude Code requests. Settings come from the plugin options, which Claude Code hands to the plugin, or from an optional configuration file that you point to with `MODEL_MOD_CONFIG`. Credentials are never read from Claude Code's credential files. |
| Your upstream key only | Sends only the upstream key you provide. From the plugin options it is passed to curl through the process environment and a curl configuration, not as a command argument; with a configuration file, the key stays in the header file that curl reads, and only that file's path is an argument. |
| No subscription upstreams | Refuses upstream hosts under `anthropic.com` and `claude.ai`, including subdomains, and URLs with credentials, queries or fragments. |
| Your model IDs only | Handles the models you selected or the upstream lists, plus a valid worker or fallback model. IDs containing `claude` or `anthropic` and Claude Code's official aliases are never handled. Every other model goes through Claude Code as usual. |
| No fallback | If a turn or `/btw` on one of your models fails, it ends with an error message. It is never retried through the subscription, and a failed local compaction never uses a subscription summary. |
| No identity spoofing | Responses report the actual local model ID and are never relabeled as a subscription model. |
| No direct settings writes | Setup and refresh use Claude Code's configuration API, not the settings files. Claude Code itself may keep your configuration and your last model choice. |

The optional usage-limit switch is off by default. It only changes which model later messages use, switching back after the reported reset. It does not resend the turn that hit the limit or reset any limit.

## What leaves your machine

Requests to your models send the conversation, system instructions, tool definitions and results, and images to your upstream and any provider behind it. They do not include Claude Code session or user identity metadata, or subscription authorization headers. Web fetch contacts the website you ask for; image generation and search use your upstream.

Some requests Claude Code makes on its own can still use your subscription connection: auto permission classification, `/rename` without a name, `Agent(model: 'haiku')`, the native WebFetch summarizer, `/context` token counts with `localContext: false`, and first-prompt titles with `localTitle: false`. They are listed in [Subscription side requests](LIMITATIONS.md#subscription-side-requests), which covers the paths that were checked, not every possible Claude Code request. The [README](../README.md) explains key handling and how to recover from a saved default model.

## Your upstream's terms

model-mod does not provide or run an upstream; you hold its key. The supported upstream is **CLIProxyAPI with a Codex account you log in to yourself**. Do not connect Claude accounts or other unsupported third-party accounts to a third-party upstream. A compatible protocol or a working test does not mean any provider's terms allow this. Before using or sharing the plugin, read the current terms that apply to Claude Code, your upstream and your accounts. Do not use model-mod to get around usage limits, to resell or share an account, or to train models on subscription output.

## Check it yourself

From a clone of the repository:

```bash
claude plugin validate .
claude plugin test .
```

Validation lists the plugin's hooks and declared capabilities. The tests use fake credentials and cover which models are handled, rejected configuration and the no-fallback rule. Read `hooks/register.ts` to see how the endpoint, key and routing are handled. Neither check shows legal compliance or covers every request Claude Code makes.

## Read the terms

Read Claude Code's [legal and compliance documentation](https://code.claude.com/docs/en/legal-and-compliance), the [Consumer Terms](https://www.anthropic.com/legal/consumer-terms) and any terms that apply to your upstream. This page does not reproduce or interpret them, and they can change, so check them again from time to time.
