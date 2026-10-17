# model-mod

[English](README.md)

model-mod 是支援 mod 的程式開發客戶端所用的插件（mod）。它讓你把自己的 Messages 相容 API（例如 CLIProxyAPI 搭配自己登入的 Codex）的模型，放在客戶端內建模型旁邊使用。用 `/model-mod:model` 選你的模型，該工作階段就改走你的上游；用客戶端原本的 `/model` 選訂閱模型，則一切照舊。

## 特色

- 你的模型與訂閱模型並存，用 `/model-mod:model` 依工作階段切換。
- 訂閱模型、`ANTHROPIC_BASE_URL` 與 Remote Control 維持客戶端原本的連線。
- 串流、工具呼叫、Skills、MCP 伺服器、子代理與 Workflow agent 都能搭配你的模型。
- 提供給你的模型使用的網頁搜尋、網頁擷取、圖片生成與工具搜尋。
- 暫時性上游錯誤自動重試，並支援客戶端的五級 effort。
- 可選：訂閱用量達上限時，自動切換到你的模型。

## 需求

- 支援 mod 的客戶端。已在 2.1.299 至 2.1.301 測試；其他版本未測。見[限制說明](docs/LIMITATIONS.zh-TW.md#已測試版本)。
- 你自己的上游，需在 `/v1/messages` 提供 Messages 相容的串流 API，並備好 API 金鑰。已測試的上游是 CLIProxyAPI。上游若提供 `/v1/models`，setup 可自動探索模型；否則請手動輸入模型 ID。
- `curl` 與 `bash`。網頁擷取另需 `uname` 與系統 resolver（Linux 用 `getent`，macOS 用 `dscacheutil`）；圖片生成另需 `sed`、`grep`、`tr`、`mktemp`、`base64`。

## 先準備好你的上游

model-mod 本身沒有模型。它把工作階段送往一個*上游*：接受 Messages 風格串流請求（`/v1/messages`）並驗證 API 金鑰的伺服器。安裝前：

1. **取得上游。** 已測試的是 CLIProxyAPI。依其文件安裝，並用你自己的供應商帳號登入；model-mod 不會安裝、啟動或設定它。
2. **確認它正在執行**，且從執行客戶端的機器連得到。下列檢查讀取的是 `/model-mod:setup` 使用的同一份模型清單（請先在 shell 設好金鑰並換成你的位址）；回傳 `200` 表示位址與金鑰可用：

   ```bash
   printf 'header = "Authorization: Bearer %s"\n' "$UPSTREAM_API_KEY" | curl -s -o /dev/null -w '%{http_code}\n' -K - http://127.0.0.1:8317/v1/models
   ```

3. **找出 mod 需要的兩個值。** `baseUrl` 是伺服器位址，不含 `/v1`；CLIProxyAPI 預設監聽 8317 埠，所以預設 `baseUrl` 是 `http://127.0.0.1:8317`。上游若在別處執行，設定時請填它的位址。`apiKey` 是上游接受客戶端使用的金鑰（CLIProxyAPI 的金鑰定義在它自己的設定中），絕不是客戶端訂閱的金鑰。

## 安裝

前三行在 shell 執行，後兩行在客戶端的互動工作階段輸入。上游 API 金鑰請在設定對話框填入；它會當作機密儲存，不必在對話中輸入。

```text
claude plugin marketplace add chin-labs/model-mod
claude plugin install model-mod@model-mod
claude plugin configure model-mod@model-mod
/model-mod:setup
/model-mod:model
```

`/model-mod:setup` 會確認上游網址，並讓你選擇要提供哪些模型；`/model-mod:model` 隨後列出這些模型。設定完成後若插件尚未啟用，請執行 `/reload-plugins` 或重新啟動客戶端。

要從本機 clone 安裝，把 `chin-labs/model-mod` 換成 clone 的路徑。

不想用對話框時，可在儲存庫之外準備一個私密的單行 JSON 檔（例如 `{"apiKey": "...", "baseUrl": "..."}`），再執行：

```bash
chmod 600 /path/to/private-config.json
claude plugin configure model-mod@model-mod --values-stdin < /path/to/private-config.json
```

不要把金鑰放進 `--config` 參數（可能出現在程序列表），也不要貼進訊息。在組織管理的客戶端中，個人安裝的插件可能收不到所有 hook，除非組織把插件列入管理設定。

## 確認運作正常

執行 `/model-mod:setup` 之後：

1. 執行 `/model-mod:status`。mod 啟用時會回覆一行，例如 `model-mod <version>: picker=active; host=127.0.0.1; config=…; models=3; …`，其中 `models` 是提供的模型數。`model-mod: inactive; …` 表示沒有可用的金鑰或網址（見疑難排解）。若回覆是說明插件 hook 未載入的文字，代表插件在此工作階段尚未啟用：執行 `/reload-plugins` 或重新啟動客戶端。
2. 執行 `/model-mod:model`，選一個你的模型並送出一則短訊息。回答來自你的上游。上游停擺或拒絕金鑰時，該回合會以錯誤訊息結束，不會改用訂閱重試。

## 設定

下列選項出現在設定對話框（`claude plugin configure model-mod@model-mod`）。

只有 `apiKey` 與 `baseUrl` 是必要的：沒有金鑰 mod 就不啟用；除非上游正好在預設位址，否則要調整 `baseUrl`。其他選項都是選用。

| 選項 | 用途 | 預設值 |
|---|---|---|
| `baseUrl` | 你的上游基底網址，不含 `/v1`。僅限 HTTP／HTTPS；含帳密、查詢參數、fragment 的網址，以及 `anthropic.com`、`claude.ai` 主機會被拒絕。 | `http://127.0.0.1:8317` |
| `apiKey` | 你的上游 API 金鑰（機密）。未設定時 mod 不啟用。 | 無 |
| `models` | 以逗號分隔的模型 ID，mod 只接管這些。空白：上游列出的所有 chat 模型。 | 空白 |
| `imageModel` | `generate_image` 使用的模型。空白：`gpt-image-2`，或上游列出的第一個 `gpt-image*`。`none` 關閉此工具。 | 空白 |
| `contextWindow` | 對未知視窗大小的模型所假設的輸入 token 數（最小 32000）。 | `272000` |
| `fallbackModel` | 訂閱用量達上限時要切換到的模型。空白：不自動切換。 | 空白 |
| `fallbackPercent` | rate-limit 視窗用量達多少比例（50–100）時切換。僅在設定 `fallbackModel` 時有效。 | `100` |
| `workerModel` | `model-mod:local-worker` 代理類型使用的模型。空白：用 fallback 模型；兩者都空白則不提供 worker 代理類型。 | 空白 |
| `promptsDir` | 存放自訂 `compact.md`、`title.md`、`subagent-note.md`、`worker.md` 的絕對路徑目錄。空白：使用插件內的 `prompts/`。 | 空白 |

進階選項不會出現在對話框，請寫在客戶端設定檔 `pluginConfigs` 下該插件的 `options` 物件（鍵為 `model-mod@model-mod`；以 `--plugin-dir` 載入時為 `model-mod@inline`）。API 金鑰仍放在機密欄位。

| 進階選項 | 用途 | 預設值 |
|---|---|---|
| `maxTokens` | 以 `max_tokens` 送出。 | `32000` |
| `effortMode` | `suffix` 依目前 effort 等級送出 `model(level)`；`none` 送純模型 ID，適用於拒絕後綴的上游。 | `suffix` |
| `sideModel` | 選了你的模型時，客戶端自己的側請求所用的官方模型。`none` 不設定；環境中已有的值優先。 | `claude-haiku-5-5` |
| `keepThinking` | 在工具迴圈內交回 Codex 形式的加密推理簽章。上游不接受時設為 `false`。 | `true` |
| `localTitle` | 經你的上游依第一個提示命名工作階段。`false` 則把該提示送到官方 `sideModel`。 | `true` |
| `localContext` | 以客戶端的本地估算回答 `/context`。`false` 則請訂閱端點計算 token。 | `true` |
| `toolSearch` | 延後載入大型 MCP 工具 schema：`auto`、`on`、`off`。 | `auto` |
| `toolSearchPercent` | `auto` 模式下，工具 schema 佔模型 context 視窗多少比例（1–90）時開始延後。 | `10` |

### 進階：外部設定檔

給腳本與測試環境使用：mod 可改從 JSON 檔讀取設定，不用插件選項。啟動客戶端前，把環境變數 `MODEL_MOD_CONFIG` 設為該檔的絕對路徑。插件選項優先：只有選項中沒有設定 `apiKey` 時才會讀此檔；`apiKey` 若無法使用，mod 會停用，不會退回讀檔。mod 絕不讀取客戶端自己的憑證檔。

檔案中不放 `apiKey`，而是指定 `headerFile`：一個給你的上游用的 HTTP 標頭行檔案（授權那一行），mod 以 `-H @file` 交給 curl。程序參數中只會出現該檔的路徑，不會出現金鑰本身。

| 鍵 | 用途 |
|---|---|
| `baseUrl`（必填） | 意義與檢查同 `baseUrl` 選項。 |
| `headerFile`（必填） | 上述標頭檔的絕對路徑。 |
| `models`（必填） | mod 負責回應的模型 ID 陣列。`[]`：上游列出的所有聊天模型。 |
| `maxTokens`（必填） | 以 `max_tokens` 送出的正整數。 |
| `toolsFile` | JSON 檔 `{"tools": [{"name", "description", "input_schema"}]}`，記錄客戶端內建工具與其輸入 schema。未設定時，mod 以開放物件 schema 列出工具。 |
| `refresh` | `/model-mod:refresh` 執行來重寫 `toolsFile` 的指令：4 到 64 個字串的陣列，前兩項必須是絕對路徑（程式與其腳本）；不符合者會被忽略。 |
| `effortMode`、`imageModel`、`sideModel`、`keepThinking`、`localTitle`、`localContext`、`toolSearch`、`toolSearchPercent`、`promptsDir` | 與同名選項相同。檔案中的預設值不同：`effortMode` 除非設為 `suffix` 否則為 `none`，`imageModel` 沒有自動選擇（未設定時工具關閉），`sideModel` 沒有預設值。 |
| `contextWindows` | 物件，把 `models` 中的模型 ID 對應到其 context window（token，32000 到 4000000）。 |

`contextWindow`、`fallbackModel`、`fallbackPercent` 與 `workerModel` 只從插件選項讀取。

## 指令

| 指令 | 用途 |
|---|---|
| `/model-mod:setup` | 確認上游網址並選擇要提供的模型。取消不會更動設定。 |
| `/model-mod:model` | 列出你的模型並切換到所選的那個（↑↓ 移動、Enter 選取、Esc 關閉）。終端機太矮、或來自 Remote Control／手機時，改用分頁選單。 |
| `/model-mod:refresh` | 重新讀取提示檔與上游的模型清單。 |
| `/model-mod:status` | 顯示 mod 是否啟用、提供的模型數量及工具設定。 |
| `/model` | 客戶端原本的指令，維持不變：訂閱模型。直接輸入你的模型 ID（`/model <id>`）也可以。 |
| `/btw <question>` | 選了你的模型時，經你的上游以唯讀上下文回答，不使用工具。 |

要回到訂閱模型，使用 `/model`。

## 運作方式

mod 只替它管理的模型 ID 回答。設定了 `models` 時，管理範圍就是該清單；否則為上游的 chat 模型。含 `claude` 或 `anthropic` 的 ID 與客戶端的官方別名一律不管理，圖片、embedding、語音與 moderation 模型也不會被探索進來。其他模型照客戶端原本的路徑走。

對管理中的模型，對話、壓縮與 `/btw` 都送往你的上游，且**失敗時絕不退回訂閱**：上游出錯，該回合就以錯誤訊息結束。

## 你的模型能做什麼

- **串流與工具。** 文字與工具呼叫皆為串流。尚未收到任何輸出前，HTTP 429、502、503、504、529 與其他暫時性錯誤會在 2、6、15 秒後重試（最多三次）。輸出開始後串流中斷，該回合直接結束，不會重播。
- **內建工具、Skills 與 MCP。** 照常運作。工具輸入 schema 不會轉交，參數由客戶端自行驗證。
- **子代理與 Workflow。** 在訂閱工作階段中，可用 `model-mod:local-worker` 代理類型把工作交給你的模型（需設定 `workerModel` 或 `fallbackModel`），或讓 Workflow agent 指定 `model: "<你的模型 ID>"`。用你的模型的工作階段仍可委派給訂閱模型，該請求走訂閱。
- **網頁搜尋與擷取。** `web_search` 經你的上游執行。`web_fetch` 自行下載公開 HTTP(S) 頁面，每一跳都檢查所有 DNS 回答，拒絕私網與特殊用途位址（最多五次重新導向）。
- **圖片生成。** `generate_image` 呼叫上游的 `/v1/images/generations`，並把 PNG 存到工作目錄。需要圖片模型。
- **工具搜尋。** `tool_search` 用來找出 schema 被延後載入的 MCP 工具。
- **Effort。** 客戶端的五級（`low`、`medium`、`high`、`xhigh`、`max`）以模型後綴（如 `model(high)`）送出。Ultracode 是獨立的 workflow 開關，不改變等級。
- **壓縮。** `/compact` 與自動壓縮使用你的模型。摘要保留多少取決於模型，不是無損存檔。
- **圖片與 PDF。** 圖片會轉交。單頁 PDF 以圖片方式讀取。
- **Prompt cache。** 上游回報的快取用量會原樣帶回。
- **自動切換（預設關閉）。** 設定 `fallbackModel` 後，當某回合結束時訂閱用量已達 `fallbackPercent` 且重置時間在未來，工作階段會切到該模型並顯示通知，重置後再切回。它不會重送觸發上限的那一回合、不會重置任何限制，也不會在工具迴圈中或對子代理執行。手動換模型會取消切回。切換期間，你的對話會送往你的上游。

`web_search`、`web_fetch`、`generate_image`、`tool_search` 只提供給你的模型；選了訂閱模型時請改用客戶端內建工具。它們遵循客戶端的權限規則。模型的實際表現取決於模型本身；本插件不會讓它等同訂閱模型。

### 自訂提示

壓縮、標題、子代理與 worker 的提示放在插件 `prompts/` 目錄的 `compact.md`、`title.md`、`subagent-note.md`、`worker.md`。要用自己的版本，把 `promptsDir` 設為你的目錄（插件目錄內的檔案會在升級時被取代）。沒有內建後備：檔案缺少、為空、無法讀取或超過 8000 字元，都視為不可用。沒有 `compact.md` 時略過本地壓縮；沒有 `title.md` 時以提示的前 50 個字元當標題；沒有 `worker.md` 時不提供 worker 代理類型。`/model-mod:refresh` 會重新讀取這些檔案。

## 疑難排解

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
| 解除安裝後客戶端以無法使用的模型啟動 | 客戶端儲存了你最後一次選的模型 | 執行 `/model sonnet`，或從設定中移除已儲存的 `model` 項目。 |

## 更新

```bash
claude plugin marketplace update
claude plugin update model-mod@model-mod
```

然後重新啟動客戶端套用更新。只有新版本的 release 才會送到你這裡（見[變更紀錄](CHANGELOG.md)）。更新會取代已安裝插件目錄中的檔案，所以自訂提示詞請放在 `promptsDir` 指定的目錄；你的設定存放在插件目錄之外。

## 解除安裝

1. 先選訂閱模型（例如 `/model sonnet`）。客戶端會把互動式的模型選擇存成預設值，否則已儲存的本地預設值會在解除安裝後留下。
2. 在工作階段中執行 `/plugin uninstall model-mod@model-mod`，或在 shell 執行 `claude plugin uninstall model-mod@model-mod`，然後重新啟動。客戶端會保留插件快取。

## 限制、隱私與合規

- [限制說明](docs/LIMITATIONS.zh-TW.md)列出與訂閱模型的已知差異、尚未驗證的項目，以及哪些客戶端請求仍可能送到你的訂閱。
- 訊息、系統指示（含專案指示檔）、工具定義與結果、圖片都會送往你的上游及其背後的供應商。搜尋查詢送往上游，擷取的網址送往目標網站，圖片提示送往圖片端點。
- mod 使用插件 hook，不修改客戶端執行檔、不攔截 TLS、不讀取訂閱憑證檔，也不把訂閱憑證送往你的上游。它只使用你設定的上游金鑰，且絕不把你的模型的回合改走訂閱重試。
- Auto 權限模式會把完整對話與專案指示送到你的訂閱做分類，即使目前選的是你的模型。改用 default 或 acceptEdits 模式搭配 allow 規則即可避免。客戶端自己發出的其他請求也可能使用你的訂閱；見[訂閱側請求](docs/LIMITATIONS.zh-TW.md#訂閱側請求)。
- 金鑰透過環境變數而非命令參數交給 curl。錯誤訊息中的金鑰會被遮蔽，但串流輸出不會改寫，因此請使用你信任的上游。

本專案獨立運作，與 Anthropic 無隸屬關係，也未獲其背書。[合規說明](docs/COMPLIANCE.zh-TW.md)解釋設計限制，並附上現行條款供你自行閱讀。這些說明不代表條款已授權此用法；閱讀條款是你自己的責任。

## 開發

```bash
claude plugin validate .
claude plugin test .
```

原始碼匯入客戶端提供的模組，因此型別檢查與測試需要支援 mod 的客戶端。測試使用假憑證。要試用工作副本，以 `--plugin-dir .` 啟動客戶端。不要散布客戶端產生的 API 宣告或任何憑證。

## 問題回報與安全

- 錯誤與問題：[GitHub Issues](https://github.com/chin-labs/model-mod/issues)。歡迎提交 PR，但不保證回覆時間。
- Pull request：被接受的變更會在上游整合，並以發布快照的形式公開。本儲存庫的 `main` 分支只接收發布快照，所以 PR 可能不會在這裡合併，而是在關閉時附上包含該變更的 commit。
- 安全問題：請使用 GitHub 私密漏洞回報（儲存庫的 Security 分頁 → Report a vulnerability），不要在公開 Issue 貼漏洞細節。
- 回報不得包含金鑰、訂閱憑證、未遮蔽的逐字稿、私人路徑或內網端點。請附客戶端與插件版本、使用假憑證的最小重現，以及預期與實際結果。

## 社群出處

以下兩則連結僅供背景參考，未經專案驗證；不構成授權，使用條款仍以你自己閱讀的現行條款為準。

- https://x.com/thsottiaux/status/2076119366647894371
- https://x.com/thsottiaux/status/2093573575869698091

## 授權

[MIT](LICENSE)。
