# Windows verification checklist

[繁體中文](WINDOWS.zh-TW.md) · [README](../README.md)

## Status

Windows is **not verified**. The following is a test checklist, not a claim of support. Use a disposable workspace and do not include tokens, credentials or conversation content in reports.

The Codex image path requires POSIX no-follow directory support. Background jobs use a Unix socket and are rejected on Windows; process-group handling also differs. Codex account paths and `CODEX_HOME` use Windows-specific forms, and streaming handles CRLF boundaries. These paths need real Windows verification.

## Steps

For each step, record the Claude Code, plugin, Python and Codex versions, the redacted `/model-mod:status` output and the expected and actual results. Never include tokens.

1. Install the plugin: expect it to appear in the plugin list; reload if hooks are not loaded.
2. Run `/model-mod:setup` and complete Codex device login: expect an account and model selection.
3. Run `/model-mod:model`: expect the configured Codex models in the picker.
4. Send one short message: expect a response from the selected model.
5. Run `/model-mod:review` in a disposable Git workspace: expect a read-only review result.
6. Run `/model-mod:rescue -- explain this workspace`: expect a read-only answer.
7. Try `/model-mod:jobs` and `/model-mod:cancel ID`: expect the Windows background-jobs refusal rather than a running job.
8. Request Codex image generation: expect `Image output requires POSIX no-follow directory support; use a supported platform.`
9. Check the SessionStart hook: `hooks/hooks.json` uses the POSIX `command -v`; verify its behavior in the Windows shell.
10. Run `/model-mod:status`: expect account and login information, with unavailable fields marked accordingly.
