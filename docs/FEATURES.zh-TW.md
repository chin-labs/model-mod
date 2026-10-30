# 你的模型能做什麼

[English](FEATURES.md) · [README](../README.zh-TW.md)

- **串流與工具。** 文字與工具呼叫皆為串流。尚未收到任何輸出前，HTTP 429、502、503、504、529 與其他暫時性錯誤會在 2、6、15 秒後重試（最多三次）。整數 `Retry-After` 為 0–15 秒時，下一次等待至少採用該值；超過 15 秒則立即以 HTTP 狀態與要求的等待秒數結束回合。無效值與 HTTP 日期一律忽略。輸出開始後串流中斷，該回合直接結束，不會重播。
- **內建工具、Skills 與 MCP。** 照常運作。工具輸入 schema 不會轉交，參數由 Claude Code 自行驗證。
- **子代理與 Workflow。** 在訂閱工作階段中，可用 `model-mod:local-worker` 代理類型把工作交給你的模型（需設定 `workerModel` 或 `fallbackModel`），或讓 Workflow agent 指定 `model: "<你的模型 ID>"`。用你的模型的工作階段仍可委派給訂閱模型，該請求走訂閱。
- **網頁搜尋與擷取。** `web_search` 經 API 上游執行，Codex 模型無法使用。`web_fetch` 自行下載公開 HTTP(S) 頁面，每一跳都檢查所有 DNS 回答，拒絕私網與特殊用途位址（最多五次重新導向）。
- **圖片生成。** `generate_image` 把 PNG 存到工作目錄。API 路徑使用 `/v1/images/generations` 與設定的圖片模型；Codex 登入使用內建圖片生成，不需設定 `imageModel`。
- **工具搜尋。** `tool_search` 用來找出 schema 被延後載入的 MCP 工具。
- **Effort。** Claude Code 的五級（`low`、`medium`、`high`、`xhigh`、`max`）以模型後綴（如 `model(high)`）送出。Codex 登入路徑會由 helper 將後綴轉為 app-server effort，包含 `max`；`effortMode` 僅適用 API 路徑。Ultracode 是獨立的 workflow 開關，不改變等級。
- **壓縮。** `/compact` 與自動壓縮使用你的模型。摘要保留多少取決於模型，不是無損存檔。
- **圖片與 PDF。** 圖片會轉交。單頁 PDF 以圖片方式讀取。
- **Prompt cache。** API 上游回報的快取用量會原樣帶回；Codex 用量由 app-server 的 token 用量推算。快取計數語意尚未完全驗證。
- **自動切換（預設關閉）。** 設定 `fallbackModel` 後，當某回合結束時訂閱用量已達 `fallbackPercent` 且重置時間在未來，工作階段會切到該模型並顯示通知，重置後再切回。它不會重送觸發上限的那一回合、不會重置任何限制，也不會在工具迴圈中或對子代理執行。手動換模型會取消切回。切換期間，你的對話會送往你的上游。

Codex 模型的工具清單不包含 `web_search`，但仍可使用 `generate_image`、`web_fetch` 與 `tool_search`。Codex 自動壓縮項目不受支援；見[限制說明](LIMITATIONS.zh-TW.md#codex-登入的限制)。

`web_search`、`web_fetch`、`generate_image`、`tool_search` 在 model-mod 啟用期間註冊（`generate_image` 需設定 API 圖片模型或 Codex 帳號，關閉工具搜尋時不註冊 `tool_search`），最多讓訂閱模型的請求多約 3 KB 的工具定義；訂閱模型呼叫時會被拒絕，請改用 Claude Code 內建工具。它們遵循 Claude Code 的權限規則。模型的實際表現取決於模型本身；本插件不會讓它等同訂閱模型。

## 背景 Codex 委派

在 `/model-mod:review` 或 `/model-mod:rescue` 加上 `--background`，即可提交後不等待結果。工作不寫檔（仍可能執行讀取類命令）。`/model-mod:jobs [ID] [--all]` 列出目前工作區或所有工作區的工作，或查看單一工作；`/model-mod:result ID` 讀取結果，`/model-mod:cancel ID` 取消工作，`/model-mod:jobs --clear` 刪除目前工作區已終態的紀錄與結果。ID 可使用至少四位的唯一十六進位前綴。完成通知僅盡力提供。
