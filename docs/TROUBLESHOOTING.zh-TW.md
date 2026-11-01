# 疑難排解

[English](TROUBLESHOOTING.md) · [README](../README.zh-TW.md)

## 確認運作正常

執行 `/model-mod:setup` 之後：

1. 執行 `/model-mod:status`。mod 啟用時會輸出一份報告，第一行是 `model-mod <version>: picker=active`（有警告時後接 `; N warnings`），接著是 QUOTA、CURRENT PATH 與 DIAGNOSTICS。DIAGNOSTICS 的 Picker 群組顯示 `picker active` 與 `models`（提供的模型數），有 API 上游時還有 `host` 與 `config`；設定 Codex 登入後，每個帳號多一個群組。`model-mod: inactive; …` 表示沒有可用的上游設定（見下方[常見症狀](#症狀)）。若回覆是說明插件 hook 未載入的文字，代表插件在此工作階段尚未啟用：執行 `/reload-plugins` 或重新啟動 Claude Code。
2. 若有問題，執行 `/model-mod:doctor`。它不送出提示，也不消耗 Codex 額度或模型 token；它會檢查以金鑰設定的 API 模型清單，以及每個 Codex 帳號的登入與額度。不會檢查 header file 上游，也不能保證聊天請求一定成功。
3. 執行 `/model-mod:model`，選一個你的模型並送出一則短訊息。回答來自你的上游。上游停擺或拒絕金鑰時，該回合會以錯誤訊息結束，不會改用訂閱重試。

## 症狀

| 症狀 | 可能原因 | 處理方式 |
|---|---|---|
| 狀態顯示 `inactive`，或沒有列出模型 | 沒有有效的上游設定、網址被拒絕，或插件未載入 | 設定 Codex 帳號與模型，或設定 API 金鑰與允許的網址，執行 `/reload-plugins`，再執行 `/model-mod:setup`。 |
| 帳號區塊標示 `[LIMIT]` | 某個視窗已用 100%，或帳號回報 rate limit（原因寫在該區塊） | 等到顯示的重置時間，或改用其他帳號或 `fallbackModel`。 |
| 帳號區塊顯示 `無法取得: …` | 額度查詢沒有完成：未登入、找不到 `codex` 或逾時 | 看原因，再看 DIAGNOSTICS 中該帳號的 `login` 與 `codex` 列；其他帳號不受影響。 |
| API 上游顯示 `沒有額度資料` | API 伺服器不回報額度 | 屬正常現象，不需處理。 |
| setup pane 顯示 `Keyboard not captured` | pane 沒有取得鍵盤 | 按 Ctrl+X，再按 Tab。 |
| `setup is already open; finish or close it first.` | 先前 `/model-mod:setup` 的 pane 仍開著 | 完成該次 setup，或在 pane 內按 Esc。 |
| setup 時出現模型清單錯誤 | 網路、驗證或伺服器問題 | 檢查上游與金鑰。明確設定 `models` 可略過探索繼續進行。 |
| Doctor 回報連線遭拒、DNS、逾時或 TLS 錯誤 | API 網址或網路無法連線 | 檢查網址、網路和 TLS 憑證。 |
| Doctor 回報 401 或 403 | API 金鑰遭拒 | 檢查插件設定中的金鑰。 |
| Doctor 回報 404 | API 基礎網址可能多了或少了 `/v1` | 將基礎網址設為不含 `/v1` 的形式。 |
| Doctor 回報 429 或 5xx | API 受限流或伺服器發生錯誤 | 稍後再試。 |
| Doctor 回報模型清單無效或為空 | 伺服器可能不相容 OpenAI | 檢查上游伺服器及其模型端點。 |
| `model is not in the allowlist` | 該 ID 不在 `models` 內 | 選擇允許的 ID，或更新清單。 |
| 選了模型後出現錯誤 | 模型不可用、上游停機或金鑰被拒絕 | 修正上游、模型或金鑰，再執行 `/model-mod:refresh`。不會退回訂閱。 |
| effort 後綴被拒絕 | 上游不認得 `model(level)` | 把進階選項 `effortMode` 設為 `none`。 |
| 圖片工具不存在或被拒絕 | 未選本地模型、API 圖片模型未設定、權限遭拒，或 Codex 登入、額度或圖片功能不可用 | 選擇已設定的模型並允許請求。API 模型需設定 `imageModel`；Codex 使用內建圖片模型。Codex 失敗時請檢查登入、額度與 CLI 版本。圖片超過 20 MiB 時請求較小的圖片；輸出路徑已存在或位於工作目錄外時請換路徑。 |
| `web_fetch` 拒絕某網址 | 不是 HTTP(S)，或目的地是私網 | 改用公開的 HTTP(S) 網址。 |
| 太早壓縮，或長輸入被拒絕 | 假設的視窗與模型實際視窗不同 | 調整 `contextWindow`。 |
| 上游正常，但 auto 權限模式下動作被擋 | 分類器跑在你的訂閱上且失敗 | 改用 default 或 acceptEdits 模式搭配 allow 規則。 |
| 解除安裝後 Claude Code 以無法使用的模型啟動 | Claude Code 儲存了你最後一次選的模型 | 執行 `/model sonnet`，或從設定中移除已儲存的 `model` 項目。 |

## Codex 登入

| 症狀 | 處理方式 |
|---|---|
| 尚未登入或帳號目錄不存在 | 執行 `/model-mod:setup` 並選 Codex login，依顯示的網址與代碼完成裝置驗證，登入後選 Continue。若 setup 無法取得網址或代碼，請依顯示的終端機命令手動登入，再重新執行 setup；Windows 會顯示 PowerShell 命令。 |
| `model is not in the allowlist; configure codexAccountsDir` | 無法決定帳號目錄，因而排除 Codex 模型 ID。請設定絕對路徑 `codexAccountsDir`，或確認 `HOME` 或 `APPDATA` 可供決定預設目錄；必要時建立帳號目錄並登入，再重新載入插件。 |
| Codex 版本過舊 | 將官方 CLI 升級至至少 0.165.0，再重試。 |
| helper 無法啟動 | 安裝 Python 3.9 以上版本並檢查 `pythonBin`，也檢查 `codexBin` 與 `codexAccountsDir` 路徑。執行檔須為命令名稱或絕對路徑。 |
| `Codex used a built-in tool that model-mod does not support` | helper 遇到不支援的項目時會終止回合。重試前請檢查 Codex 版本及有效設定。見[限制說明](LIMITATIONS.zh-TW.md#codex-登入的限制)。 |
| `incompatible app-server protocol; update or check Codex` | 升級或檢查 Codex 及其有效設定後再重試。 |
| 工具名稱顯示為 `bridge_` 加雜湊 | `mcp__...` 等保留名稱及不符合 Codex 格式的名稱，在呼叫 Codex 時會轉成別名，回傳時還原。見[限制說明](LIMITATIONS.zh-TW.md#codex-登入的限制)。 |
| 429、額度或速率限制 | 查看你的 Codex 訂閱額度與重置時間。尚未輸出前，重試會遵循最多 15 秒的 `Retry-After`；要求等待更久時直接結束回合。不會自動輪替帳號。 |
| Transfer 拒絕自訂 `CLAUDE_CONFIG_DIR` | Transfer 僅支援預設 `~/.claude` 目錄；實測 Codex 0.166 匯入偵測搜尋 `HOME/.claude`。請取消自訂設定，並使用預設目錄中的工作階段。 |
| 帳號設定被拒且回復失敗 | 開啟 `/plugin configure model-mod@model-mod`，手動將 `codexModels` 還原成先前的值，也檢查 `codexAccounts`；需要時再執行 setup。 |

若 setup 無法顯示裝置驗證網址與代碼，請依顯示的命令操作，或自行建立帳號目錄並執行 `CODEX_HOME=<codexAccountsDir>/<帳號> codex login --device-auth`。Windows 請在 PowerShell 設定各帳號專用的 `CODEX_HOME`。之後重新執行 setup。

在 setup 的 **Manage configured upstreams** 中，**Log out** 會保留設定及帳號目錄；**Remove** 會移除設定並預設保留目錄，除非另行確認刪除。刪除範圍僅限該帳號目錄，並會先嘗試登出。若登出後憑證仍在，目錄與設定會保留；請執行顯示的登出命令再重試。若目前仍選著已移除的模型，請用 `/model` 改選。由檔案提供的 API 須自行編輯設定檔移除。移除 API 會停用上游，但金鑰仍留在客戶端的安全儲存中，model-mod 無法清除；重新加入時 setup 會先確認要把已存金鑰送往哪個主機。

## 更新

```bash
claude plugin marketplace update
claude plugin update model-mod@model-mod
```

然後重新啟動 Claude Code 套用更新。只有新版本的 release 才會送到你這裡（見[變更紀錄](../CHANGELOG.md)）。更新會取代已安裝插件目錄中的檔案，所以自訂提示詞請放在 `promptsDir` 指定的目錄；你的設定存放在插件目錄之外。

## 解除安裝

1. 先選訂閱模型（例如 `/model sonnet`）。Claude Code 會把互動式的模型選擇存成預設值，否則已儲存的本地預設值會在解除安裝後留下。
2. 在工作階段中執行 `/plugin uninstall model-mod@model-mod`，或在 shell 執行 `claude plugin uninstall model-mod@model-mod`，然後重新啟動。Claude Code 會保留插件快取。
