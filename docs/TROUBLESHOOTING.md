# Troubleshooting

[繁體中文](TROUBLESHOOTING.zh-TW.md) · [README](../README.md)

## Check that it works

After `/model-mod:setup`:

1. Run `/model-mod:status`. When the mod is active it answers with one line such as `model-mod <version>: picker=active; host=127.0.0.1; config=…; models=3; …`, where `models` is the number of models offered. `model-mod: inactive; …` means there is no usable key or URL (see Troubleshooting). If the reply is a text saying that the plugin hooks are not loaded, the plugin is not active in this session: run `/reload-plugins` or restart Claude Code.
2. Run `/model-mod:model`, pick one of your models and send a short message. The answer comes from your upstream. If the upstream is down or rejects the key, the turn ends with an error message; it is never retried on your subscription.

## Symptoms

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

Then restart Claude Code to apply the update. An update arrives only when the release has a new version (see the [changelog](../CHANGELOG.md)). Updating replaces the files in the installed plugin directory, so keep custom prompts in a directory set with `promptsDir`; your configuration is stored outside the plugin directory.

## Uninstall

1. Select a subscription model (for example `/model sonnet`). Claude Code saves interactive model choices as its default, so a saved local default would otherwise survive the uninstall.
2. Run `/plugin uninstall model-mod@model-mod` in a session, or `claude plugin uninstall model-mod@model-mod` in a shell, then restart. Claude Code leaves the plugin cache in place.
