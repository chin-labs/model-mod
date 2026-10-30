# 疑難排解

[English](TROUBLESHOOTING.md) · [README](../README.zh-TW.md)

## 確認運作正常

執行 `/model-mod:setup` 之後：

1. 執行 `/model-mod:status`。mod 啟用時會回覆一行，例如 `model-mod <version>: picker=active; host=127.0.0.1; config=…; models=3; …`，其中 `models` 是提供的模型數。只設定 Codex 登入時，改顯示各帳號的狀態，不含 `host`、`config`、`models`。`model-mod: inactive; …` 表示沒有可用的上游設定（見疑難排解）。若回覆是說明插件 hook 未載入的文字，代表插件在此工作階段尚未啟用：執行 `/reload-plugins` 或重新啟動 Claude Code。
2. 執行 `/model-mod:model`，選一個你的模型並送出一則短訊息。回答來自你的上游。上游停擺或拒絕金鑰時，該回合會以錯誤訊息結束，不會改用訂閱重試。

## 症狀

| 症狀 | 可能原因 | 處理方式 |
|---|---|---|
| 狀態顯示 `inactive`，或沒有列出模型 | 沒有有效的上游設定、網址被拒絕，或插件未載入 | 設定 Codex 帳號與模型，或設定 API 金鑰與允許的網址，執行 `/reload-plugins`，再執行 `/model-mod:setup`。 |
| setup 時出現模型清單錯誤 | 網路、驗證或伺服器問題 | 檢查上游與金鑰。明確設定 `models` 可略過探索繼續進行。 |
| `model is not in the allowlist` | 該 ID 不在 `models` 內 | 選擇允許的 ID，或更新清單。 |
| 選了模型後出現錯誤 | 模型不可用、上游停機或金鑰被拒絕 | 修正上游、模型或金鑰，再執行 `/model-mod:refresh`。不會退回訂閱。 |
| effort 後綴被拒絕 | 上游不認得 `model(level)` | 把進階選項 `effortMode` 設為 `none`。 |
| 圖片工具不存在或被拒絕 | 選了 Codex 模型、沒有圖片模型，或未選你的模型 | 圖片生成僅供 API 使用；設定 `imageModel` 並選擇 API 模型。 |
| `web_fetch` 拒絕某網址 | 不是 HTTP(S)，或目的地是私網 | 改用公開的 HTTP(S) 網址。 |
| 太早壓縮，或長輸入被拒絕 | 假設的視窗與模型實際視窗不同 | 調整 `contextWindow`。 |
| 上游正常，但 auto 權限模式下動作被擋 | 分類器跑在你的訂閱上且失敗 | 改用 default 或 acceptEdits 模式搭配 allow 規則。 |
| 解除安裝後 Claude Code 以無法使用的模型啟動 | Claude Code 儲存了你最後一次選的模型 | 執行 `/model sonnet`，或從設定中移除已儲存的 `model` 項目。 |

## Codex 登入

| 症狀 | 處理方式 |
|---|---|
| 尚未登入或帳號目錄不存在 | 執行 `/model-mod:setup` 並選 Codex login，在終端機依畫面指示建立目錄並執行 `CODEX_HOME=... codex login`，之後重新執行 setup。Windows 會顯示 PowerShell 命令。 |
| Codex 版本過舊 | 將官方 CLI 升級至至少 0.165.0，再重試。 |
| helper 無法啟動 | 安裝 Python 3.9 以上版本並檢查 `pythonBin`，也檢查 `codexBin` 與 `codexAccountsDir` 路徑。執行檔須為命令名稱或絕對路徑。 |
| `unsupported codex behavior` 或協定不相容 | helper 遇到不支援的項目或設定時會終止回合。請檢查 Codex 版本及有效設定，更新或檢查 Codex 後再重試。見[限制說明](LIMITATIONS.zh-TW.md#codex-登入的限制)。 |
| 429、額度或速率限制 | 查看你的 Codex 訂閱額度與重置時間。尚未輸出前，重試會遵循最多 15 秒的 `Retry-After`；要求等待更久時直接結束回合。不會自動輪替帳號。 |
| 帳號設定被拒且回復失敗 | 開啟 `/plugin configure model-mod@model-mod`，手動將 `codexModels` 還原成先前的值，也檢查 `codexAccounts`；需要時再執行 setup。 |

## 更新

```bash
claude plugin marketplace update
claude plugin update model-mod@model-mod
```

然後重新啟動 Claude Code 套用更新。只有新版本的 release 才會送到你這裡（見[變更紀錄](../CHANGELOG.md)）。更新會取代已安裝插件目錄中的檔案，所以自訂提示詞請放在 `promptsDir` 指定的目錄；你的設定存放在插件目錄之外。

## 解除安裝

1. 先選訂閱模型（例如 `/model sonnet`）。Claude Code 會把互動式的模型選擇存成預設值，否則已儲存的本地預設值會在解除安裝後留下。
2. 在工作階段中執行 `/plugin uninstall model-mod@model-mod`，或在 shell 執行 `claude plugin uninstall model-mod@model-mod`，然後重新啟動。Claude Code 會保留插件快取。
