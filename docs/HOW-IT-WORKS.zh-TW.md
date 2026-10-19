# 運作方式

[English](HOW-IT-WORKS.md) · [README](../README.zh-TW.md)

mod 只替它管理的模型 ID 回答。設定了 `models` 時，管理範圍就是該清單；否則為上游的 chat 模型。含 `claude` 或 `anthropic` 的 ID 與 Claude Code 的官方別名一律不管理，圖片、embedding、語音與 moderation 模型也不會被探索進來。其他模型照 Claude Code 原本的路徑走。

對管理中的模型，對話、壓縮與 `/btw` 都送往你的上游，且**失敗時絕不退回訂閱**：上游出錯，該回合就以錯誤訊息結束。

## 自訂提示

壓縮、標題、子代理與 worker 的提示放在插件 `prompts/` 目錄的 `compact.md`、`title.md`、`subagent-note.md`、`worker.md`。要用自己的版本，把 `promptsDir` 設為你的目錄（插件目錄內的檔案會在升級時被取代）。沒有內建後備：檔案缺少、為空、無法讀取或超過 8000 字元，都視為不可用。沒有 `compact.md` 時略過本地壓縮；沒有 `title.md` 時以提示的前 50 個字元當標題；沒有 `worker.md` 時不提供 worker 代理類型。`/model-mod:refresh` 會重新讀取這些檔案。

## 限制、隱私與合規

- [限制說明](LIMITATIONS.zh-TW.md)列出與訂閱模型的已知差異、尚未驗證的項目，以及哪些 Claude Code 請求仍可能送到你的訂閱。
- 訊息、系統指示（含專案指示檔）、工具定義與結果、圖片都會送往你的上游及其背後的供應商。搜尋查詢送往上游，擷取的網址送往目標網站，圖片提示送往圖片端點。
- mod 使用插件 hook，不修改 Claude Code 執行檔、不攔截 TLS、不讀取訂閱憑證檔，也不把訂閱憑證送往你的上游。它只使用你設定的上游金鑰，且絕不把你的模型的回合改走訂閱重試。
- Auto 權限模式會把完整對話與專案指示送到你的訂閱做分類，即使目前選的是你的模型。改用 default 或 acceptEdits 模式搭配 allow 規則即可避免。Claude Code 自己發出的其他請求也可能使用你的訂閱；見[訂閱側請求](LIMITATIONS.zh-TW.md#訂閱側請求)。
- 金鑰透過環境變數而非命令參數交給 curl。錯誤訊息中的金鑰會被遮蔽，但串流輸出不會改寫，因此請使用你信任的上游。

本專案獨立運作，與 Anthropic 或 OpenAI 均無隸屬關係，也未獲任一方背書。[合規說明](COMPLIANCE.zh-TW.md)解釋設計限制，並附上現行條款供你自行閱讀。這些說明不代表條款已授權此用法；閱讀條款是你自己的責任。

## 開發

```bash
claude plugin validate .
claude plugin test .
```

原始碼匯入 Claude Code 提供的模組，因此型別檢查與測試需要支援 mod 的 Claude Code。測試使用假憑證。要試用工作副本，以 `--plugin-dir .` 啟動 Claude Code。不要散布 Claude Code 產生的 API 宣告或任何憑證。

## 問題回報與安全

- 錯誤與問題：[GitHub Issues](https://github.com/chin-labs/model-mod/issues)。歡迎提交 PR，但不保證回覆時間。
- Pull request：被接受的變更會在上游整合，並以發布快照的形式公開。本儲存庫的 `main` 分支只接收發布快照，所以 PR 可能不會在這裡合併，而是在關閉時附上包含該變更的 commit。
- 安全問題：請使用 GitHub 私密漏洞回報（儲存庫的 Security 分頁 → Report a vulnerability），不要在公開 Issue 貼漏洞細節。
- 回報不得包含金鑰、訂閱憑證、未遮蔽的逐字稿、私人路徑或內網端點。請附 Claude Code 與插件版本、使用假憑證的最小重現，以及預期與實際結果。

## 社群出處

以下兩則連結僅供背景參考，未經專案驗證；不構成授權，使用條款仍以你自己閱讀的現行條款為準。

- https://x.com/thsottiaux/status/2076119366647894371
- https://x.com/thsottiaux/status/2093573575869698091
