# model-mod

在 Claude Code 中使用你自己的 Codex 登入或 API 模型。

[![Version](https://img.shields.io/github/v/release/chin-labs/model-mod)](https://github.com/chin-labs/model-mod/releases)
[![License](https://img.shields.io/github/license/chin-labs/model-mod)](LICENSE)
[![Claude Code plugin](https://img.shields.io/badge/Claude_Code-plugin-gray)](https://code.claude.com/docs/en/plugins)

[English](README.md)

model-mod 是供 Claude Code 使用的插件（mod），讓你把自己的 Codex 登入或 Messages 相容 API 模型放在內建模型旁邊。兩種上游可同時設定。用 `/model-mod:model` 選你的模型，該工作階段就改走你的上游；用 `/model` 回到訂閱模型。訂閱模型、`ANTHROPIC_BASE_URL` 與 Remote Control 維持 Claude Code 原本的連線。

## 需求

- 支援 mod 的 Claude Code：Codex 登入與 API 上游已在 **Claude Code 2.1.314** 測試；API 上游也曾在 2.1.299 至 2.1.310 測試。另在一台 Mac 上以 2.1.316 搭配 Codex 0.166.0 做過手動端到端檢查。其他版本未測。
- Codex 登入：Python 3.9 以上版本及已安裝的 `codex` CLI（最低支援版本 0.165.0；更舊版本會被拒絕）。Codex context 視窗取自帳號模型目錄（套用有效比例），讀不到時退回 128,000 token；`contextWindow` 可覆寫。或使用你自己已啟動的 Messages 相容 API 與其金鑰；CLIProxyAPI 是曾測試過的一例 API 上游，model-mod 不會安裝或啟動該伺服器。
- `curl` 與 `bash`；網頁擷取與圖片生成另需[設定說明](docs/CONFIGURATION.zh-TW.md#系統工具)列出的系統工具。

## 快速開始

Codex 登入是主要路徑。先安裝 Python 3.9 以上版本與官方 `codex` CLI，再於 Claude Code 互動工作階段中執行：

```text
/plugin marketplace add chin-labs/model-mod
/plugin install model-mod@model-mod
```

若 `/model-mod:setup` 沒反應或提示 hooks 未載入，請先執行 `/reload-plugins`。接著執行：

```text
/model-mod:setup
/model-mod:model
```

選擇 **Codex login** 與帳號；若系統要求登入，開啟顯示的網址、輸入一次性代碼，再選 **Continue (after logging in)**。選擇模型。setup 會建立帳號目錄並寫入帳號與模型設定；此路徑不需要 `/plugin configure`。代碼約 15 分鐘後失效；手動登入方式見[疑難排解](docs/TROUBLESHOOTING.zh-TW.md)。

若已有 [Messages 相容 API 伺服器](docs/CONFIGURATION.zh-TW.md#先準備好你的上游)，也可先用 `/plugin configure model-mod@model-mod` 設定 `baseUrl` 與 `apiKey`，再執行 `/model-mod:setup` 並選 **Compatible API server**。金鑰會當作機密儲存，不必輸入對話。兩種上游可並存。本機 clone 或私密設定檔用法見[其他安裝與設定方式](docs/CONFIGURATION.zh-TW.md#其他安裝與設定方式)。

首次檢查：

- hooks 未載入：執行 `/reload-plugins` 或重新啟動 Claude Code。
- 尚未登入：重新執行 `/model-mod:setup` 完成裝置登入，或依錯誤訊息中的終端機指令登入。
- `codex` 不在 `PATH`：安裝官方 CLI 或設定 `codexBin`，再重試 setup。
- `model-mod: Codex login: device code expired; run /model-mod:setup again to get a new code.`：重新執行 setup。
- `model-mod: no local models. Run /model-mod:setup to add them.`：執行 setup 並選模型；用 `/model-mod:status` 檢查是否啟用。

選模型後送一則短訊息。上游出錯時，該回合以錯誤訊息結束，絕不改走訂閱重試。

## 特色

- 你的模型與訂閱模型並存，用 `/model-mod:model` 依工作階段切換。
- 支援串流、工具呼叫、Skills、MCP 伺服器、子代理與 Workflow agent。
- Codex 登入使用原生網頁搜尋（`codexWebSearch`）及僅支援 POSIX 的圖片生成；API 路徑使用 mod 的搜尋、擷取及圖片生成工具。Codex 也可使用網頁擷取與工具搜尋。
- 暫時性上游錯誤自動重試，採用有上限的 `Retry-After` 處理，並支援 Claude Code 的五級 effort。
- 以你選的模型壓縮上下文；訂閱或 Codex 登入額度達上限時，可選擇切換至 `fallbackModel`，不會自動輪流更換帳號；API 上游模型沒有官方額度切換機制。

## 指令

| 指令 | 用途 |
|---|---|
| `/model-mod:setup` | 設定上游並選擇模型，或管理已設定的上游。取消設定流程不會更動設定。 |
| `/model-mod:model` | 列出你的模型並切換到所選的那個（↑↓ 移動、Enter 選取、Esc 關閉）。終端機太矮、或來自 Remote Control／手機時，改用分頁選單。 |
| `/model-mod:refresh` | 重新載入提示檔並檢查 Codex 登入狀態、CLI 版本與額度。若已設定 schema 更新命令，則執行該命令更新工具 schema（此分支不顯示 Codex 狀態）；否則顯示 Codex 狀態，並在已設定 API 金鑰時更新 API 模型清單。改過的選項需 `/reload-plugins` 才會生效。 |
| `/model-mod:status` | 顯示是否啟用、模型數量及工具設定。回送位址顯示主機名，其他主機顯示 `host=remote`；明文 HTTP 將 API 金鑰以未加密形式送至非回送主機時會提出警告。 |
| `/model-mod:review` | 請 Codex 審查；`--gate` 要求結構化裁定、`--adversarial` 審查 diff，`--background` 啟動背景工作。 |
| `/model-mod:rescue` | 向 Codex 求助；`--write` 要求工作區寫入權限，`--background` 啟動背景工作。 |
| `/model-mod:jobs` | 列出或清除背景工作。 |
| `/model-mod:result` | 依 ID 讀取工作結果。 |
| `/model-mod:cancel` | 依 ID 取消工作。 |
| `/model-mod:transfer` | 確認後將目前工作階段匯入 Codex。 |
| `/model` | Claude Code 原本的指令，維持不變：訂閱模型。直接輸入你的模型 ID（`/model <id>`）也可以。 |
| `/btw <question>` | 選了你的模型時，經你的上游以唯讀上下文回答，不使用工具。 |

## 文件

- [設定說明](docs/CONFIGURATION.zh-TW.md)：上游準備、所有選項與預設值、外部設定檔及 `--values-stdin`。
- [運作方式](docs/HOW-IT-WORKS.zh-TW.md)：路由、自訂提示、開發與安全回報。
- [你的模型能做什麼](docs/FEATURES.zh-TW.md)：串流、工具、代理、effort、壓縮與自動切換。
- [疑難排解](docs/TROUBLESHOOTING.zh-TW.md)：啟用檢查、常見錯誤、更新與解除安裝。

## 限制、隱私與合規

- [Windows 驗證清單](docs/WINDOWS.zh-TW.md)說明尚未驗證的平台。
- [限制說明](docs/LIMITATIONS.zh-TW.md)列出已知差異、尚未驗證的行為及[訂閱側請求](docs/LIMITATIONS.zh-TW.md#訂閱側請求)。
- 對話、系統指示（含專案指示）、工具定義與結果、圖片會送往你的上游及其背後的供應商。搜尋查詢、擷取網址、圖片提示分別送往對應的目的地。
- Auto 權限模式會把完整對話與專案指示送到你的訂閱做分類，即使目前選的是你的模型。改用 default 或 acceptEdits 模式搭配 allow 規則即可避免；其他側請求仍可能使用你的訂閱。
- mod 使用插件 hook，不修改 Claude Code 執行檔、不攔截 TLS、不讀取訂閱憑證檔，也不把訂閱憑證送往你的上游。請使用你信任的上游；串流輸出不會改寫來遮蔽金鑰。

本專案獨立運作，與 Anthropic 或 OpenAI 均無隸屬關係，也未獲任一方背書。[合規說明](docs/COMPLIANCE.zh-TW.md)解釋設計限制，並附上現行條款；不代表已獲授權。閱讀適用條款是你自己的責任。

## 開發

```bash
claude plugin validate .
claude plugin test .
```

測試使用假憑證，需搭配支援 mod 的 Claude Code。試用工作副本的方式見[開發說明](docs/HOW-IT-WORKS.zh-TW.md#開發)。

## 問題回報與安全

歡迎[回報錯誤與問題](https://github.com/chin-labs/model-mod/issues)及提交 PR，但不保證回覆時間。漏洞請透過儲存庫的 Security 分頁私密回報，不要貼在公開 Issue。見[回報規範](docs/HOW-IT-WORKS.zh-TW.md#問題回報與安全)；不得包含金鑰、訂閱憑證、私人路徑或內網端點。

## 授權

[MIT](LICENSE)。
