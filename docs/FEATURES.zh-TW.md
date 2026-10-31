# 你的模型能做什麼

[English](FEATURES.md) · [README](../README.zh-TW.md)

- **串流與工具。** 文字與工具呼叫皆為串流。尚未收到任何輸出前，HTTP 429、502、503、504、529 與其他暫時性錯誤會在 2、6、15 秒後重試（最多三次）。整數 `Retry-After` 為 0–15 秒時，下一次等待至少採用該值；超過 15 秒則立即以 HTTP 狀態與要求的等待秒數結束回合。無效值與 HTTP 日期一律忽略。輸出開始後串流中斷，該回合直接結束，不會重播。
- **內建工具、Skills 與 MCP。** 照常運作。工具輸入 schema 不會轉交，參數由 Claude Code 自行驗證。
- **子代理與 Workflow。** 在訂閱工作階段中，可用 `model-mod:local-worker` 代理類型把工作交給你的模型（需設定 `workerModel` 或 `fallbackModel`），或讓 Workflow agent 指定 `model: "<你的模型 ID>"`。用你的模型的工作階段仍可委派給訂閱模型，該請求走訂閱。
- **網頁搜尋與擷取。** API 路徑的 `web_search` 經 API 上游執行；Codex 登入在 `codexWebSearch` 開啟且工作階段提供 WebSearch 時使用原生搜尋。`web_fetch` 自行下載公開 HTTP(S) 頁面，每一跳都檢查所有 DNS 回答，拒絕私網與特殊用途位址（最多五次重新導向）。
- **圖片生成。** `generate_image` 把 PNG 存到工作目錄。API 路徑使用 `/v1/images/generations` 與設定的圖片模型；Codex 登入使用內建圖片生成，不需設定 `imageModel`，僅支援 POSIX。Codex 可能先讀取帳號目錄中內建的圖片生成技能檔，因此可能多出一次讀取權限提示。
- **Codex 父 thread 重用。** `codexThreadReuse` 開啟時，符合條件的請求從短期父 thread 建立 ephemeral fork，並重放完整歷史。一台 Mac 上的小樣本測試觀察到快取重用改善，但不保證命中。見[限制說明](LIMITATIONS.zh-TW.md#codex-登入的限制)。
- **Codex 推理延續。** 工具迴圈期間可透過實驗性 app-server API 在記憶體保留不透明的 reasoning item；真實 Codex 回合的重放尚未驗證。見[限制說明](LIMITATIONS.zh-TW.md#codex-登入的限制)。
- **工具搜尋。** `tool_search` 用來找出 schema 被延後載入的 MCP 工具。
- **Effort。** Claude Code 的五級（`low`、`medium`、`high`、`xhigh`、`max`）以模型後綴（如 `model(high)`）送出。Codex 登入路徑會由 helper 將後綴轉為 app-server effort，包含 `max`；`effortMode` 僅適用 API 路徑。Ultracode 是獨立的 workflow 開關，不改變等級。
- **壓縮。** `/compact` 與自動壓縮使用你的模型。摘要保留多少取決於模型，不是無損存檔。
- **圖片與 PDF。** 圖片會轉交。單頁 PDF 以圖片方式讀取。
- **Prompt cache。** API 上游回報的快取用量會原樣帶回；Codex 用量由 app-server 的 token 用量推算。快取計數語意尚未完全驗證。
- **自動切換（預設關閉）。** 設定 `fallbackModel` 後，當某回合結束時訂閱用量已達 `fallbackPercent` 且重置時間在未來，工作階段會切到該模型並顯示通知，重置後再切回。它不會重送觸發上限的那一回合、不會重置任何限制，也不會在工具迴圈中或對子代理執行。手動換模型會取消切回。切換期間，你的對話會送往你的上游。

Codex 登入的官方 `rateLimits` 達設定門檻且已知未來重置時間時，也會切換至 `fallbackModel`。不會輪流更換帳號；API 上游模型沒有官方額度切換機制。

Codex 模型的工具清單不包含 mod 的 `web_search`；原生搜尋無法顯示為內建「已搜尋」區塊，改以每次搜尋一行助手文字呈現（該行僅在一台 Mac 的真實客戶端看過一次）；但仍可使用 `generate_image`、`web_fetch` 與 `tool_search`。Codex 自動壓縮項目不受支援；見[限制說明](LIMITATIONS.zh-TW.md#codex-登入的限制)。

`web_search`、`web_fetch`、`generate_image`、`tool_search` 在 model-mod 啟用期間註冊（`generate_image` 需設定 API 圖片模型或 Codex 帳號，關閉工具搜尋時不註冊 `tool_search`），最多讓訂閱模型的請求多約 3 KB 的工具定義；訂閱模型呼叫時會被拒絕，請改用 Claude Code 內建工具。它們遵循 Claude Code 的權限規則。模型的實際表現取決於模型本身；本插件不會讓它等同訂閱模型。

## 委派與資料流

`/model-mod:review` 要求唯讀的原生 Codex 審查；`--base REF` 指定 base。`--adversarial` 送出範圍內的 diff，允許在 `--` 後指定焦點並接受 `--effort`；它不含未追蹤檔案。原生 review 不接受焦點文字或 `--effort`。`--gate` 要求下述結構化審查。`/model-mod:rescue -- TASK` 請 Codex 協助。兩者預設前景執行，並接受 `--account NAME` 與 `--model ID`。Rescue 接受 `--effort`、`--background`、`--write`；原生 review 接受 `--base`、`--background`；adversarial review 接受 `--base`、`--effort`、`--background` 與焦點文字；gate 接受 `--base`、`--effort`，但不接受 `--background` 或焦點文字。Windows 不支援背景工作。

`/model-mod:rescue --write -- TASK` 需要互動確認工作目錄。它要求對該目錄使用 workspace-write 並關閉網路；命令可能有其他外部副作用。每個帳號最多一個未終態的背景 write 工作。review 與一般 rescue 使用唯讀 sandbox，限制寫入與網路，但**不限制讀取範圍**；命令可能讀取工作區外的檔案。這與 Messages bridge 停用內建 shell 不同。見[限制說明](LIMITATIONS.zh-TW.md#背景委派限制)。

透過使用者登入的 Codex CLI，任務與焦點文字及審查內容會送到 OpenAI。Adversarial review 送出 diff；gate review 送出 diff 與未追蹤且未忽略檔案的完整內容。原生 review 把目標交給 Codex，Codex 可讀取 sandbox 內的檔案並送出讀到的內容。啟用選用的 Stop gate 後，符合條件的收尾回合可將 diff 與未追蹤內容送去審查；此功能預設關閉。`transfer` 經確認後把目前對話 transcript 匯入所選 Codex 帳號，由 OpenAI 持久保存。官方 CLI 自行處理連線；model-mod 的委派路徑不使用 API 代理，外掛本身也未加入遙測。CLI 與供應商的行為（包括是否有遙測）不在本專案的驗證範圍內。

工作狀態與結果留在本機 model-mod 狀態目錄的 `delegate/v1` 下，最多保留七天、50 筆。結果可能包含敏感片段；本機遮罩能力有限。`/model-mod:cancel ID` 停止工作；`/model-mod:jobs --clear` 移除目前工作區的終態紀錄與結果，但不會刪除供應商端紀錄。與官方 `openai/codex-plugin-cc` 並存只做了原始碼的靜態比對；見[限制說明](LIMITATIONS.zh-TW.md#尚未驗證)。Codex 輸出是不可信資料；gate findings 會標示並清除控制字元，但不代表已獨立驗證。

## Codex 審查關卡

`/model-mod:review --gate [--account NAME] [--model ID] [--effort E] [--base REF]` 對範圍內變更（含未追蹤檔案）要求結構化裁定，顯示帳號、模型、快照指紋與不可信的 findings。`unknown` 需要人工審查；pass 只適用同一工作階段與快照。Gate 模式不接受 `--adversarial`、`--background` 或焦點文字。Adversarial 審查不包含未追蹤檔案。

選用 Stop gate 預設關閉。啟用後，主工作階段結束回合時可能額外啟動唯讀 Codex 審查，把 diff 與未追蹤且未被 gitignore 的檔案全文送往 OpenAI，並可能阻擋結束，最多達該工作階段的設定次數；被 gitignore 的檔案不會送出。唯讀仍可能執行命令。達上限或結果為 unknown 時可能在未驗證通過下結束，需人工審查。

## 背景 Codex 委派

在 `/model-mod:review`（`--gate` 除外）或 `/model-mod:rescue` 加上 `--background`，即可提交後不等待結果。預設不寫檔（仍可能執行讀取類命令）。前景或背景的 `/model-mod:rescue --write` 會先要求互動確認，通過後才能寫入工作區。`/model-mod:jobs [ID] [--all]` 列出目前工作區或所有工作區的工作，或查看單一工作；`/model-mod:result ID` 讀取結果，`/model-mod:cancel ID` 取消工作，`/model-mod:jobs --clear` 刪除目前工作區已終態的紀錄與結果。每帳號一次只能有一個寫入工作，此上限僅適用背景工作。合用 `--all --clear` 時，只清除目前工作區已終態的工作，再列出所有工作區的剩餘工作。ID 可使用至少四位的唯一十六進位前綴。完成通知僅盡力提供。

`/model-mod:transfer [--account NAME]` 在確認後匯入目前工作階段，確認完成時顯示 `codex resume` 命令；它不執行模型回合，重複匯入可能產生重複紀錄。
