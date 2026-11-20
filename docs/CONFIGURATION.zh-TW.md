# 設定

[English](CONFIGURATION.md) · [README](../README.zh-TW.md)

## 選擇上游

Codex 登入是主要路徑；已有的 Messages 相容 API 伺服器是替代選擇，兩者也可並存。使用 Codex 時，先安裝 Python 3.9 以上版本與官方 `codex` CLI，再執行 `/model-mod:setup` 並選 **Codex login**。需要登入時，setup 會建立專用帳號目錄並執行 `codex login --device-auth`。請開啟顯示的網址、輸入代碼，選 **Continue (after logging in)**，再選模型。若無法取得網址，setup 會改顯示手動終端機命令。使用 API 伺服器時，請依下一節準備，並在 setup 選 **Compatible API server**。

在 setup 選 **Manage configured upstreams** 可登出或移除 Codex 帳號，也可移除插件選項中的 API。登出會保留帳號設定與目錄；移除預設保留目錄，若要刪除須再次確認，且只刪該帳號目錄。由 `MODEL_MOD_CONFIG` 提供的 API 須自行編輯該檔移除。移除 API 會停用上游，但金鑰仍留在客戶端的安全儲存中，model-mod 無法清除；重新加入時 setup 會先確認要把已存金鑰送往哪個主機。

## 先準備好你的上游

你自己的上游需在 `/v1/messages` 提供 Messages 相容的串流 API，並備好 API 金鑰。 CLIProxyAPI 是曾測試過的一例上游。上游若提供 `/v1/models`，setup 可自動探索模型；否則請手動輸入模型 ID。

API 伺服器路徑會把工作階段送往接受 Messages 風格串流請求（`/v1/messages`）並驗證 API 金鑰的伺服器。安裝前：

1. **使用你的上游。** 可使用相容伺服器；CLIProxyAPI 是曾測試過的一例。model-mod 不會安裝、啟動或設定伺服器。
2. **確認它正在執行**，且從執行 Claude Code 的機器連得到。下列檢查讀取的是 `/model-mod:setup` 使用的同一份模型清單（請先在 shell 設好金鑰並換成你的位址）；回傳 `200` 表示位址與金鑰可用：

   ```bash
   printf 'header = "Authorization: Bearer %s"\n' "$UPSTREAM_API_KEY" | curl -s -o /dev/null -w '%{http_code}\n' -K - http://127.0.0.1:8317/v1/models
   ```

3. **找出 mod 需要的兩個值。** `baseUrl` 是伺服器位址，不含 `/v1`；CLIProxyAPI 預設監聽 8317 埠，所以預設 `baseUrl` 是 `http://127.0.0.1:8317`。上游若在別處執行，設定時請填它的位址。`apiKey` 是上游接受客戶端使用的金鑰（CLIProxyAPI 的金鑰定義在它自己的設定中），絕不是 Claude Code 訂閱的金鑰。

## 系統工具

需要 `curl` 與 `bash`。網頁擷取另需 `uname` 與系統 resolver（Linux 用 `getent`，macOS 用 `dscacheutil`）；API 圖片生成另需 `sed`、`grep`、`tr`、`mktemp`、`ln`、`base64`；Codex 圖片生成使用 Python 與官方 Codex CLI。

## 插件選項

