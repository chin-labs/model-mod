# 限制說明

[English](LIMITATIONS.md)

本頁說明你的模型與訂閱模型有何不同、哪些行為尚未驗證，以及哪些客戶端請求仍可能送到你的訂閱。適用範圍是由 model-mod 路由的模型；訂閱模型維持客戶端原本的路徑。

CLIProxyAPI 是曾測試過的一例 API 上游；Codex 登入是另一種上游。設定方式見 [README](../README.zh-TW.md)。

## 已測試版本

Codex 登入與 API 上游已在 **Claude Code 2.1.314** 測試。API 上游也曾在 2.1.299 至 2.1.310 測試；在 2.1.310 檢查了插件載入、單元測試、回合與更新路徑。其他版本未測，請勿假設可用。這些檢查使用測試用設定，而非一般的機密選項流程，因此無法說明你的金鑰如何儲存（見[尚未驗證](#尚未驗證)）。

Marketplace 安裝已用本機 clone 與使用標準 HTTP 協定的 Git 伺服器測試過。客戶端不支援從單純（dumb）HTTP 的 Git 伺服器安裝，且解除安裝後會留下插件快取。

## 未識別的模型警告

啟動時 Claude Code 可能警告非 Claude 模型 ID 未獲識別，並假設 context 為 200k。這是客戶端行為，model-mod 無法消除。選取模型後，model-mod 會套用自己的 context 視窗；Codex 使用模型目錄的有效視窗，讀不到時退回 128,000 token。

## Codex 登入的限制

- 最近實測的 Codex CLI 版本為 **0.166.0**；最低版本為 **0.165.0**，更舊的版本會被拒絕。較新版本會照常執行，但未逐版驗證。更新已測版本紀錄前，應對新版本執行手動 live 契約測試。
- 這是**軟隔離，不是嚴格的工具白名單**。helper 使用專用家目錄、唯讀 sandbox、不允許核准並關閉部分功能，但兩個 MCP 資源清單工具仍可能執行。執行期項目檢查在中斷回合之前、或與等待項目同批到達時遇到不允許或未知的項目，會終止回合並顯示 `Codex used a built-in tool that model-mod does not support (<type>); try again, and report it if it keeps happening` 訊息。若停用功能後仍出現 `sleep` 或 `collabAgentToolCall` 項目，helper 會中斷並正常結束回合，其後的非工具項目會被丟棄，已識別的動態工具呼叫則會保留。開始 thread 前，`config/read` 會檢查有效設定；新版若改變設定或協定，helper 會採保守拒絕。協定不相容時會顯示 `incompatible app-server protocol; update or check Codex`。重試前請檢查設定與 Codex 相容性。
- Codex 內建 shell、網路與瀏覽器工具、sleep、子代理、apps、plugins 和 goals 均已停用。patch 與檔案操作會被唯讀 sandbox 與項目白名單阻擋；項目處理方式如上述檢查所示。動態工具來自客戶端，另有上述 MCP 資源清單例外。模型會收到簡短的 developer instructions，要求只使用提供的函式工具、不使用內建 sleep、等待、協作及子代理工具，等待背景工作時結束回合；唯讀隔離的細節不會告知模型。
- Codex 保留 `mcp__` 開頭的名稱並限制工具名稱。bridge 以 `bridge_` 加雜湊作為受影響名稱的別名，回傳時還原原名。
- `max_tokens` 會接受但忽略；`tool_choice`、`temperature`、`top_p`、`stop_sequences`、`cache_control` 與 thinking 預算會被忽略。helper 寫出的 `model-mod-note:` 診斷行是內部標記，會被丟棄，不會顯示給使用者。不要依賴這些控制項生效。
- `codexKeepReasoning` 預設為 `on`。bridge 使用 Codex 0.165.0 的實驗性 `experimentalRawEvents` 與 `thread/inject_items` 介面；上游可能修改這些 API，且重放尚未對真實 Codex 回合驗證。OpenAI 回傳的不透明 reasoning item 可能包含加密資料；簽章每個 item 上限 256 KiB、每次回應上限 1 MiB，超出的項目會丟棄。只保留第一段助手文字或工具呼叫之前的 reasoning；其後交錯的 reasoning 會丟棄，以維持重放順序。推理只在同一工作階段的工具往返期間保存在記憶體，重新載入或重啟後遺失。換帳號或模型可能使其失效；若輸出前被拒，會去掉推理重建請求一次。不保證與 API 路徑完全等價。
- Codex 原生搜尋僅在 `codexWebSearch` 開啟且工作階段工具清單包含 WebSearch 時啟用。原生搜尋與 openPage 在 OpenAI 端執行，不受 Claude 權限的網域規則（allowed／blocked domains）限制；model-mod 不做 `allowed_domains` 的安全宣稱。查詢文字會送往 OpenAI。原生搜尋不經 Claude 逐次詢問權限，顯示的搜尋文字也會進入助手歷史。搜尋活動每次顯示為一行助手文字，不是可展開的工具結果或內建「已搜尋」區塊；真實客戶端顯示尚未驗證，不顯示不透明的搜尋結果。Codex 不提供 mod 的 `web_search`，但保留 `generate_image` 與 `web_fetch`。Codex 使用內建圖片模型，提示詞與生成圖片內容送往 OpenAI；尺寸與品質僅作為提示詞中的請求，不保證生效；是否計入額度尚未驗證。超過 20 MiB 的圖片會被拒絕。即使 sandbox 唯讀，app-server 仍會自行把圖片寫入 `CODEX_HOME/generated_images`；取得位元組後，model-mod 嘗試不跟隨符號連結刪除該字面路徑，失敗僅記內部 note，不使呼叫失敗。輸出以 0600 權限排他建立。Codex context 預設為帳號模型目錄視窗乘以有效比例，讀不到時退回 128,000 token；明設 `contextWindow` 可覆寫。helper 將 Codex 自動壓縮門檻設在客戶端視窗之上並於內部記錄壓縮事件；這不保證完全停用 Codex 壓縮，也不會停用 model-mod 自己的壓縮。
- 每次呼叫會啟動一個本機 helper 程序與 `codex app-server`，會增加延遲；啟動延遲尚未量測。Windows **尚未驗證**；見 [Windows 驗證清單](WINDOWS.zh-TW.md)。Codex 圖片生成僅支援 POSIX。
- Codex 的額度與速率限制取決於你自己的訂閱；達到限制時 model-mod 不會輪替帳號。

- 帳號名稱含 `claude` 或 `anthropic` 時，該帳號的模型 ID 會被過濾。若有效的 API 金鑰搭配遭拒的 `baseUrl`，整個 mod（含 Codex）都會停用。

## 已知限制

移除上游後，先前儲存的舊版 `/model` 自訂列可能仍會顯示；選取已移除的模型會被拒絕，請改選其他模型或從設定中移除舊列。`MODEL_MOD_CONFIG` 提供的 API 無法在 setup 中移除，須自行編輯該檔。 移除 API 會停用上游，但金鑰仍留在客戶端的安全儲存中，model-mod 無法清除；重新加入時 setup 會先確認要把已存金鑰送往哪個主機。

| 項目 | 會發生什麼 | 變通方法 |
|---|---|---|
| 輸出長度與 context | `maxTokens` 預設 32000；CLIProxyAPI 搭配 Codex 未強制較小的值，實際最大輸出未知。API 模型的預設 context 視窗為 272000（可設 `contextWindow`，最小 32000）。視窗過小時，客戶端的自動壓縮門檻會變負值，造成反覆壓縮。 | 把 `contextWindow` 設為模型的實際上限。 |
| 請求內容 | 對話請求帶 `model`、`max_tokens`、`stream`、`messages`、`system` 及選用的 `tools`；客戶端的其他請求欄位不會送出。 | 無需處理。 |
| 推理 | API 路徑只在工具迴圈內交回 Codex 形式的加密推理簽章；其他 thinking 與 server-tool 區塊會移除。簽章被拒時，去除後重試一次。 | 上游拒絕簽章時，設 `keepThinking: false`。 |
| Effort | API 路徑以模型後綴（如 `model(high)`）送出五個等級；Codex 登入路徑依模型目錄宣告夾值，`max` 對應最高宣告值，絕不送 `minimal`；目錄不可用時維持原值。未帶 effort 後綴時，若支援 `low` 則使用 `low`，否則使用模型預設值。這只確認名稱有送到上游，不代表推理強度會改變。Ultracode 是獨立開關，不改變等級；`/effort ultra` 由客戶端自己拒絕。 | 上游拒絕後綴時，設 `effortMode: none`。 |
| 失敗處理 | 尚未有任何輸出前，HTTP 429、502、503、504、529 與可辨識的暫時性錯誤（含早期的 `overloaded_error` 事件）會在 2、6、15 秒後重試（最多三次）。整數 `Retry-After` 為 0–15 秒時，下一次等待至少採用該值；超過 15 秒則立即以 HTTP 狀態與要求的等待秒數結束回合。無效值與 HTTP 日期一律忽略。輸出開始後串流中斷，該回合直接結束，不會重播。失敗的回合不會改用其他模型或訂閱重試。 | 重新送出訊息，或用 `/model` 換模型。 |
| 壓縮 | 只使用 `prompts/` 內的提示檔；缺檔時略過本地壓縮。摘要品質取決於模型。送去摘要的逐字稿有上限（總計 600000 字元、每則 20000、每個工具結果 1500）。代理內的壓縮尚未驗證。 | 重要事項寫進專案指示，不要只留在對話裡。 |
| 工具 | 工具 schema 為開放式（只有名稱與描述）。在 API 模型上，`web_search`、`web_fetch` 取代原生 WebSearch、WebFetch；Codex 模型保留 `web_fetch`，並以原生搜尋取代 mod 的 `web_search`，且 `web_fetch` 回傳頁面內容，不做模型摘要。四個 mod 工具（`web_search`、`web_fetch`、`generate_image`、`tool_search`）在訂閱模型下拒絕呼叫，請改用內建工具。`web_fetch` 會拒絕部分公開 IPv6 literal，特殊 IPv6 過渡形式也未完整涵蓋。 | 改用其他網址形式，或用其他工具擷取。 |
| 子代理與 Workflow | 子代理取得工作階段系統提示加上委派備註。訂閱工作階段的 Agent 呼叫不能直接指定你的模型 ID；請用 `model-mod:local-worker` 代理類型或 Workflow agent。context 視窗覆寫跟隨主工作階段。 | 設定 `workerModel` 並使用 `model-mod:local-worker`。 |
| 圖片與 PDF | 圖片可用。單頁 PDF 會轉成圖片。原生 document 區塊與多頁 PDF 尚未驗證。 | 把頁面轉成圖片。 |
| 用量顯示 | 送往你上游的請求不會更新訂閱用量顯示，CLIProxyAPI 的回覆也不帶 rate-limit 欄位。 | 查看上游自己的用量頁面。 |
| 儲存的預設模型 | 客戶端把互動式的模型選擇存成預設值。帶著已儲存的本地模型解除安裝，會留下無法使用的預設值。 | 先選訂閱模型，或移除已儲存的 `model` 設定。 |
| 模型選單 | `/model-mod:model` 列出你的模型；客戶端自己的 `/model` 面板與 `/config` Model 不會列出，啟動時的 `--model <id>` 則繞過選單（用你的模型 ID 可正常運作）。 | 使用 `/model-mod:model`，或輸入 `/model <id>`。 |
| 組織管理的客戶端 | 標題、模型切換與壓縮 hook 會略過個人安裝的插件，除非組織把它列入管理設定。此情境未測試。 | 請管理員把插件列入管理設定。 |

SDK 與 `-p` 的呼叫端必須檢查結果文字是否以 `model-mod:` 開頭：失敗的回合會刻意以一則文字訊息加 `end_turn` 結束，`is_error` 為 `false`，因為丟出例外會讓引擎改走訂閱端點。

## 尚未驗證

以下行為尚未驗證，請勿假設可用。

- 真實客戶端的 setup 與 Remote Control 尚未端到端驗證。在一台 Mac（Claude Code 2.1.316、Codex 0.166.0、單一帳號）上以手動方式檢查過前景 review 與 rescue、Ctrl+C 與 Esc 中斷，以及發起工作的 session 內的完成 toast。
- Windows 整體尚未驗證；請使用 [Windows 驗證清單](WINDOWS.zh-TW.md)。
- hook 時間預算、重載行為及 `$.store` 權限尚未驗證。
- 實驗性 reasoning 重放尚未驗證：兩個含工具往返的真實回合沒有報錯，但逐字稿中沒有出現 thinking 區塊。真實的圖片生成與原生搜尋在單一帳號上各檢查過一次。
- 真實 review 是否嚴格遵守 Stop gate 所依賴的 `outputSchema` 尚未驗證；真實 Codex 的 pass、block、unknown 結果各觀察到一次。
- commentary 事件順序，以及 `classic.Stop` 與官方外掛 hook 的真實順序尚未驗證。
- 與官方 `openai/codex-plugin-cc` 的並存只做了對上游 commit `db52e28f4d9d` 的靜態比對，兩者未實際同時執行。請使用完整指令名稱（`/codex:review`、`/model-mod:review`），並且最多開啟一個 Stop 審查 gate。兩者預設的 Codex home 各自獨立，但若刻意把兩者指向同一個 `CODEX_HOME`，帳號設定與信任紀錄可能互相影響。
- Codex 額度耗盡時的切換，以及 `priority` 計費與 `codexServiceTier` 實際服務層級尚未驗證；使用 `priority` 的真實回合已被接受。
- 以 `codex resume` 續跑 transfer 後的工作階段尚未驗證；匯入本身，以及使用 `apply_patch` 的多檔 workspace-write rescue 各檢查過一次。
- Linux 只做了離線驗證：helper 測試、假 Codex 流程與 socket 路徑長度限制在 Linux arm64 容器（Python 3.12、Git 2.34、無網路）內通過；hook 測試、真實帳號回合、`/proc` 後備路徑與 Git 2.54 的 configured-hook 檢查未在其上執行。exFAT 尚未驗證。

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

Codex 額度用完不輪流換帳號，可設備援模型（不同帳號或上游）。API 上游沒有官方 rateLimits，不適用 Codex fallback 機制。

Codex reasoning 保留為實驗性功能：簽章依前綴過濾，快取以第一個工具呼叫 ID 為鍵，並非完整對話識別；真實 Codex 重放尚未驗證。

## 審查關卡限制

Stop gate 預設關閉。結構化裁定的品質、漏判情況，以及真實 Codex 是否遵守 `outputSchema` 均未驗證；此功能不是安全或合規保證。與官方 Codex gate 並存時的順序尚未驗證。因阻擋而繼續的回合不會再次審查：狀態會顯示變更未經重新審查，因此上限設為 2 次並不代表修正會被第二次審查。在 gate 審查中按 Esc 會結束 helper，並以未驗證警告放行。Pass 只在記憶體中對相符的工作階段與指紋有效；模組重新載入會清除 pass 快取與 gate 阻擋計數。目前目錄及其祖先均無 `.git` 時，自動 gate 會靜默跳過；儲存庫尚無 HEAD 或 Git 發生錯誤時會顯示未驗證警告。自動 gate 沒有 base ref，若回合內已提交變更，可能靜默跳過。二進位或無法讀取的未追蹤檔案、有未提交變更的 submodule，以及過大的 diff，無法由此 gate 審查。工作區變更後需重新審查；快照檢查後仍可能發生並行變更。Unknown、錯誤與逾時會放行並提示人工審查；阻擋達設定的 1 或 2 次後，再次 block 也會在未通過下放行。

Transfer 僅支援預設 Claude 設定目錄（`~/.claude`）；離線實測 Codex 0.166 的匯入偵測只搜尋 `HOME/.claude`，不搜尋自訂 `CLAUDE_CONFIG_DIR`。

## 背景委派限制

- Windows 不支援背景指令；前景委派仍可使用。手動檢查中，Ctrl+C 與 `/reload-plugins` 都沒有讓 broker 結束（macOS）。
- broker 死亡時工作會中斷而不會繼續，復原後標為 `interrupted`。清理是盡力而為：macOS `ps lstart` 只有秒級精度，可能遇到 PID 重用與 TOCTOU 時間窗口，呼叫 `setsid` 的孫程序也可能逃過清理。無法確認清理時標示 `possible_leftover`。完成通知僅盡力提供，且只會出現在發起工作的 session；其他 session 請用 `/model-mod:jobs` 與 `/model-mod:result` 查看。
- 沒有工作在執行時，背景 broker 閒置 30 分鐘後會自行結束；在此之前可能留有殘留的 broker 程序。
- 背景委派只支援預設帳號根目錄；自訂帳號根目錄請使用前景委派。`codexBin` 必須能在 broker 的環境中執行。
- write 模式下，Codex 可能執行命令並修改真實工作目錄，沒有自動備份；建議先 commit 或 stash。sandbox 限制 Codex 的命令與檔案寫入，不保證阻擋所有外部副作用；關閉網路的效果尚未跨平台驗證。
- Codex 啟動 workspace-write 時可能在帳號的 `config.toml` 記錄專案信任；model-mod 為 thread 指定不信任專案的覆寫，離線測試 Codex 0.166.0 時未留下持久信任紀錄。委派與圖片生成會拒絕已啟用或無法驗證的專案設定層，包括帳號原有信任所啟用的設定。寫入委派也會拒絕 thread 啟動後存在的工作目錄「已信任」專案紀錄；明確標為 `untrusted` 的紀錄會放行。若要移除信任，請在帳號的 Codex 設定中取消該專案的信任。
- 唯讀 sandbox 不限制讀取範圍，命令可能讀取工作區以外的檔案；這與上方 Messages bridge 停用內建 shell 的情況不同。
