# 設定

[English](CONFIGURATION.md) · [README](../README.zh-TW.md)

## 先準備好你的上游

你自己的上游需在 `/v1/messages` 提供 Messages 相容的串流 API，並備好 API 金鑰。已測試的上游是 CLIProxyAPI。上游若提供 `/v1/models`，setup 可自動探索模型；否則請手動輸入模型 ID。

model-mod 本身沒有模型。它把工作階段送往一個*上游*：接受 Messages 風格串流請求（`/v1/messages`）並驗證 API 金鑰的伺服器。安裝前：

1. **取得上游。** 已測試的是 CLIProxyAPI。依其文件安裝，並用你自己的供應商帳號登入；model-mod 不會安裝、啟動或設定它。
2. **確認它正在執行**，且從執行 Claude Code 的機器連得到。下列檢查讀取的是 `/model-mod:setup` 使用的同一份模型清單（請先在 shell 設好金鑰並換成你的位址）；回傳 `200` 表示位址與金鑰可用：

   ```bash
   printf 'header = "Authorization: Bearer %s"\n' "$UPSTREAM_API_KEY" | curl -s -o /dev/null -w '%{http_code}\n' -K - http://127.0.0.1:8317/v1/models
   ```

3. **找出 mod 需要的兩個值。** `baseUrl` 是伺服器位址，不含 `/v1`；CLIProxyAPI 預設監聽 8317 埠，所以預設 `baseUrl` 是 `http://127.0.0.1:8317`。上游若在別處執行，設定時請填它的位址。`apiKey` 是上游接受客戶端使用的金鑰（CLIProxyAPI 的金鑰定義在它自己的設定中），絕不是 Claude Code 訂閱的金鑰。

## 系統工具

需要 `curl` 與 `bash`。網頁擷取另需 `uname` 與系統 resolver（Linux 用 `getent`，macOS 用 `dscacheutil`）；圖片生成另需 `sed`、`grep`、`tr`、`mktemp`、`base64`。

## 插件選項

下列選項出現在設定對話框（`/plugin configure model-mod@model-mod`）。

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

進階選項不會出現在對話框，請寫在 Claude Code 設定檔 `pluginConfigs` 下該插件的 `options` 物件（鍵為 `model-mod@model-mod`；以 `--plugin-dir` 載入時為 `model-mod@inline`）。API 金鑰仍放在機密欄位。

| 進階選項 | 用途 | 預設值 |
|---|---|---|
| `maxTokens` | 以 `max_tokens` 送出。 | `32000` |
| `effortMode` | `suffix` 依目前 effort 等級送出 `model(level)`；`none` 送純模型 ID，適用於拒絕後綴的上游。 | `suffix` |
| `sideModel` | 選了你的模型時，Claude Code 自己的側請求所用的官方模型。`none` 不設定；環境中已有的值優先。 | `claude-haiku-5-5` |
| `keepThinking` | 在工具迴圈內交回 Codex 形式的加密推理簽章。上游不接受時設為 `false`。 | `true` |
| `localTitle` | 經你的上游依第一個提示命名工作階段。`false` 則把該提示送到官方 `sideModel`。 | `true` |
| `localContext` | 以 Claude Code 的本地估算回答 `/context`。`false` 則請訂閱端點計算 token。 | `true` |
| `toolSearch` | 延後載入大型 MCP 工具 schema：`auto`、`on`、`off`。 | `auto` |
| `toolSearchPercent` | `auto` 模式下，工具 schema 佔模型 context 視窗多少比例（1–90）時開始延後。 | `10` |

### 進階：外部設定檔

給腳本與測試環境使用：mod 可改從 JSON 檔讀取設定，不用插件選項。啟動 Claude Code 前，把環境變數 `MODEL_MOD_CONFIG` 設為該檔的絕對路徑。插件選項優先：只有選項中沒有設定 `apiKey` 時才會讀此檔；`apiKey` 若無法使用，mod 會停用，不會退回讀檔。mod 絕不讀取 Claude Code 自己的憑證檔。

檔案中不放 `apiKey`，而是指定 `headerFile`：一個給你的上游用的 HTTP 標頭行檔案（授權那一行），mod 以 `-H @file` 交給 curl。程序參數中只會出現該檔的路徑，不會出現金鑰本身。

| 鍵 | 用途 |
|---|---|
| `baseUrl`（必填） | 意義與檢查同 `baseUrl` 選項。 |
| `headerFile`（必填） | 上述標頭檔的絕對路徑。 |
| `models`（必填） | mod 負責回應的模型 ID 陣列。`[]`：上游列出的所有聊天模型。 |
| `maxTokens`（必填） | 以 `max_tokens` 送出的正整數。 |
| `toolsFile` | JSON 檔 `{"tools": [{"name", "description", "input_schema"}]}`，記錄 Claude Code 內建工具與其輸入 schema。未設定時，mod 以開放物件 schema 列出工具。 |
| `refresh` | `/model-mod:refresh` 執行來重寫 `toolsFile` 的指令：4 到 64 個字串的陣列，前兩項必須是絕對路徑（程式與其腳本）；不符合者會被忽略。 |
| `effortMode`、`imageModel`、`sideModel`、`keepThinking`、`localTitle`、`localContext`、`toolSearch`、`toolSearchPercent`、`promptsDir` | 與同名選項相同。檔案中的預設值不同：`effortMode` 除非設為 `suffix` 否則為 `none`，`imageModel` 沒有自動選擇（未設定時工具關閉），`sideModel` 沒有預設值。 |
| `contextWindows` | 物件，把 `models` 中的模型 ID 對應到其 context window（token，32000 到 4000000）。 |

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
