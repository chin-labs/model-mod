# 你的模型能做什麼

[English](FEATURES.md) · [README](../README.zh-TW.md)

- **串流與工具。** 文字與工具呼叫皆為串流。尚未收到任何輸出前，HTTP 429、502、503、504、529 與其他暫時性錯誤會在 2、6、15 秒後重試（最多三次）。輸出開始後串流中斷，該回合直接結束，不會重播。
- **內建工具、Skills 與 MCP。** 照常運作。工具輸入 schema 不會轉交，參數由 Claude Code 自行驗證。
- **子代理與 Workflow。** 在訂閱工作階段中，可用 `model-mod:local-worker` 代理類型把工作交給你的模型（需設定 `workerModel` 或 `fallbackModel`），或讓 Workflow agent 指定 `model: "<你的模型 ID>"`。用你的模型的工作階段仍可委派給訂閱模型，該請求走訂閱。
- **網頁搜尋與擷取。** `web_search` 經你的上游執行。`web_fetch` 自行下載公開 HTTP(S) 頁面，每一跳都檢查所有 DNS 回答，拒絕私網與特殊用途位址（最多五次重新導向）。
- **圖片生成。** `generate_image` 呼叫上游的 `/v1/images/generations`，並把 PNG 存到工作目錄。需要圖片模型。
- **工具搜尋。** `tool_search` 用來找出 schema 被延後載入的 MCP 工具。
- **Effort。** Claude Code 的五級（`low`、`medium`、`high`、`xhigh`、`max`）以模型後綴（如 `model(high)`）送出。Ultracode 是獨立的 workflow 開關，不改變等級。
- **壓縮。** `/compact` 與自動壓縮使用你的模型。摘要保留多少取決於模型，不是無損存檔。
- **圖片與 PDF。** 圖片會轉交。單頁 PDF 以圖片方式讀取。
- **Prompt cache。** 上游回報的快取用量會原樣帶回。
- **自動切換（預設關閉）。** 設定 `fallbackModel` 後，當某回合結束時訂閱用量已達 `fallbackPercent` 且重置時間在未來，工作階段會切到該模型並顯示通知，重置後再切回。它不會重送觸發上限的那一回合、不會重置任何限制，也不會在工具迴圈中或對子代理執行。手動換模型會取消切回。切換期間，你的對話會送往你的上游。

`web_search`、`web_fetch`、`generate_image`、`tool_search` 只提供給你的模型；選了訂閱模型時請改用 Claude Code 內建工具。它們遵循 Claude Code 的權限規則。模型的實際表現取決於模型本身；本插件不會讓它等同訂閱模型。
