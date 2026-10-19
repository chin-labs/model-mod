# 疑難排解

[English](TROUBLESHOOTING.md) · [README](../README.zh-TW.md)

## 確認運作正常

執行 `/model-mod:setup` 之後：

1. 執行 `/model-mod:status`。mod 啟用時會回覆一行，例如 `model-mod <version>: picker=active; host=127.0.0.1; config=…; models=3; …`，其中 `models` 是提供的模型數。`model-mod: inactive; …` 表示沒有可用的金鑰或網址（見疑難排解）。若回覆是說明插件 hook 未載入的文字，代表插件在此工作階段尚未啟用：執行 `/reload-plugins` 或重新啟動 Claude Code。
2. 執行 `/model-mod:model`，選一個你的模型並送出一則短訊息。回答來自你的上游。上游停擺或拒絕金鑰時，該回合會以錯誤訊息結束，不會改用訂閱重試。

## 症狀

| 症狀 | 可能原因 | 處理方式 |
|---|---|---|
| 狀態顯示 `inactive`，或沒有列出模型 | 未設定金鑰、網址被拒絕，或插件未載入 | 設定金鑰與允許的網址，執行 `/reload-plugins`，再執行 `/model-mod:setup`。 |
| setup 時出現模型清單錯誤 | 網路、驗證或伺服器問題 | 檢查上游與金鑰。明確設定 `models` 可略過探索繼續進行。 |
| `model is not in the allowlist` | 該 ID 不在 `models` 內 | 選擇允許的 ID，或更新清單。 |
| 選了模型後出現錯誤 | 模型不可用、上游停機或金鑰被拒絕 | 修正上游、模型或金鑰，再執行 `/model-mod:refresh`。不會退回訂閱。 |
| effort 後綴被拒絕 | 上游不認得 `model(level)` | 把進階選項 `effortMode` 設為 `none`。 |
| 圖片工具不存在或被拒絕 | 沒有圖片模型，或未選你的模型 | 設定 `imageModel`，並選擇你的模型。 |
| `web_fetch` 拒絕某網址 | 不是 HTTP(S)，或目的地是私網 | 改用公開的 HTTP(S) 網址。 |
| 太早壓縮，或長輸入被拒絕 | 假設的視窗與模型實際視窗不同 | 調整 `contextWindow`。 |
| 上游正常，但 auto 權限模式下動作被擋 | 分類器跑在你的訂閱上且失敗 | 改用 default 或 acceptEdits 模式搭配 allow 規則。 |
| 解除安裝後 Claude Code 以無法使用的模型啟動 | Claude Code 儲存了你最後一次選的模型 | 執行 `/model sonnet`，或從設定中移除已儲存的 `model` 項目。 |

## 更新

```bash
claude plugin marketplace update
claude plugin update model-mod@model-mod
```

然後重新啟動 Claude Code 套用更新。只有新版本的 release 才會送到你這裡（見[變更紀錄](../CHANGELOG.md)）。更新會取代已安裝插件目錄中的檔案，所以自訂提示詞請放在 `promptsDir` 指定的目錄；你的設定存放在插件目錄之外。

## 解除安裝

1. 先選訂閱模型（例如 `/model sonnet`）。Claude Code 會把互動式的模型選擇存成預設值，否則已儲存的本地預設值會在解除安裝後留下。
2. 在工作階段中執行 `/plugin uninstall model-mod@model-mod`，或在 shell 執行 `claude plugin uninstall model-mod@model-mod`，然後重新啟動。Claude Code 會保留插件快取。
