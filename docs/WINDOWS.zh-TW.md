# Windows 驗證清單

[English](WINDOWS.md) · [README](../README.zh-TW.md)

## 狀態

Windows **尚未驗證**。以下是測試清單，不代表已宣稱支援。請使用可拋棄的工作區，回報時不要附上 token、憑證或對話內容。

Codex 圖片路徑需要 POSIX 不跟隨符號連結的目錄支援。背景工作使用 Unix socket，Windows 會拒絕；process group 處理也不同。Codex 帳號路徑及 `CODEX_HOME` 使用 Windows 專用形式，串流會處理 CRLF 邊界。這些路徑需要在真實 Windows 驗證。

## 步驟

每一步請記錄 Claude Code、插件、Python 與 Codex 版本、遮去敏感資訊的 `/model-mod:status` 輸出，以及預期和實際結果。絕不附上 token。

1. 安裝插件：預期插件出現在清單；若 hooks 未載入則重新載入。
2. 執行 `/model-mod:setup` 並完成 Codex 裝置登入：預期可選帳號與模型。
3. 執行 `/model-mod:model`：預期選單列出設定的 Codex 模型。
4. 傳送一則短訊息：預期所選模型回覆。
5. 在可拋棄的 Git 工作區執行 `/model-mod:review`：預期得到唯讀審查結果。
6. 執行 `/model-mod:rescue -- explain this workspace`：預期得到唯讀回答。
7. 嘗試 `/model-mod:jobs` 與 `/model-mod:cancel ID`：預期收到 Windows 背景工作拒絕訊息，而非啟動工作。
8. 要求 Codex 生成圖片：預期收到 `Image output requires POSIX no-follow directory support; use a supported platform.`
9. 檢查 SessionStart hook：`hooks/hooks.json` 使用 POSIX `command -v`；請驗證其在 Windows shell 的行為。
10. 執行 `/model-mod:status`：預期顯示帳號與登入資訊，無法取得的欄位標示為 unavailable。
