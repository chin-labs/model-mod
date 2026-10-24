# model-mod

在 Claude Code 中使用你自己的 API 模型。

[![Version](https://img.shields.io/github/v/release/chin-labs/model-mod)](https://github.com/chin-labs/model-mod/releases)
[![License](https://img.shields.io/github/license/chin-labs/model-mod)](LICENSE)
[![Claude Code plugin](https://img.shields.io/badge/Claude_Code-plugin-gray)](https://code.claude.com/docs/en/plugins)

[English](README.md)

model-mod 是供 Claude Code 使用的插件（mod），讓你把自己的 Messages 相容 API 模型放在內建模型旁邊，例如 CLIProxyAPI 搭配自己登入的 Codex。用 `/model-mod:model` 選你的模型，該工作階段就改走你的上游；用 `/model` 回到訂閱模型。訂閱模型、`ANTHROPIC_BASE_URL` 與 Remote Control 維持 Claude Code 原本的連線。

## 需求

- 支援 mod 的 Claude Code，已在 **Claude Code 2.1.299 至 2.1.310** 測試；其他版本未測。
- 你自己已啟動的 Messages 相容上游及其 API 金鑰。已測試的上游是 CLIProxyAPI；model-mod 不會安裝或啟動它。
- `curl` 與 `bash`；網頁擷取與圖片生成另需[設定說明](docs/CONFIGURATION.zh-TW.md#先準備好你的上游)列出的系統工具。

## 快速開始

先[準備好你的上游](docs/CONFIGURATION.zh-TW.md#先準備好你的上游)，再於 Claude Code 的互動工作階段中執行：

```text
/plugin marketplace add chin-labs/model-mod
/plugin install model-mod@model-mod
/plugin configure model-mod@model-mod
/model-mod:setup
/model-mod:model
```

上游 API 金鑰請在設定對話框填入；它會當作機密儲存，不必在對話中輸入。`/model-mod:setup` 會確認上游網址，並讓你選擇模型；`/model-mod:model` 隨後列出這些模型。設定完成後若插件尚未啟用，請執行 `/reload-plugins` 或重新啟動 Claude Code。

也可從 shell 加入 marketplace 並安裝：

```bash
claude plugin marketplace add chin-labs/model-mod
claude plugin install model-mod@model-mod
claude plugin configure model-mod@model-mod
```

最後一行 shell 指令會列出選項及尚未設定的項目；請在 Claude Code 內用 `/plugin configure model-mod@model-mod` 編輯，或[從私密檔案設定](docs/CONFIGURATION.zh-TW.md#其他安裝與設定方式)。要從本機 clone 安裝，把 `chin-labs/model-mod` 換成 clone 的路徑。

用 `/model-mod:status` 檢查是否啟用，再選你的模型並送一則短訊息。上游出錯時，該回合以錯誤訊息結束，絕不改走你的訂閱重試。

## 特色

- 你的模型與訂閱模型並存，用 `/model-mod:model` 依工作階段切換。
- 支援串流、工具呼叫、Skills、MCP 伺服器、子代理與 Workflow agent。
- 提供給你的模型使用的網頁搜尋、網頁擷取、圖片生成與工具搜尋。
- 暫時性上游錯誤自動重試，並支援 Claude Code 的五級 effort。
- 以你選的模型壓縮上下文，也可選擇在訂閱用量達上限時自動切換模型。

## 指令

| 指令 | 用途 |
|---|---|
| `/model-mod:setup` | 確認上游網址並選擇要提供的模型。取消不會更動設定。 |
| `/model-mod:model` | 列出你的模型並切換到所選的那個（↑↓ 移動、Enter 選取、Esc 關閉）。終端機太矮、或來自 Remote Control／手機時，改用分頁選單。 |
| `/model-mod:refresh` | 重新讀取提示檔與上游的模型清單。 |
| `/model-mod:status` | 顯示 mod 是否啟用、提供的模型數量及工具設定。 |
| `/model` | Claude Code 原本的指令，維持不變：訂閱模型。直接輸入你的模型 ID（`/model <id>`）也可以。 |
| `/btw <question>` | 選了你的模型時，經你的上游以唯讀上下文回答，不使用工具。 |

## 文件

- [設定說明](docs/CONFIGURATION.zh-TW.md)：上游準備、所有選項與預設值、外部設定檔及 `--values-stdin`。
- [運作方式](docs/HOW-IT-WORKS.zh-TW.md)：路由、自訂提示、開發與安全回報。
- [你的模型能做什麼](docs/FEATURES.zh-TW.md)：串流、工具、代理、effort、壓縮與自動切換。
- [疑難排解](docs/TROUBLESHOOTING.zh-TW.md)：啟用檢查、常見錯誤、更新與解除安裝。

## 限制、隱私與合規

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