設定對話框（`/plugin configure model-mod@model-mod`）顯示八個選項：下方前五個，以及 Codex 登入選項中的 `codexAccounts`、`codexModels` 與 `codexBin`。其餘選項列在[進階選項](#進階選項)。

有效的 `apiKey` 或有效的 `codexAccounts` 與 `codexModels` 組合，任一即可啟用 mod；兩者可並存。無效的 API 金鑰只停用 API 端，不會停用有效的 Codex 設定。使用 API 路徑且伺服器不在預設位址時，請調整 `baseUrl`。

| 選項 | 用途 | 預設值 |
|---|---|---|
| `baseUrl` | 你的上游基底網址，不含 `/v1`。僅限 HTTP／HTTPS；含帳密、查詢參數、fragment 的網址，以及 `anthropic.com`、`claude.ai` 主機會被拒絕。 | `http://127.0.0.1:8317` |
| `apiKey` | API 上游的金鑰（機密）。API 路徑需要此欄位。 | 無 |
| `models` | 以逗號分隔的模型 ID，mod 只接管這些。空白：上游列出的所有 chat 模型。 | 空白 |
| `fallbackModel` | 訂閱或 Codex 登入額度達上限時切換的模型；不會輪流換帳號，同帳號不可作為備援。空白：不自動切換。客戶端會把這次切換存成新工作階段的預設模型。 | 空白 |
| `workerModel` | `model-mod:local-worker` 代理類型使用的模型。空白：用 fallback 模型；兩者都空白則不提供 worker 代理類型。 | 空白 |

### Codex 登入選項

| 選項 | 格式與預設值 |
|---|---|
| `codexAccounts` | 以逗號分隔帳號名稱，預設空白。每個名稱 1–32 字元，首字元為 `[a-z0-9]`，其餘使用 `[a-z0-9-]`。由 `/model-mod:setup` 寫入。 |
| `codexModels` | 以逗號分隔模型名稱，預設空白。每個名稱 1–64 字元，首字元為 `[A-Za-z0-9]`，其餘使用 `[A-Za-z0-9._-]`；含 `claude` 或 `anthropic` 的名稱不分大小寫均會拒絕。由 `/model-mod:setup` 寫入。Codex 新提供的模型必須先將 ID 加到此清單才能選用；可直接加入，或重新執行 `/model-mod:setup` 並選取完整的模型清單（setup 會取代整份清單）。 |
| `codexBin` | 執行檔名稱或絕對路徑；預設 `codex`。 |

Codex effort 依模型宣告的等級夾值：`max` 取支援的最高等級；不支援的明設等級取不高於它的最高支援等級，若沒有較低等級則取最低。絕不送出 `minimal`。未明設時，需要調整會採用模型支援的預設值。

`/model-mod:review --adversarial` 支援焦點文字與 effort；`--gate` 要求結構化裁定。Stop gate 由 `codexStopGate` 與 `codexStopGateBlocks` 獨立設定；見[審查關卡](FEATURES.zh-TW.md#codex-審查關卡)。

原生搜尋與 openPage 在 OpenAI 端執行，不受 Claude 權限的網域規則（allowed／blocked domains）限制；model-mod 不做 `allowed_domains` 的安全宣稱。查詢文字會送往 OpenAI。

路徑與命令不得包含 NUL 或換行；單純命令名稱只能包含英文字母、數字、`.`、`_`、`-`。帳號與模型組成 ID `<帳號>/<模型>`，顯示為 `<模型> @ <帳號>`。每個帳號都會搭配每個已設定的模型。API 模型 ID 相同時，Codex 優先。`/model-mod:setup` 會合併並去除重複帳號，但會以選定模型**覆寫整個**適用於所有帳號的 `codexModels` 設定；新增帳號時請重新選取完整所需模型清單。`fallbackModel` 與 `workerModel` 可指向有效的 Codex ID。使用 Codex 登入時，若只有一個已設定帳號擁有該模型，可直接使用模型 ID；若有多個帳號，請指定 `<account>/<model>`。

### 進階選項

這些選項不會出現在對話框，請寫在 Claude Code 設定檔 `pluginConfigs` 下該插件的 `options` 物件（鍵為 `model-mod@model-mod`；以 `--plugin-dir` 載入時為 `model-mod@inline`），然後重新啟動 Claude Code。寫在那裡的值在插件更新後仍會保留。API 金鑰仍放在機密欄位。

```json
{
  "pluginConfigs": {
    "model-mod@model-mod": {
      "options": {
        "contextWindow": 200000,
        "codexWebSearch": "off"
      }
    }
  }
}
```

數字請寫成 JSON 數字。`maxTokens`、`contextWindow` 與 `fallbackPercent` 寫成加引號的數字（`"80"`）時也會當作該數字讀取；`codexStopGateBlocks` 也接受 `"1"` 或 `"2"`。數字選項裡的其他文字會被忽略（`codexStopGateBlocks` 會顯示為無效）。其餘進階選項使用表中所列的文字值。

| 進階選項 | 用途 | 預設值 |
|---|---|---|
| `imageModel` | API 路徑的 `generate_image` 圖片模型。空白：先前的 session 找到並保存的圖片模型，沒有的話用 `gpt-image-2`，或上游列出的第一個 `gpt-image*`。`none` 關閉 API 圖片路徑；Codex 使用內建圖片模型，不受此設定影響。 | 空白 |
| `contextWindow` | 對未知視窗大小的模型所假設的輸入 token 數（最小 32000）。明設的值會覆寫 Codex 模型目錄視窗（見[限制](LIMITATIONS.zh-TW.md#codex-登入的限制)）。 | `272000`（API）；目錄有效視窗或 128,000（Codex） |
| `fallbackPercent` | rate-limit 視窗用量達多少比例（50–100）時切換。僅在設定 `fallbackModel` 時有效。 | `100` |
| `promptsDir` | 存放自訂 `compact.md`、`title.md`、`subagent-note.md`、`worker.md` 的絕對路徑目錄。空白：使用插件內的 `prompts/`。 | 空白 |
| `codexAccountsDir` | 絕對目錄；每個帳號使用獨立子目錄。 | `~/.config/model-mod/accounts`，Windows 為 `%APPDATA%\model-mod\accounts`（未驗證） |
| `pythonBin` | 執行檔名稱或絕對路徑。Windows 請設為 `python`（未驗證）。 | `python3` |
| `codexThreadReuse` | `on`、`true`、`1` 或 `off`、`false`、`0`（文字不分大小寫）；無效值視為 `on` 並顯示於 status。關閉時使用 ephemeral thread，不存取父 thread 登錄；見[隱私與清理](LIMITATIONS.zh-TW.md#父-thread-隱私與清理)。 | `on` |
| `codexKeepReasoning` | `on`、`true`、`1` 或 `off`、`false`、`0`（文字不分大小寫）；無效值視為 `on` 並顯示於 status。使用實驗性 API；真實 Codex 重放尚未驗證。thread 重用的 fork 請求不保留 reasoning；若要保留，請將 `codexThreadReuse` 設為 `off`。 | `on` |
| `codexServiceTier` | `default` 或 `priority`；實際服務層級與計費尚未驗證。 | `default` |
| `codexWebSearch` | `on`、`true`、`1` 或 `off`、`false`、`0`（文字不分大小寫）；無效值視為 `on` 並顯示於 status。工作階段工具清單沒有 WebSearch 時會停用搜尋。 | `on` |
| `codexStopGate` | `off` 或 `on`，不分大小寫；無效值視為 `off` 並顯示於 status。開啟後可能在主工作階段回合結束時啟動唯讀 Codex 審查、把 diff 與未追蹤且未被忽略的檔案全文送往 OpenAI 並阻擋結束（Git 忽略的未追蹤檔案不會送出，例外見[委派與資料流](FEATURES.zh-TW.md#委派與資料流)）。 | `off` |
| `codexStopGateBlocks` | 每個工作階段最多阻擋 `1` 次或 `2` 次；其他無效值視為 `1` 並顯示於 status。達上限後未通過的結果會放行並提示人工審查。 | `1` |
| `maxTokens` | 以 `max_tokens` 送出。若不是正整數（`0`、負數或小數）會被忽略並使用預設值。 | `32000` |
| `effortMode` | 僅適用 API 路徑：`suffix` 依目前 effort 等級送出 `model(level)`；`none` 送純模型 ID，適用於拒絕後綴的上游。 | `suffix` |
| `sideModel` | 選了你的模型時，Claude Code 自己的側請求所用的官方模型。`none` 不設定；環境中已有的值優先。 | `claude-haiku-5-5` |
| `keepThinking` | 僅在 API 路徑的工具迴圈內交回 Codex 形式的加密推理簽章。上游不接受時設為 `false`（或 `off`、`0`）。 | `true` |
| `localTitle` | 經你的上游依第一個提示命名工作階段。`false`（或 `off`、`0`）則把該提示送到官方 `sideModel`。 | `true` |
| `localContext` | 以 Claude Code 的本地估算回答 `/context`。`false`（或 `off`、`0`）則請訂閱端點計算 token。 | `true` |
| `toolSearch` | 延後載入大型 MCP 工具 schema：`auto`、`on`、`off`。 | `auto` |
| `toolSearchPercent` | `auto` 模式下，工具 schema 佔模型 context 視窗多少比例（1–90）時開始延後。 | `10` |

`/model-mod:status` 以 `model-mod <version>: picker=active` 開頭（有警告時附警告數），接著依序是 QUOTA、CURRENT PATH 與 DIAGNOSTICS。`rate-limits` 提供各視窗比例、重置時間與 credits；`account-info` 在可取得時提供方案。

每個 Codex 帳號區塊會就各 rate-limit 視窗（通常是 5 小時與每週）顯示用量條、已用百分比與重置時間（相對時間，括號內為本地時間），另有 credits、方案及 `ordinaryUsageAllowed`；取得不到的欄位顯示 unavailable。讀不到的帳號顯示 `無法取得` 與原因，其他帳號不受影響。Codex 額度最多每帳號五分鐘查一次，額度錯誤可立即查詢；沒有可用的未來重置時間時不自動切換。API 上游沒有官方 rateLimits，不適用此機制。額度用完不會自動輪流換帳號，可設定不同上游或帳號的 `fallbackModel`。

`codexServiceTier` 可設 `default`（預設）或 `priority`；非法值視為 `default`。`priority` 需要 Codex 方案支援，可能較快回應但較快耗用額度；實際層級與計費是否生效未驗證。

### 進階：外部設定檔

給腳本與測試環境使用：mod 可改從 JSON 檔讀取設定，不用插件選項。啟動 Claude Code 前，把環境變數 `MODEL_MOD_CONFIG` 設為該檔的絕對路徑。插件選項優先：只有插件選項沒有可用的上游設定時才會讀檔；`apiKey` 若無法使用，mod 會停用，不會退回讀檔。mod 絕不讀取 Claude Code 自己的憑證檔。

檔案中不放 `apiKey`，而是指定 `headerFile`：一個給你的上游用的 HTTP 標頭行檔案（授權那一行），mod 以 `-H @file` 交給 curl。程序參數中只會出現該檔的路徑，不會出現金鑰本身。

| 鍵 | 用途 |
|---|---|
| `baseUrl`（必填） | 意義與檢查同 `baseUrl` 選項。 |
| `headerFile`（必填） | 上述標頭檔的絕對路徑。 |
| `models`（必填） | mod 負責回應的模型 ID 陣列。`[]`：檔案不提供任何模型，只回應先前工作階段記住的模型，且檔案模式從不取得上游清單。 |
| `maxTokens`（必填） | 以 `max_tokens` 送出的正整數。 |
| `toolsFile` | JSON 檔 `{"tools": [{"name", "description", "input_schema"}]}`，記錄 Claude Code 內建工具與其輸入 schema。未設定時，mod 以開放物件 schema 列出工具。 |
| `effortMode`、`imageModel`、`sideModel`、`keepThinking`、`localTitle`、`localContext`、`toolSearch`、`toolSearchPercent`、`promptsDir` | 與同名選項相同。檔案中的預設值不同：`effortMode` 除非設為 `suffix` 否則為 `none`，`imageModel` 沒有自動選擇（未設定時 API 圖片路徑關閉），`sideModel` 沒有預設值。 |
| `contextWindows` | 物件，把 `models` 中的模型 ID 對應到其 context window（token，32000 到 4000000）。 |

提示檔變更後，請重新啟動 Claude Code 才會生效。插件選項模式會在工作階段開始時讀取上游模型清單，因此上游新列出的聊天模型，只有在選項未設 `models` 清單時，重新啟動後才會加入（設了 `models` 清單時不加入取得的聊天模型）；檔案模式從不取得清單。使用 `/model-mod:status` 和 `/model-mod:doctor` 查看 Codex 狀態。改過的選項需 `/reload-plugins` 才會生效。

`contextWindow`、`fallbackModel`、`fallbackPercent` 與 `workerModel` 只從插件選項讀取。

## 其他安裝與設定方式

要從本機 clone 安裝，把 `chin-labs/model-mod` 換成 clone 的路徑。

在 Claude Code 的互動工作階段中，用 `/plugin configure model-mod@model-mod` 設定插件。shell 指令 `claude plugin configure model-mod@model-mod` 會列出選項及尚未設定的項目，不會開啟互動對話框。

不想用對話框時，可在儲存庫之外準備一個私密的單行 JSON 檔（例如 `{"apiKey": "...", "baseUrl": "..."}`），再執行：

```bash
chmod 600 /path/to/private-config.json
claude plugin configure model-mod@model-mod --values-stdin < /path/to/private-config.json
```

不要把金鑰放進 `--config` 參數（可能出現在程序列表），也不要貼進訊息。在組織管理的 Claude Code 中，個人安裝的插件可能收不到所有 hook，除非組織把插件列入管理設定。

## 背景工作儲存與限制

SessionStart hook 會啟動本機 broker。所有 session 關閉後，閒置的 broker 最多仍存活 30 分鐘。最多保留 50 個工作；新增第 51 個時會先淘汰最舊的終態紀錄與結果，但標為 `possible_leftover` 的紀錄最後才淘汰；若沒有終態紀錄則拒絕新增；每個帳號最多兩個執行中、五個排隊中，且最多一個未終態的 write 工作。背景執行總時限為 30 分鐘、無活動時限為五分鐘；前景分別為五分鐘及兩分鐘。使用 `/model-mod:jobs --clear` 可立即移除目前工作區已完成的工作與結果。

工作輸出保存在本機 `$XDG_STATE_HOME/model-mod/delegate/v1`；未設定 `XDG_STATE_HOME` 時改用 XDG 預設的 state 目錄（目錄權限 0700、檔案 0600）。結果可能含有你的 prompt 或程式碼片段：遮罩只對長度至少 32 字元的 prompt 或 diff 作精確字串比對，無法識別模型改寫的內容。超過七天的已完成紀錄會在背景 broker 下次啟動時移除，broker 執行期間約每小時再清一次，並非定時器；在那之前仍留在磁碟上。刪除本機紀錄不會刪除 Codex 自己的 thread 或 provider 端紀錄。狀態紀錄本身不儲存 prompt、diff、思考、帳號目錄路徑或環境變數。
