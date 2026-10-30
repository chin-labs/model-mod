# 限制說明

[English](LIMITATIONS.md)

本頁說明你的模型與訂閱模型有何不同、哪些行為尚未驗證，以及哪些客戶端請求仍可能送到你的訂閱。適用範圍是由 model-mod 路由的模型；訂閱模型維持客戶端原本的路徑。

CLIProxyAPI 是已測試的 API 上游；Codex 登入是另一種上游。設定方式見 [README](../README.zh-TW.md)。

## 已測試版本

Codex 登入與 API 上游已在 **Claude Code 2.1.314** 測試。API 上游也曾在 2.1.299 至 2.1.310 測試；在 2.1.310 檢查了插件載入、單元測試、回合與更新路徑。其他版本未測，請勿假設可用。這些檢查使用測試用設定，而非一般的機密選項流程，因此無法說明你的金鑰如何儲存（見[尚未驗證](#尚未驗證)）。

Marketplace 安裝已用本機 clone 與使用標準 HTTP 協定的 Git 伺服器測試過。客戶端不支援從單純（dumb）HTTP 的 Git 伺服器安裝，且解除安裝後會留下插件快取。

## 未識別的模型警告

啟動時 Claude Code 可能警告非 Claude 模型 ID 未獲識別，並假設 context 為 200k。這是客戶端行為，model-mod 無法消除。選取模型後，model-mod 會套用自己的 context 視窗；Codex 預設為 128,000 token。

## Codex 登入的限制

- 最近實測的 Codex CLI 版本為 **0.165.0**，也是最低版本；更舊的版本會被拒絕。較新版本會照常執行，但未逐版驗證。更新已測版本紀錄前，應對新版本執行手動 live 契約測試。
- 這是**軟隔離，不是嚴格的工具白名單**。helper 使用專用家目錄、唯讀 sandbox、不允許核准並關閉部分功能，但兩個 MCP 資源清單工具仍可能執行。執行期項目檢查在中斷回合之前、或與等待項目同批到達時遇到不允許或未知的項目，會終止回合並顯示 `Codex used a built-in tool that model-mod does not support (<type>); try again, and report it if it keeps happening` 訊息。若停用功能後仍出現 `sleep` 或 `collabAgentToolCall` 項目，helper 會中斷並正常結束回合，其後的非工具項目會被丟棄，已識別的動態工具呼叫則會保留。開始 thread 前，`config/read` 會檢查有效設定；新版若改變設定或協定，helper 會採保守拒絕。協定不相容時會顯示 `incompatible app-server protocol; update or check Codex`。重試前請檢查設定與 Codex 相容性。
- Codex 內建 shell、網路與瀏覽器工具、sleep、子代理、apps、plugins 和 goals 均已停用。patch 與檔案操作會被唯讀 sandbox 與項目白名單阻擋；項目處理方式如上述檢查所示。動態工具來自客戶端，另有上述 MCP 資源清單例外。模型會收到簡短的 developer instructions，要求只使用提供的函式工具、不使用內建 sleep、等待、協作及子代理工具，等待背景工作時結束回合；唯讀隔離的細節不會告知模型。
- Codex 保留 `mcp__` 開頭的名稱並限制工具名稱。bridge 以 `bridge_` 加雜湊作為受影響名稱的別名，回傳時還原原名。
- `max_tokens` 會接受但忽略；`tool_choice`、`temperature`、`top_p`、`stop_sequences`、`cache_control`、thinking 預算與簽章會被忽略；歷史 thinking 區塊會丟棄。helper 寫出的 `model-mod-note:` 診斷行是內部標記，會被丟棄，不會顯示給使用者。不要依賴這些控制項生效。
- Codex 模型不提供 `generate_image` 與 `web_search`，但保留 `web_fetch`。Codex 自動壓縮項目不受支援。使用者未明設 `contextWindow` 時，Codex 模型的預設視窗為 128,000 token。可用 `contextWindow` 設定視窗。這不會停用 model-mod 自己的壓縮。
- 每次呼叫會啟動一個本機 helper 程序與 `codex app-server`，會增加延遲；啟動延遲尚未量測。Windows 在設計上支援，但**未驗證**。
- Codex 的額度與速率限制取決於你自己的訂閱；達到限制時 model-mod 不會輪替帳號。

- 帳號名稱含 `claude` 或 `anthropic` 時，該帳號的模型 ID 會被過濾。若有效的 API 金鑰搭配遭拒的 `baseUrl`，整個 mod（含 Codex）都會停用。

## 已知限制

移除上游後，先前儲存的舊版 `/model` 自訂列可能仍會顯示；選取已移除的模型會被拒絕，請改選其他模型或從設定中移除舊列。`MODEL_MOD_CONFIG` 提供的 API 無法在 setup 中移除，須自行編輯該檔。

| 項目 | 會發生什麼 | 變通方法 |
|---|---|---|
| 輸出長度與 context | `maxTokens` 預設 32000；CLIProxyAPI 搭配 Codex 未強制較小的值，實際最大輸出未知。API 模型的預設 context 視窗為 272000（可設 `contextWindow`，最小 32000）。視窗過小時，客戶端的自動壓縮門檻會變負值，造成反覆壓縮。 | 把 `contextWindow` 設為模型的實際上限。 |
| 請求內容 | 對話請求帶 `model`、`max_tokens`、`stream`、`messages`、`system` 及選用的 `tools`；客戶端的其他請求欄位不會送出。 | 無需處理。 |
| 推理 | API 路徑只在工具迴圈內交回 Codex 形式的加密推理簽章；其他 thinking 與 server-tool 區塊會移除。簽章被拒時，去除後重試一次。 | 上游拒絕簽章時，設 `keepThinking: false`。 |
| Effort | API 路徑以模型後綴（如 `model(high)`）送出五個等級；Codex 登入路徑由 helper 將後綴對映成 app-server effort。這只確認名稱有送到上游，不代表推理強度會改變。Ultracode 是獨立開關，不改變等級；`/effort ultra` 由客戶端自己拒絕。 | 上游拒絕後綴時，設 `effortMode: none`。 |
| 失敗處理 | 尚未有任何輸出前，HTTP 429、502、503、504、529 與可辨識的暫時性錯誤（含早期的 `overloaded_error` 事件）會在 2、6、15 秒後重試（最多三次）。整數 `Retry-After` 為 0–15 秒時，下一次等待至少採用該值；超過 15 秒則立即以 HTTP 狀態與要求的等待秒數結束回合。無效值與 HTTP 日期一律忽略。輸出開始後串流中斷，該回合直接結束，不會重播。失敗的回合不會改用其他模型或訂閱重試。 | 重新送出訊息，或用 `/model` 換模型。 |
| 壓縮 | 只使用 `prompts/` 內的提示檔；缺檔時略過本地壓縮。摘要品質取決於模型。送去摘要的逐字稿有上限（總計 600000 字元、每則 20000、每個工具結果 1500）。代理內的壓縮尚未驗證。 | 重要事項寫進專案指示，不要只留在對話裡。 |
| 工具 | 工具 schema 為開放式（只有名稱與描述）。在 API 模型上，`web_search`、`web_fetch` 取代原生 WebSearch、WebFetch；Codex 模型保留 `web_fetch`，但不提供 `web_search`，且 `web_fetch` 回傳頁面內容，不做模型摘要。四個 mod 工具（`web_search`、`web_fetch`、`generate_image`、`tool_search`）在訂閱模型下拒絕呼叫，請改用內建工具。`web_fetch` 會拒絕部分公開 IPv6 literal，特殊 IPv6 過渡形式也未完整涵蓋。 | 改用其他網址形式，或用其他工具擷取。 |
| 子代理與 Workflow | 子代理取得工作階段系統提示加上委派備註。訂閱工作階段的 Agent 呼叫不能直接指定你的模型 ID；請用 `model-mod:local-worker` 代理類型或 Workflow agent。context 視窗覆寫跟隨主工作階段。 | 設定 `workerModel` 並使用 `model-mod:local-worker`。 |
| 圖片與 PDF | 圖片可用。單頁 PDF 會轉成圖片。原生 document 區塊與多頁 PDF 尚未驗證。 | 把頁面轉成圖片。 |
| 用量顯示 | 送往你上游的請求不會更新訂閱用量顯示，CLIProxyAPI 的回覆也不帶 rate-limit 欄位。 | 查看上游自己的用量頁面。 |
| 儲存的預設模型 | 客戶端把互動式的模型選擇存成預設值。帶著已儲存的本地模型解除安裝，會留下無法使用的預設值。 | 先選訂閱模型，或移除已儲存的 `model` 設定。 |
| 模型選單 | `/model-mod:model` 列出你的模型；客戶端自己的 `/model` 面板與 `/config` Model 不會列出，啟動時的 `--model <id>` 則繞過選單（用你的模型 ID 可正常運作）。 | 使用 `/model-mod:model`，或輸入 `/model <id>`。 |
| 組織管理的客戶端 | 標題、模型切換與壓縮 hook 會略過個人安裝的插件，除非組織把它列入管理設定。此情境未測試。 | 請管理員把插件列入管理設定。 |

SDK 與 `-p` 的呼叫端必須檢查結果文字是否以 `model-mod:` 開頭：失敗的回合會刻意以一則文字訊息加 `end_turn` 結束，`is_error` 為 `false`，因為丟出例外會讓引擎改走訂閱端點。

## 尚未驗證

以下行為尚未驗證，請勿假設可用。

- **Codex 環境。** Windows、Python 3.9 實際執行、live SIGHUP 回收及較新 Codex 版本逐版驗證尚未完成。啟動延遲尚未量測。`max` effort 只用假 Codex 測試過。
- **自動切換。** 真實用量重置後切回、真實被拒請求後的 rate-limit 資料，以及從 Remote Control 觸發。
- **Remote Control 與手機。** 只試過簡短的工作階段。長時間連線與從手機選模型未測。
- **真實的上游 rate limit。** 已測試重試，但未測已耗盡的上游憑證之間的容錯，也未測快取 token 對你額度的影響。
- **版本與金鑰儲存。** 上述以外的版本、一般機密選項流程搭配 macOS keychain 儲存，以及客戶端升級後金鑰與設定是否保留。
- **GitHub 託管的 marketplace。** 直接從 GitHub 託管的 marketplace 安裝，尚未端到端測試；若失敗請改用本機 clone。
- **長時間或複雜的工作。** 反覆壓縮的長工作階段、代理內壓縮、長 Workflow、多頁 PDF 與原生 document 區塊、在之後的工作階段延續帶簽章推理的對話，以及跨工作階段延續代理。
- **Fetch 網路防護。** 位址與重新導向限制已有單元測試；真實的 DNS rebinding 與外部重新導向攻擊尚未端到端測試。
- **其他側請求。** 見下節末段列出的客戶端請求。

## 訂閱側請求

客戶端有些請求是獨立發出的，與你選的模型無關。在預設值（`localTitle: true`、`localContext: true`、`sideModel: claude-haiku-5-5`）下，下表列出哪些會送到你的訂閱端點。表中只涵蓋已檢查的路徑，不涵蓋所有客戶端請求，因此不是完整的隱私保證。

| 功能或設定 | 送往你訂閱的內容 | 備註 |
|---|---|---|
| `localTitle: false` 的首提示標題 | 第一個使用者提示 | 送到官方 `sideModel`；預設值（`true`）經你的上游命名工作階段。 |
| Auto 權限模式 | 對話、專案指示與命令或工具輸入 | 使用你訂閱上的獨立分類器模型，不是 `sideModel`。default 與 acceptEdits 模式對測試的命令沒有分類請求。 |
| `Agent(model: 'haiku')` | 子任務提示與專案指示 | 在官方模型上執行。`model-mod:local-worker` 使用你的上游。 |
| 未帶名稱的 `/rename` | 工作階段的使用者與助手訊息，即使 `localTitle: true` | 已知限制，未修正。請用 `/rename <name>`。 |
| `localContext: false` 的 `/context` | 分類內容（含部分專案指示）與模型 ID | 使用訂閱的 token 計數。預設的本地估算不會送出任何內容。 |
| 客戶端原生的 WebFetch 摘要 | 擷取的頁面文字與摘要提示 | 你的模型的一般對話使用沒有摘要的 `web_fetch`。 |
| 你的模型上的 `/btw` | 無 | 經你的上游以唯讀上下文回答。 |

檢查時未觸發或結果不確定，請視為未驗證：工具使用摘要、提示建議、離開後摘要、代理進度摘要、記憶擷取／選擇／合成、LLM 型的 prompt 或 agent hook、子代理壓縮、原生 WebSearch、訂閱用量與額度請求、cache touch，以及模型或金鑰驗證。

## 範圍之外

| 領域 | 界線 |
|---|---|
| 全域 API 取代 | model-mod 不更動 `ANTHROPIC_BASE_URL`、不修改客戶端執行檔，也不改寫客戶端的每個請求。 |
| 訂閱憑證 | mod 既不讀取也不轉送。 |
| claude.ai 連接器 | 支援標準 MCP 伺服器；需 claude.ai 登入的連接器不支援。 |
| 模型等價 | 路由不會讓你的上游模型獲得其他模型的能力或身分。 |
| 繞過用量限制 | 選用的切換只改變下一則訊息使用的模型，不會重置或繞過訂閱限制。 |
