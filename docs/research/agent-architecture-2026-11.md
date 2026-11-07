# M2r · Agent architecture research

**日期：2026-11-07**  
**範圍：唯讀研究；本文由 caller 儲存為 `docs/research/agent-architecture-2026-11.md`。**

**建議：目前保留本機登入、REST 與 stdio MCP，先把使用者限制、資料版本、模型成本及結果整合做成明確的程式流程。AgentCore Runtime 值得做對照實驗，但 Gateway、Memory 與雲端部署不應綁在同一次遷移。官方 Events 的 loopback-only OAuth 仍阻止純雲端網站自行完成登入。**

本文區分：

- **已核實**：本次讀到的程式或官方文件。
- **估算／提案**：可重算的成本假設或尚未執行的設計。
- **unverified**：未取得實測、帳號層驗證或足夠文件證據。

外部來源均於 **2026-11-07 查閱**；有明確刊期者另列。價格以 USD 表示，不含稅、優惠及未列明的共用服務費。表中的本機「$0」指**不新增按量雲端服務費**，仍使用既有機器、磁碟與維護時間。

已讀指定的 `README.md`、`atlas/*.py`、`web.py`、roadmap、UX flow，並補讀 `explorer/official_catalog.py`、相關 brief、requirements 與測試清單。觀察的 HEAD 為 `190b839a3045d79877b92245e1bb0ce70c12f7a2`。未修改程式、未部署、未呼叫產品的 Bedrock 推論或官方行程寫入。

## 1. AgentCore 現況與我們的整合邊界

### 1.1 今天的程式，哪些已經有、哪些還沒有

| 現況 | 程式依據 | 架構上的意義 |
|---|---|---|
| 預設所有對話使用 `us.amazon.nova-pro-v1:0`，透過 Bedrock Converse 調用工具 | `atlas/agent.py` | 已有可運作的自訂 agent loop，Runtime 遷移不必先換框架 |
| 搜尋、路線、行程選擇及可行性判定由程式完成 | `catalog.py`、`routing.py`、`planner.py` | 這些工作不需要模型重新推理一次 |
| REST 與官方遠端 MCP 共用同一個記憶體 token | `official_auth.py`、`official_mcp.py` | 授權目前綁在本機 Python process |
| 自有 MCP 使用 `mcp.run()`，即 stdio 傳輸 | `mcp_server.py` | 不能直接拿它當 Gateway 可連線的遠端 URL |
| profile 是本機 JSON；最後到訪狀態另存 `.state.json` | `profile.py` | 已有持久化個人事實，不必靠 AgentCore Memory 才能「記得使用者」 |
| 每日步數、移動需求及固定承諾主要靠 prompt 轉成參數 | `prompts.py`、`tools.py` | 原則層需要程式執行，不能只換儲存格式 |
| `must` 目前仍由呼叫者傳入；規劃入口沒有自行鎖定官方預約 | `tools.py::_call` | 應由既有 M0 T2 修正，不另開重複實作 |
| Copilot catalog 快取 300 秒；Explorer 有另一個 catalog adapter，最短刷新間隔 60 秒 | `catalog.py`、`explorer/official_catalog.py` | 同一畫面與對話可能讀到不同版本，應先統一快照 |
| 此 checkout 沒有 `docs/costs.md`；agent 未處理 Converse `usage` | 檔案清單、`agent.py` | 本文模型成本是估算，不能宣稱已量測節省 |

README 的部分描述已落後於程式：它說不提供預約，但 `web.py` 已有明確點擊觸發的 `/api/rsvp`，呼叫 `catalog.reserve_sessions()` 後讀回 `GetSchedule`；模型的 `WRITE_TOOLS` 則仍只有 `add_favorites`。後續架構應保留這項「模型提案、程式驗證、人確認後執行」的分工。

### 1.2 AgentCore 各能力：用途、價格、是否值得現在採用

AgentCore 是可分別使用的服務組合，並非採用 Runtime 就必須同時採用 Gateway、Memory 或 managed Harness。官方現在也提供 **Harness**，即代管的模型與工具執行迴圈；它和本專案所說的「個人原則層」是不同概念。[AgentCore 概覽，2026-11-07][ac-overview]

以下價格取自官方定價頁；區域代號集合見下一節。[AgentCore 定價，2026-11-07][ac-price]

| 能力 | 是什麼，以及如何承接本專案 | 成本 | 判斷／參加者能感受到的好處 |
|---|---|---|---|
| **Runtime microVM** | 執行自訂 Python agent 或工具服務；保留現有 planner、routing、dispatcher。不能替參加者的瀏覽器接收本機 OAuth callback | v1：CPU **$0.0895/vCPU-hour**、記憶體 **$0.00945/GB-hour**；v2 consumption：**$0.1276**、**$0.0169**。另計模型、儲存、網路等 | **做 spike**。可能改善服務可用性及部署，但目前尚無本專案的延遲、可靠性證據 |
| **Runtime Instances** | 在代管 EC2 instance 上執行較持久或資源密集的工作 | EC2 費用＋依公開 On-Demand 價計算的 **12% 管理費**，另加 EBS、網路 | **not now**：目前沒有需要長駐大型工作環境的參加者功能 |
| **Gateway** | 將 OpenAPI、Lambda 等介面轉成 MCP 工具，或彙整既有遠端 MCP；它不是我們本機程式的主機 | 操作 **$0.005/1,000 次**；工具語意搜尋 **$0.025/1,000 次**；索引 **$0.02/100 tools-month**；另加 target 成本 | **稍後條件式採用**：當參加者確實需要從遠端 MCP client 使用同一組工具時有價值 |
| **Identity** | 管理 agent 身分、下游 OAuth/API key 及使用者委派；不會把 IAM 身分變成 Events attendee token | 經 Runtime／Gateway 使用不另收 Identity 費；獨立使用為 **$0.010/1,000 次 token/API key 請求** | **不能解開目前登入限制**。稍後有多個下游服務時再評估 |
| **Memory** | 保存短期事件，或從互動抽取跨 session 的長期記憶 | 2026-10-06 起短期：寫入 **$1/GB**、取回 **$0.20/GB**、儲存 **$0.10/GB-month**；寫入／取回每事件至少按 12 KB 計。長期 built-in **$0.75/1,000 records-month**；override/self-managed **$0.25**，另有模型費；取回 **$0.50/1,000 次** | **not now**：本機 profile 已能跨重啟保存。日後有跨裝置記憶需求，再評估；不能取代明確確認的個人事實 |
| **Observability** | 以 OpenTelemetry（OTel，標準化追蹤格式）記錄模型、工具、延遲與錯誤；資料進 CloudWatch | 依 CloudWatch logs、spans、metrics、查詢計費；本專案精確單價及資料量 **unverified** | **先保留可攜 trace**，日後需要查雲端故障時接入。搬 Runtime 不是使用它的前提 |
| **Managed Harness** | AWS 代管 agent loop，可配置模型、工具及記憶 | Harness 本身無額外費；底層 Runtime、模型、工具等照計 | **not now**：尚未證明重寫現有 loop 能改善答案或完成時間 |
| **Policy** | 在 Gateway 邊界執行工具授權規則；與「喜歡少走路」這類規劃原則不同 | 授權 **$0.000025/次**；自然語言政策編寫表列 **$0.13/1,000 input tokens**；Guardrails 另計 | 本機先用程式規則。遠端工具正式開放時再評估；不能把模型傳入的 `confirm=true` 當真人同意 |
| **Evaluations** | 使用 trace 評估任務、工具與回答品質 | built-in：**$0.0024/1,000 input tokens**、**$0.012/1,000 output tokens**；batch **$0.0018／$0.009**；custom **$1.50/1,000 evaluations＋模型費** | 先跑離線 scenario battery；之後抽樣評分。**not now：每個回答都另叫 judge** |
| **Optimization** | 根據評估提供改善建議及 A/B test | Insights 預覽免費；建議流程仍可能產生 Evaluations 費；A/B 計底層用量 | **not now**：先建立正確性與成本基線 |
| **Browser／Code Interpreter** | 雲端瀏覽器及隔離程式執行環境 | CPU **$0.0895/vCPU-hour**、記憶體 **$0.00945/GB-hour**，其他資源另計 | **not now**：已有明確 API 及固定演算法，沒有需要額外代理操作的功能 |
| **Web Search／Web Answer** | 公開網路搜尋／帶來源的網路回答 | 分別 **$7/1,000 queries**、**$10/1,000 calls** | **not now**：不能取代需要 attendee 授權的官方 catalog |
| **AWS Agent Registry** | 跨服務登錄及探索 agents、MCP、tools 等資源 | 每月先有 5,000 records、100 萬 search、200 萬 Get/List 免費額度；超額分別 **$0.40、$0.020、$0.004/1,000** | **not now**：目前沒有讓參加者受益的跨團隊工具目錄需求 |
| **Payments** | 讓 agent 支付付費 API／內容 | AWS 無額外服務費；wallet provider、交易及內容費另計，供應商精確費率 **unverified** | **not now**：沒有付費工具功能需求 |
| **Managed session storage** | Runtime session 儲存能力，目前文件標示 public preview | 預覽期間不收使用費；正式價格及本專案所需持久化行為 **unverified** | **not now 作 profile 真實來源**；先驗證 session 結束、版本升級及刪除後的行為 |

能力與整合依據分別見 [Runtime contract][runtime-contract]、[Gateway targets][gateway-mcp]、[Identity][identity-custom]、[Memory][memory]、[Observability][observability]、[Harness][harness]、[Policy][policy]、[Evaluations][evaluations]、[Optimization][optimization]；查閱日均為 2026-11-07。

**兩個價格限制：**

1. v2 committed baseline 雖列出 CPU `$0.0997/vCPU-hour`、記憶體 `$0.0132/GB-hour`，頁面仍帶有「launching by October 2026」文字。實際可購買狀態及條件 **unverified**，不拿承諾用量折扣當 spike 基準。
2. Policy 自然語言編寫的敘述與表格單位文字不完全一致；本文引用價格表及範例，但實際 SKU 單位仍列 **unverified**。目前也不需要這項功能。[AgentCore 定價][ac-price]

### 1.3 區域可用性

官方區域表目前列出 22 個區域。以下的「支援」是**公開文件支援**，不代表 BR 帳號已取得配額、模型存取或相同功能版本；後者全部 **unverified**。[官方區域表，2026-11-07][ac-regions]

定義全集 **R**：

`us-east-1`、`us-east-2`、`us-west-1`、`us-west-2`、`eu-central-1`、`eu-west-1`、`eu-west-2`、`eu-west-3`、`eu-south-1`、`eu-south-2`、`eu-north-1`、`ap-southeast-5`、`ap-south-1`、`ap-south-2`、`ap-southeast-1`、`ap-southeast-2`、`ap-southeast-7`、`ap-northeast-1`、`ap-northeast-2`、`ca-central-1`、`sa-east-1`、`us-gov-west-1`。

| 能力 | 公開文件支援區域 |
|---|---|
| Runtime microVM、Gateway、Identity、Built-in Tools、Observability、Policy、Evaluations | R |
| Harness、Memory | R 扣除 `us-west-1`、`eu-south-1`、`eu-south-2`、`ap-southeast-5`、`ap-south-2`、`ap-southeast-7` |
| Runtime Instances | `us-east-1`、`us-east-2`、`us-west-2`、`eu-central-1`、`eu-west-1`、`ap-south-1`、`ap-southeast-1`、`ap-southeast-2`、`ap-northeast-1` |
| Optimization | R 扣除 `us-gov-west-1` |
| Registry | `us-east-1`、`us-west-2`、`eu-west-1`、`ap-southeast-2`、`ap-northeast-1` |
| Web Search | Registry 上述區域，加 `us-east-2`、`us-gov-west-1` |
| Payments | `us-east-1`、`us-east-2`、`us-west-2`、`eu-central-1`、`eu-west-1`、`eu-west-2`、`eu-west-3`、`eu-south-1`、`eu-south-2`、`eu-north-1`、`ap-southeast-1`、`ap-southeast-2` |
| Web Answer、managed session storage 的獨立區域範圍 | **unverified**，不能直接沿用其他服務的集合 |

**建議 spike 使用 `us-east-1`**，沿用目前 Bedrock client 的預設區域，減少同時變動。這不表示推論資料必定只在該區處理：目前的 `us.amazon...` 是跨區域 inference profile；Memory、Policy、Evaluations 也有各自的跨區推論規則。未來若存放個人資料，應另外確認實際處理範圍。[Nova Micro model card][nova-micro]、[AgentCore 跨區推論，2026-11-07][ac-cross-region]

### 1.4 官方 Events MCP：協定可接，登入仍有硬限制

官方 `https://api.awsevents.com/mcp` 使用 **Streamable HTTP**，即以 HTTP 傳輸 MCP 請求與串流結果。它提供與 REST 對應的工具；MCP 本身所有工具都需要登入，讀取需註冊的活動及個人行程還需要該 attendee 的活動資格。[Events MCP，2026-11-07][events-mcp]

官方登入文件明確規定：

- 使用 OAuth authorization-code flow＋PKCE（Proof Key for Code Exchange，以一次性驗證碼保護公開 client）。
- 自建應用必須在參加者機器執行。
- callback 是精確比對的 `localhost` 或 `127.0.0.1`、8484–8489、`/callback`。
- **沒有 hosted redirect URI。**
- 已安裝 MCP client 有各自已登錄的 callback；這不是任意網站可使用的 hosted callback。[Events 登入文件，2026-11-07][events-signin]

本專案刻意只用 8484–8488，避免占用 8489；這是程式的較窄選擇，不是官方少支援一個 port。

因此：

```text
參加者的瀏覽器
  → Builder ID
  → http://127.0.0.1:8484/callback
  → 參加者自己的機器
```

雲端 Runtime 在自己的 `127.0.0.1` 開 listener，無法收到這個 callback。把程式放入容器、加 NAT、Gateway 或 Runtime session endpoint，都不會改變參加者瀏覽器中 `127.0.0.1` 的意義。

AgentCore Identity 的官方流程使用 AWS hosted callback，例如：

```text
https://bedrock-agentcore.us-east-1.amazonaws.com/identities/oauth2/callback/...
```

這個 URL 必須被下游 OAuth provider 接受。Events 公開 client 目前沒有這項 hosted redirect，因此 **Identity 不能直接代辦其登入**。`defaultReturnUrl` 是流程完成後的返回頁，也不能用來改寫 provider 的 `redirect_uri`。[Runtime OAuth，2026-11-07][runtime-oauth]、[Gateway outbound authorization][gateway-auth]

| Events 接法 | 可行性與參加者體驗 | 成本 | 判斷 |
|---|---|---|---|
| 本機服務直接連官方 REST／MCP | 與目前登入邊界相符；token 留本機 | 既有本機成本＋模型；Events API 計費 **unverified** | **現在採用** |
| Runtime／Gateway＋Identity 直接走 Events authorization-code flow | 雲端 callback 不在現有允許範圍 | AgentCore 費仍會產生，登入問題仍在 | **目前不可作為完成方案** |
| 本機 helper 保管 token、執行 Events 工具，雲端只接收任務資料 | 技術方向合理，但仍需安裝 helper；雲端回呼工具的通道尚未實作 | 本機＋Runtime／網路／bridge 維護成本，**unverified** | M4 的候選 spike，不宣稱已可用 |
| 本機登入後把 token 交雲端 | 不再符合目前「token 僅留本機 process」邊界 | 雲端 credential 管理、隔離與稽核成本 **unverified** | **not now**，不是透明搬遷 |
| Device flow、新 client、token exchange 或 AWS 新增 hosted redirect | 未找到足以確認 Events 支援的證據 | **unverified** | 交 M4 向官方驗證，不能假設存在 |

Gateway 連 OAuth-protected MCP 還有 discovery 問題：DEFAULT listing 會同步工具定義；authorization-code target 可採預先提供 schema 等方式。DYNAMIC listing 則有不支援 outbound 3LO 等限制。不能因為 URL 使用 MCP，就假設背景同步能用某個參加者的授權自動成功。[Gateway MCP targets，2026-11-07][gateway-mcp]

**Runtime 成本量級示例，僅為估算：**每次請求使用 10 vCPU-seconds，0.5 GB 記憶體保留 60 秒，則 v1 約 `$0.000327/次`，v2 consumption 約 `$0.000495/次`；1,000 次約 `$0.327／$0.495`。這不含系統額外用量、初始化、較長 session、推論、log、儲存與網路，不能當完整報價。CPU 等待模型時可不計 CPU 費，記憶體仍須按版本及生命週期估算。[AgentCore 定價][ac-price]

## 2. 我們的服務介面：保留 REST＋MCP，何時加 Gateway

**建議現在保留 REST＋stdio MCP，內部直接呼叫共用 Python domain functions。未來真有遠端 client 需求時，再新增 HTTP MCP 或 Gateway adapter。**

目前 `atlas.tools.dispatch()` 已經是共用入口。應讓每種傳輸薄薄地包住它，避免 REST、MCP、Gateway 各自發展一套規劃規則。

| 選項 | 參加者可見的好處 | 成本 | 限制與決定 |
|---|---|---|---|
| **A. 保留本機 REST＋stdio MCP** | Web 操作直接；也能把工具接入本機 MCP client | 新增代管費 **$0**；既有模型、機器及 Events 費另計 | **現在推薦**。維持目前可用的登入方式 |
| **B. 全部經 Gateway 對外** | 遠端 client 有一致的工具入口及授權管理 | Gateway 操作費＋target hosting＋模型＋監控 | **not now**。Gateway 不能連到參加者機器上的 localhost，也不能解開登入 |
| **C. REST＋本機 stdio，另加遠端 Gateway** | 同一套能力能同時服務網站、本機與遠端 MCP client | B 的雲端費＋adapter 維護；本機部分不新增代管費 | **稍後推薦的擴充形態**，前提是遠端使用者與登入需求已成立 |
| **D. 直接提供自有 Streamable HTTP MCP** | 遠端 MCP client 可連線，不必先採 Gateway | 服務 hosting、身分驗證、log；不付 Gateway 費，精確數字 **unverified** | 可作 C 的較小替代；仍需處理 Events 登入與 profile 隔離 |
| **E. 內部直接 Python 呼叫，外部才走 REST／MCP** | 避免 agent 對同 process 服務再繞一圈 HTTP；結果一致 | 本機新增代管費 **$0** | **維持現有共用 dispatcher**；單純介面重整若無故障或延遲改善，額外重構 **not now** |
| **F. A2A／AG-UI 等新協定** | 可能服務獨立 agents 或更複雜串流 UI | hosting、adapter 及維護，**unverified** | **not now**：目前沒有對應功能需求 |

AgentCore Runtime 支援 HTTP、MCP、A2A、AG-UI；MCP server 的遠端 contract 是 Streamable HTTP，並非 stdio。因此新增遠端介面需要真正的 adapter，不能只修改 Gateway 設定。[Runtime service contract][runtime-contract]、[MCP protocol contract，2026-11-07][runtime-mcp-contract]

### 必須保留的三個介面邊界

**第一，本機兩個 MCP server 並列不會共享授權。**  
`python -m atlas.mcp_server` 是另一個 process，沒有 Web process 的 `_AUTH`。在 client 設定中並列官方遠端 MCP，只會讓 client 取得官方工具；不會讓自有搜尋、規劃工具自動拿到相同 token。目前自有 stdio server 因而預設使用 synthetic catalog。這點應在介面說明中直接講清楚。

**第二，Gateway 應暴露 domain operations。**  
適合的是 `search_sessions`、`get_session`、`route_between`、`check_itinerary`、`plan_itinerary` 等，不是把 `/api/chat`、登入控制及全部 UI endpoints 一律轉成工具。目前也沒有可直接交給 Gateway 的完整 domain OpenAPI contract。

**第三，寫入授權必須在服務端成立。**  
`readOnlyHint` 是描述；`confirm=true` 是呼叫參數。兩者都不能證明真人批准了這幾個 session。遠端化前應把確認綁定到 attendee、action、精確 IDs、有效期限及一次性操作記錄，再執行官方操作並讀回結果。若回應遺失，先查狀態，再決定是否重試，避免模型盲目重送。

這延續現有 UX 原則，不需要新增一個會自行寫行程的 agent。

## 3. 任務到模型的路由與成本

### 3.1 價格與用量的證據限制

此 checkout 沒有成本報表，因此以下 input/output tokens 都是**完整單次模型呼叫的估算**，不是 ledger 實測。

AWS 於 **2025-04-04** 的官方文章列出以下參考價格；本次仍可讀到相同數值的官方活動頁，但 Nova／Bedrock 動態定價表未能提供可核對的完整區域價格。因此 **2026-11 的精確區域、tier 與帳號計價仍為 unverified**，以下僅用於預算。[AWS 官方價格比較文章，2025-04-04][nova-price-blog]、[官方活動頁，查閱 2026-11-07][nova-price-campaign]

| 模型選項 | 輸入／100 萬 tokens | 輸出／100 萬 tokens | 本專案角色與驗證狀態 |
|---|---:|---:|---|
| Deterministic code | $0 模型費 | $0 模型費 | 已有搜尋、路線、DP；不代表所有個人限制都已實作 |
| Nova Micro v1 | $0.035 | $0.14 | 最低成本文字任務候選；本專案品質 **unverified** |
| Nova Lite v1 | $0.06 | $0.24 | 摘要、翻譯與說明候選；品質 **unverified** |
| Nova Pro v1 | $0.80 | $3.20 | 現有預設；沒有本次 scenario 成本與成功率實測 |

Micro 官方 model card 將分類、摘要、翻譯列為用途，並提供 Converse；這能支持「值得測試」，不能證明它已能正確處理本專案的繁中與規劃問題。[Nova Micro model card，2026-11-07][nova-micro]

計算方式：

```text
model_cost =
  input_tokens × input_price_per_million / 1,000,000
  + output_tokens × output_price_per_million / 1,000,000
```

### 3.2 七種工作的最低成本路徑

**下表的「候選」需通過驗收才替換現有 Pro。價格低不等於已證明正確。**

| 工作 | 最低成本正確路徑／模型候選 | 估算 tokens：input／output | 估算成本／次 | 正確性與升級條件 |
|---|---|---:|---:|---|
| **Search：結構化搜尋、session code 查找** | 程式查詢；自然語言才用 Micro 抽取 query/filter | 程式 0；Micro 1,200／160 | **$0**；Micro **$0.0000644**；同 tokens Pro `$0.001472` | code、day、venue、level 必須通過 schema 與 catalog 驗證；不讓模型掃整份 catalog |
| **Plan：候選組合與可行性** | 現有 DP＋限制檢查；Micro 只解析意圖。複雜歧義保留 Pro | Micro 1,500／250；Pro 複雜案例 4,000／500 | solver **$0**；Micro **$0.0000875**；複雜 Pro **$0.0048** | 預約、blocked windows、返飯店時間由 code 鎖定；大模型不能覆蓋硬限制 |
| **Route：交通與轉場** | `routing.route()`＋固定呈現 | 0／0 | **$0 模型費** | 不用模型估距離、時刻或可行性；未知室內路線保持未知 |
| **Briefing：重返摘要** | 程式 diff、逐日檢查；固定提醒用 template，需語句整合時用 Lite 候選 | Lite 2,500／250 | template **$0**；Lite **$0.000210**；同 tokens Pro `$0.0028` | 沒有變更不重算模型；任何可行性敘述都須有當日檢查結果 |
| **Translate：按需翻譯** | 命中快取直接回傳；Micro 為最低成本候選，Lite 作比較；目前 Pro 不自動降級 | 900／500 | cache **$0**；Micro **$0.0001015**；Lite **$0.000174**；Pro **$0.00232** | 繁中、否定詞、技術術語與資訊完整性需雙語檢查；保留原 session code 與原文 |
| **Explain：為何選／沒選** | 理由碼直接 template；跨多個來源的取捨說明用 Lite 候選 | Lite 2,200／350 | template **$0**；Lite **$0.000216**；同 tokens Pro `$0.00288` | 必須引用 filter trace；不讓模型事後編造理由 |
| **Write actions：收藏、預約、取消** | 程式確認、執行、逐項結果與 read-back；自然語言只提案 | 程式 0；選配 Micro 800／100 | 執行 **$0 模型費**；意圖提案 **$0.000042** | 必須確認精確 action＋IDs；失敗或部分成功由官方結果決定，不能由模型宣告 |

### 3.3 如何整合不同模型的結果

不建議讓七個模型固定串接，也不建議讓一個 supervisor 再叫多個 agent 討論。建議一個小型、明確的 workflow：

1. UI 的已知操作直接進程式，例如篩選、路線、確認寫入。
2. 自然語言先轉成經驗證的 `TaskIntent`。
3. 程式載入同一版本的 profile、principles、catalog 與官方 schedule。
4. 執行搜尋、限制及規劃，產生帶來源的 `TaskResult`。
5. 只有需要自然語言時，才選一個合適模型。
6. 程式將文字與正式結果整合；時間、ID、狀態由資料呈現，不能被生成文字改寫。

每個結果應帶：

```text
request_id, task, catalog_revision, profile_revision,
principles_revision, evidence_refs, validation_status,
model_id, attempts, tokens, estimated_usd, price_status
```

獨立的讀取可並行，但必須使用相同快照。規劃依賴搜尋及限制，不能為了並行提早執行；寫入則保持序列。

失敗時最多做一次有理由的模型升級，並計入原呼叫費。schema 通過只能證明格式，不能證明翻譯或意圖正確；模型自己的「信心」也不能當唯一門檻。

### 3.4 先降低不必要的模型工作，再比較單價

目前每回合會送 system prompt、工具 schema、對話歷史及先前工具結果。工具執行回合上限為六，但封頂時仍可能有額外結尾呼叫及 schema retry；**一個問題不等於一次推論**。

T0 ledger 應包含每個成功取得 usage 的呼叫，包括 retry 及強制結尾；無法取得 usage 的失敗請求應記為未知，不能填 `$0`。只記用量與版本，不記 token、prompt 或完整個人資料。

一個**假設**的規劃請求：

- Micro 解析 1,500／250：`$0.0000875`。
- Lite 整合 2,500／350：`$0.000234`。
- 合計 `$0.0003215`。
- 若 20% 額外升級到一次 4,000／500 的 Pro，平均變成 `$0.0012815`。

這只是可重算的工作量模型；目前 Pro loop 的實際輸入量、升級率與回答品質 **unverified**，不能把上述差額寫成節省成果。

Bedrock 另有 Intelligent Prompt Routing，官方目前列出 Pro／Lite 路由，額外費為 `$1/1,000 requests`。對上述微小呼叫，單次 `$0.001` 路由費可能超過模型本身，因此先採程式依 task 選模型；Gateway 的模型 fallback 也不能替代語意正確性檢查。[Bedrock 定價，2026-11-07][bedrock-price]

## 4. Markdown profile＋principles：讓規則真正影響行為

**建議以 Markdown 保存可閱讀的事實與原則，以經驗證的程式結構執行。Markdown 本身不會讓模型更可靠，也不會自動降低 token。**

### 4.1 檔案位置與格式

提案：

```text
atlas/principles.md
    版本化的產品預設原則；不放個人資料

local-private/profiles/<safe-name>/profile.md
    個人確認的事實與來源

local-private/profiles/<safe-name>/principles.md
    個人可調整的原則；只能使用允許的規則語法

local-private/profiles/<safe-name>.state.json
    到訪狀態；沿用既有行程狀態工作，不混入個人事實
```

`profile.md` 用 Markdown 標題與說明供人閱讀，以唯一的 JSON fence 保存機器資料，沿用現有 JSON parser，避免為此新增 YAML 依賴。

以下完全是格式示例，不是 BR 的資料：

````markdown
# Attendee profile

以下為參加者確認的事實；未填欄位表示未知。

```json
{
  "schema_version": 1,
  "revision": 3,
  "facts": {
    "language": "zh-Hant",
    "hotel": "Example Hotel",
    "max_steps_per_day": 8000,
    "interests": ["agents", "security"]
  },
  "provenance": {
    "max_steps_per_day": {
      "source": "attendee",
      "observed_at": "2026-11-07T09:00:00-08:00"
    }
  }
}
```
````

事實要有型別、單位及來源。`home_base` 仍由程式從 hotel 推導，保留「最近 venue 的近似值」標示，不能寫回成使用者自述事實。

### 4.2 principles.md 的 if／then 規則

| 規則 | If | Then | 執行成本及參加者好處 |
|---|---|---|---|
| `walking-limit` | 有步數上限或移動需求 | `prefer="fewest_steps"`；額外檢查支援的硬限制 | **$0 模型費**；不必每次提醒少走路 |
| `fixed-hotel-call` | 有明確日期、時間的飯店通話 | 產生返飯店 deadline 及 buffer | **$0 模型費**；不推薦趕不上固定行程的 session |
| `reserved-is-fixed` | 官方 schedule 有預約 | 注入 `must` 與阻擋時段 | **$0 模型費**；已搶到的座位不被新建議忽略；由 T2 落實 |
| `unknown-route` | venue、室內或無障礙資訊不足 | 結果標記未知，不宣稱無障礙可行 | **$0 模型費**；使用者能區分估算與保證 |
| `catalog-changed` | 使用中的 session revision 改變 | 舊 plan 失效並重新檢查 | **$0 模型費**；避免繼續使用舊時間、房間 |
| `translate-on-demand` | 使用者要求翻譯且快取未命中 | 只翻該 session，保留原文與 code | 第 3 節的單次翻譯費；避免整份 catalog 預翻成本 |

機器規則可採有限、明確的 JSON 語法，例如：

```json
{
  "id": "walking-limit",
  "if": {"any_present": ["max_steps_per_day", "mobility"]},
  "then": {"route_prefer": "fewest_steps"}
}
```

`any_present` 與 `route_prefer` 是程式白名單操作；不是可任意 `eval()` 的字串，也不是任意工具名稱。未支援的條件應報告，不能默默忽略。

**目前最重要的差別：**`fewest_steps` 是最佳化偏好，不等於每日總步數必定小於 8,000。現有 planner 沒有硬性每日步數 budget；現有 transport profile 也沒有完整變成路線 edge 排除規則。原則層可先確保偏好由程式設定，但在新增對應可行性檢查以前，**每日上限與交通限制的完整遵守仍是 unverified**。

### 4.3 prompt 如何消費它們

```text
profile facts
  + 產品原則
  + 個人原則
  + 當次明確要求
  + 官方預約
    → validate／compile
    → EffectiveConstraints + applied_rules
    → 搜尋、規劃、檢查
    → 提供模型需要的事實與結果
```

模型讀取的是必要的事實、有效限制及理由碼，不必每次接收兩份完整 Markdown。個人備註與 session abstract 都是資料，不能修改工具權限或確認規則。

硬性服務規則優先；當次要求可以調整軟偏好，但若與既有硬限制衝突，應指出衝突，不可自行抹除限制。個人事實更新仍只保存使用者明確陳述的內容。

### 4.4 與現有 JSON／AgentCore Memory 比較

| 選項 | 成本 | 優點 | 決定 |
|---|---|---|---|
| 現有 JSON＋prompt 規則 | 本機新增代管費 $0；profile tokens 仍計推論費 | 程式簡單、現有工具可直接讀 | 保持相容入口，但行為仍過度依賴模型轉參數 |
| Markdown facts＋可執行 principles | 本機新增代管費 $0；若多送 400 input tokens，按暫定價為 Micro `$0.000014`、Lite `$0.000024`、Pro `$0.00032` | 人可閱讀、來源可追蹤，且規則能在 trace 顯示 | **推薦**；先做一條規則的完整流程 |
| AgentCore Memory 保存偏好 | 第 1 節 Memory 費＋取回後的 prompt tokens | 跨 session 抽取及取回互動記憶 | **not now**；不讓抽取出的偏好覆蓋明確 profile |
| 雲端保存 canonical Markdown | 物件儲存、請求、版本及存取控制費，精確值 **unverified** | 日後跨裝置讀同一份 profile | 隨 M4 評估；目前沒有授權搬移個人資料 |

遷移時維持 `get_profile` 現有的 `fields`、`missing`、`home_base` 結構。舊 JSON 可以作相容讀取；切換後只保留一個 canonical writer，避免 JSON 與 Markdown 雙寫分歧。寫入需版本檢查與原子替換；失敗保留前一版及個人編輯。

未來若放入 Runtime，不能把某個 microVM 的本機檔案當成永久 profile，也不能把可自行填寫的 profile 名稱當成身分隔離。

## 5. Agenda：資料庫先行，語意檢索作輔助

**現在推薦本機 SQLite＋全文搜尋，JSON 作短期快照過渡；稍後若相關 session 搜尋確實不足，再加小型向量索引。**

這裡的「現在」指下一階段的資料層目標，**不是把資料庫塞進目前明定不得加 DB 的 M0 T1**。

應區分三種資料：

1. **Catalog**：session 內容、時間、房間與版本。
2. **個人狀態**：官方預約、收藏、personal time，以及本機 picks。
3. **檢索索引**：可重建的關鍵字或向量資料，不是正式行程真實來源。

### 5.1 選項與成本

比較假設：**2,500 sessions、每筆約 300 embedding tokens、原始資料 10 MB、向量及 metadata 15 MB、每月 1,000 次查詢**。全部是估算，不是讀取私人 catalog 後的測量。

| 選項 | 成本 | Freshness 與解釋能力 | 判斷 |
|---|---|---|---|
| **現有記憶體 catalog** | 新增代管費 **$0**；每次完整刷新仍有 API／網路／CPU 成本 | 快取到期後更新；重啟丟失；兩個 adapter 可能版本不同 | 可維持短期使用，但不適合作唯一歷史來源 |
| **本機 JSON snapshots** | 新增代管費 **$0**；使用磁碟與完整掃描 | 易保存前後版本、hash、差異；複雜查詢與並行修改需要自行管理 | **過渡方案**，可配合 M0 T6 |
| **SQLite＋FTS5** | 新增代管費 **$0**；本機 CPU／磁碟及備份 | 可原子切換版本、查詢條件、關聯個人狀態並保留 trace | **現在推薦的目標**；本環境 FTS5 編譯支援 **unverified** |
| **小型本機向量索引** | 若 embedding 暫按 Titan V2 `$0.02/百萬 tokens`，首次約 **$0.015**；10% 內容更新約 **$0.0015**，另加查詢 embedding 與 CPU。此模型現行價格 **unverified** | 能找「意思相關但關鍵字不同」；必須另做版本、更新及刪除 | **稍後推薦**，先證明相關搜尋缺口 |
| **Bedrock self-managed KB＋S3 Vectors** | 依下述假設，首月向量儲存／操作約 **$0.00646**，加上述 embedding 約 **$0.02146**；另加來源 S3、生成模型、log 等 | 提供代管 ingestion／retrieval，但仍要把官方更新送入並同步 | **not now**：便宜的向量單價不等於值得增加雲端資料管線 |
| **Bedrock Managed Knowledge Base** | 官方表列 raw index **$5/GB-month**、Retrieve **$1/1,000 次**；managed parser、embedding、reranker 包含。示例約 **$1.05/月**，另加回答生成等；最低計費與區域 SKU **unverified** | 管理基礎設施較少，提供 hybrid retrieval；仍不是即時行程資料庫 | **not now**：較適合日後多來源文件需求 |
| **Managed KB agentic retrieval** | **$4/1,000 次 agentic calls＋$1/1,000 次底層 Retrieve**；自選 planning model 另依方案計費 | 複雜問題可拆解、多輪檢索；增加呼叫數與延遲 | **not now**：單次 conference session 查詢多數不需要 |

SQLite FTS5 提供全文搜尋及 `bm25()`、highlight、snippet 等功能；這足以先建立可檢查的關鍵字搜尋。[SQLite FTS5，2026-11-07][sqlite-fts]

S3 Vectors 官方例示的 us-east-1 價格為儲存 `$0.06/GB-month`、PUT `$0.20/GB`、query API `$2.50/百萬次`，第一個 100,000 vectors 的查詢處理 `$0.004/TB`；另有 PUT 最小計費及結果資料計費規則。上表示例假設適當批次寫入、小量返回結果，並非帳單保證。[S3 定價，2026-11-07][s3-price]

Managed KB 是目前定價頁另外列出的產品，不能套用舊版「只算自選 vector store＋embedding」的估價方式。[Bedrock 定價，2026-11-07][bedrock-price]

### 5.2 最小資料結構

不需要一開始就建立通用知識圖譜。先有下列概念即可：

| 資料 | 必須保留的內容 |
|---|---|
| `catalog_snapshot` | event、revision、fetched_at、完整性狀態、來源 |
| `session`／`session_revision` | 官方 ID、code、內容 hash、時間、venue、room、來源版本 |
| `official_schedule_snapshot` | attendee 範圍、reserved／favorites／personal time、讀取時間 |
| `local_plan` | 本機 picks，與官方狀態分開 |
| `filter_trace` | 使用的事實、規則、查詢條件、候選、排除理由、選擇結果 |

憑證不進這些資料表。取得需註冊的 catalog，不等於已確認可以把它跨 attendee 分享或上傳為公開知識庫；可接受的雲端使用範圍 **unverified**。

### 5.3 活動期間的更新策略

建議：

- 到訪、重新連線及使用者手動刷新時檢查 catalog；背景間隔先以 **60–300 秒**作實驗設定，並非官方更新 SLA。
- Web 與 agent 共用一個 refresh coordinator，合併同時發生的刷新。
- 全部分頁成功、通過完整性檢查後，才原子切換 snapshot。
- 刷新失敗時保留前一份並標示 stale。已登入的正式畫面不能把 synthetic fixture 當更新成功。
- 預約、取消等操作前，重新確認必要的 schedule／session 狀態；操作後讀回。
- session 從一次快照消失，只能先說「目前未出現在 catalog」，不能直接認定已取消。
- 本次沒有驗證 Events 的 webhook、增量 cursor、ETag 或跨分頁 snapshot isolation，均為 **unverified**。

官方每 attendee 的 `ListSessions` 配額是 120 次／分鐘、`GetSchedule` 是 60 次／分鐘；`ReserveSessions`、`AssociateFavorites` 以 session 數計配額。快取協調與批次可以減少 round trips，但不能把 batch 當成較少的 session 配額消耗。[Events 配額，2026-11-07][events-quotas]

向量更新只需依 title／abstract 等語意內容 hash 重算。房間、時間或座位狀態變更，應立即影響結構化查詢，不應等待重新 embedding。Bedrock KB 的來源變更仍需 ingestion／sync；它不會自行知道 Events API 改了資料。[KB ingestion][kb-data]、[S3 Vectors 與 KB 同步，2026-11-07][kb-s3]

### 5.4 知識庫真正買到什麼

向量檢索或 KB 的主要價值是**找出詞彙不同但內容相關的 session**，以及取回可引用的內容。它不會自行提供「為什麼這堂比另一堂更適合你」的完整決策證據。

可解釋推薦需要：

```text
使用者事實
 → 套用原則
 → day／level／venue 等條件
 → 候選集合與檢索來源
 → 時間／交通／預約檢查
 → chosen／dropped 理由
```

這是程式的決策紀錄，不是模型的內部思考過程。

現有 DP 的「exact」也只針對提供的候選集合及演算法假設；如果只傳入 30 筆，就不能宣稱已找出整份 catalog 的全域最佳解。trace 應顯示候選上限、排序與截斷。

**稍後的向量方案仍要回到 SQLite 的最新 session row，再執行限制與行程檢查。** 相似分數不能證明課程能排入當天。Bedrock 的 Retrieve 可回傳來源 chunks；RetrieveAndGenerate 可加上引用，但這些引用不等於交通可行性的證明。[KB retrieval，2026-11-07][kb-retrieval]

## 6. 目標架構、遷移順序與前兩個小 PR

### 6.1 推薦目標

```text
本機 Web UI／CLI／stdio MCP
             │
             ▼
     共用 task workflow
             │
     ┌───────┼──────────────────┐
     ▼       ▼                  ▼
 Markdown  SQLite catalog   官方 schedule
 profile   ＋版本／trace       即時讀取
 ＋rules       │                  │
     └───────┼──────────────────┘
             ▼
   程式搜尋、限制、DP、路線
             │
             ▼
   必要時呼叫 Micro／Lite／Pro
             │
             ▼
   驗證與整合結果、呈現來源
             │
       精確的人為確認
             │
             ▼
   官方寫入 → GetSchedule 讀回
```

Builder ID token 留在本機 auth layer，供 REST／官方 MCP transport 使用，不進模型、profile、catalog 或 trace。

AgentCore Runtime 是這個 workflow 的**候選執行位置**。Gateway 是未來的**外部工具入口**。Memory 是選配的**互動記憶**。三者不需要一次導入。

### 6.2 框架選型

Context7 查詢本次回傳 `fetch failed`，未重試或變更網路權限；以下改以官方文件及原始 repo 查核。精確可安裝版本、與現有 requirements 的相容性均 **unverified**。

| 選項 | 成本 | 參加者可見的價值 | 建議 |
|---|---|---|---|
| **現有 boto3 Converse＋明確 Python workflow** | 不新增框架服務費；照付模型與執行成本 | 維持已知規劃行為，容易追蹤每一步及限制呼叫次數 | **現在採用**；先讓任務、結果及預算明確 |
| **官方 MCP Python SDK** | MIT；沒有必付的 hosted 服務費，hosting／模型另計 | 同一組工具能供不同 client 使用 | **繼續使用**，但先鎖版再新增 HTTP transport |
| **Strands Agents SDK** | Apache-2.0；本機 SDK 無 hosted control plane，模型／hosting 另計 | 若減少自製 loop 的串流、預算、MCP、trace 維護，能改善穩定性 | **M2a 可比較**；不因品牌或範例簡短就重寫 |
| **LangGraph** | MIT；本機執行仍有模型、checkpoint 儲存及維護成本；代管產品另計 | 工作跨重啟、長時間等待確認時，可提供明確持久化與恢復 | **not now**，等出現需要 durable execution 的功能 |
| **AgentCore managed Harness** | Harness 無額外費，底層服務照付 | 可減少平台維護，但本專案的 OAuth 與規劃限制仍須處理 | **not now 重寫**，除非對照實驗證明可靠性收益 |
| **多 agent swarm／A2A 編排** | 多次推論、協調與可能的 hosting 費，實際值 **unverified** | 目前沒有獨立 agent 才能完成的參加者功能 | **not now** |

Strands 目前官方 repo 的舊 `sdk-python` URL 會轉到 `harness-sdk`；文件仍區分底層 `strands-agents` SDK 與較完整的 harness。選用時應明確指定套件與版本，避免順帶引入 shell、browser 等本專案不需要的工具。[Strands 官方 repo，2026-11-07][strands]

LangGraph 提供 shared-state workflow、持久化、串流及 human-in-the-loop；這些是具體能力，並不代表它會自動減少模型 tokens。[LangGraph 官方文件][langgraph]、[授權][langgraph-repo]

目前 requirements 只有下限 `boto3>=1.35`、`mcp>=1.2`，沒有 Python lockfile。官方 MCP SDK 最新文件已介紹 v2 與 Python 3.11+；不能把最新範例直接當成現有 `FastMCP` 程式的相容保證。[MCP Python SDK，2026-11-07][mcp-sdk]

### 6.3 遷移順序

| 階段 | 工作 | 成本 | 參加者收益／門檻 |
|---|---|---|---|
| **先完成 M0** | T0 ledger、T1 共用 server state、T2 鎖定預約 | 既有開發工作；離線測試不需模型費 | 不丟狀態、不推薦撞預約、成本可量測；與既有 owner 協調，不重複改檔 |
| **第一批 M2 小改動** | 任務呼叫邊界、按需翻譯 canary、profile 原則 | 小量比較推論；金額以 ledger 為準 | 更便宜且可驗證的翻譯；限制不再靠模型記得 |
| **Catalog repository** | 在 M0 範圍外統一 SQLite 快照與 filter trace | 本機新增代管費 $0 | 畫面與回答使用同版資料，可看新課、改期及排除理由 |
| **語意搜尋** | 只在相關搜尋測試暴露缺口後加向量索引 | 第 5 節的 embedding／索引費 | 找到關鍵字不同的相鄰主題 |
| **M2a Runtime 對照** | 同 workflow、同模型、同資料比較本機與 Runtime | Roadmap 上限 **$20**；不是預估必須花滿 | 證明可靠性、延遲或可用性收益；未證明就保留本機 |
| **M4 hosted path** | 驗證官方可支援的登入方式或 helper | **unverified** | 第二位參加者能自行登入；純 hosted 登入限制未解前，不宣稱已完成 |

### 6.4 前兩個具體小 PR

以下是 memo 後的實作提案，不是本次已完成的修改。

#### PR 1 — `Add bounded model tasks and an on-demand translation canary`

**問題：**目前同一個 Pro loop 處理所有語言工作，沒有 task 級成本與品質比較。

**範圍：**

- 依賴並重用 T0 ledger，不建立第二套記帳。
- 新增小型 `ModelTask` 呼叫入口，包含 task、model、token／attempt budget、price version。
- 先只接**按需 session 翻譯**；預設沿用 M0 T10 的 Pro，Micro／Lite 使用明確 opt-in 的比較設定。
- 快取 key 包含 event、session ID、title＋abstract hash、target language、glossary／translator version。
- 不改 planner、登入、其他工具權限或整體 UI。

**驗收：**

- 第二次相同翻譯不發出模型呼叫。
- title／abstract 或翻譯版本變更會使快取失效。
- 保留 session code、原文及「非官方翻譯」標示。
- 每次呼叫及重試都進同一 ledger。
- 以固定雙語案例比較否定句、術語、遺漏與繁中表達；通過後才提出預設模型切換。
- 成本與品質結果不足時，維持 Pro。

**成本：**比較呼叫按第 3 節估算並實際記帳；快取命中 `$0 模型費`。  
**參加者收益：**同一內容不重付費，翻譯品質有依據，之後能以數據降低單次成本。

#### PR 2 — `Compile a walking preference from Markdown profile principles`

**問題：**使用者已填走路限制，仍依賴模型每次正確傳入 `prefer`。

**範圍：**

- `profile.py` 增加 Markdown profile 相容讀取與單一 canonical 寫入。
- 維持 `get_profile` 既有資料形狀。
- 新增有限規則 parser，第一版只支援 `walking-limit → fewest_steps`。
- 在規劃工具進入點由程式套用，結果加入使用的 profile／rule revision 與理由。
- 不在此 PR 加每日步數硬 cap、資料庫、Memory 或完整規則語言。

**驗收：**

- 舊 JSON profile 可相容讀取，遷移後不雙寫。
- 不合法檔案或未知規則不覆蓋前一有效版本。
- 有 walking limit 時，即使模型傳 `fastest`，也遵循已生效的原則。
- 未知室內路線、飯店近似節點仍明確標示。
- 回答不宣稱已保證每日總步數上限。

**成本：**本機新增代管費 `$0`；編譯規則不叫模型。  
**參加者收益：**一次設定持續生效，能看到「為什麼採少走路」，不必反覆糾正 agent。

### 6.5 M2a 如何得到可用的比較結果

先固定 runtime 比較中的模型、prompt、工具 schema、資料及規劃程式；模型降級實驗另做，避免無法判斷收益來自哪個變更。

建議八個功能情境：

1. 精確 session code 查找。
2. 自然語言多條件搜尋與規劃。
3. 已預約 session 與候選衝突。
4. 跨 venue 路線及未知資訊。
5. catalog 更新後使舊 plan 失效。
6. 翻譯快取 miss／hit。
7. token 過期、429 或服務不可用。
8. 寫入提案、拒絕、部分成功及 read-back；使用 mock，不自行動真實預約。

記錄成功率、具體資訊是否有來源、硬限制違反、trace 完整性、各呼叫 tokens／USD、端到端延遲，以及 Runtime／Gateway／CloudWatch／儲存費。cold 與 warm 分開。

**八個情境不是八筆就能得出可靠 P95。** 先作功能門檻，再在預算內重複量測並報告樣本數。

可先提出「品質不退步、每功能平均成本降低至少 30%、P95 不惡化超過 20%」作討論門檻；這些是**提案，不是結果**。Runtime 遷移還需證明參加者感受得到的可用性或可靠性收益，不能只靠便宜的 compute 單價。

如果只用 synthetic fixtures 跑通 Runtime，能證明部署與部分成本，**不能證明正式 Events OAuth 整合完成**。實際官方寫入維持既有 BR 授權門檻。

### 6.6 明確列為 not now

沒有對應參加者功能或量測收益前，以下不進建置範圍：

- 用 Gateway 彙整目前少量工具，只為換一個 endpoint。
- 為了工具搜尋替九個自有工具建語意索引。
- 把明確 profile 改成自動抽取的 Memory。
- 新增 Browser、Code Interpreter、公開 Web Search、Payments 或 Registry。
- 為短期行程問答加入多 agent swarm。
- 同時重寫 framework、模型、storage、runtime 與登入。
- 在 hosted OAuth 尚未解決時宣稱「參加者不用本機即可登入」。

### 6.7 未完成驗證與研究缺口

| 項目 | 狀態與影響 | 下一個能消除不確定性的工作 |
|---|---|---|
| 真實 tokens、各功能成本及 Pro 基線品質 | **unverified**；`docs/costs.md` 不存在 | T0 完成後跑同一組情境 |
| Nova／Titan 的 2026-11 區域、tier 精確價格 | **unverified**；本文用了有日期的參考價 | 保存可核對的正式價格資料與 price version |
| BR 帳號的 AgentCore、模型及版本可用性 | **unverified**；僅查公開文件 | M2a 檢查目標 region、IAM、quota |
| Hosted Events OAuth／local helper | Hosted callback 文件明確不支援；helper 端到端 **unverified** | M4 驗證官方支援方式及 helper |
| Runtime 的冷啟動、session 行為與完整帳單 | **unverified** | 同程式對照，包含閒置、log、儲存及失敗呼叫 |
| Markdown parser、規則、SQLite／FTS5、向量搜尋品質 | 提案，未實作或執行；**unverified** | 上述小 PR 與 fixture 驗證 |
| KB 的現行區域 SKU、最低計費、資料上傳及共享範圍 | **unverified** | 有具體雲端功能需求時再核實 |
| 官方增量同步、webhook、分頁一致性保證 | **unverified** | 查核官方 contract；目前按完整快照設計 |
| Python／MCP／framework 精確鎖版相容性 | **unverified** | 在獨立 spike 鎖版並執行既有測試 |
| CloudWatch 精確單價及 trace 資料量 | **unverified** | 選定 instrumentation 後量測 |
| 獨立 Claude 複核 | `claude-delegate` 訂閱驗證通過；`opus` 架構請求 **180 秒逾時**，沒有可用意見；實際 Opus 5.5 模型 **unverified** | 此 memo 不宣稱已通過獨立複核 |
| 產品執行與 UI 驗證 | 本次是唯讀研究，未跑應用或測試 | 各實作 PR 依其範圍執行與驗證 |

本次交付為研究 memo；未啟動應用服務、未部署，也未提出任何已量測的省費或效能成果。

## 外部來源

以下均於 **2026-11-07 查閱**；AWS 文件與定價頁多為持續更新頁，不視為不可變的歷史快照。唯一在成本基準中採用的明確歷史刊期為 Nova 比較文章的 **2025-04-04**。

- [AgentCore 概覽][ac-overview]、[定價][ac-price]、[區域支援][ac-regions]、[跨區推論][ac-cross-region]。
- [Runtime service contract][runtime-contract]、[MCP protocol contract][runtime-mcp-contract]、[Runtime OAuth][runtime-oauth]。
- [Gateway MCP targets][gateway-mcp]、[Gateway outbound authorization][gateway-auth]、[Identity custom provider][identity-custom]。
- [Memory][memory]、[Observability][observability]、[Harness][harness]、[Policy][policy]、[Evaluations][evaluations]、[Optimization][optimization]。
- [Events MCP][events-mcp]、[Events 登入][events-signin]、[Events 配額][events-quotas]。
- [Nova 官方價格比較文章，2025-04-04][nova-price-blog]、[官方活動頁][nova-price-campaign]、[Nova Micro model card][nova-micro]。
- [Bedrock 定價][bedrock-price]、[S3 定價][s3-price]、[KB ingestion][kb-data]、[S3 Vectors／KB 同步][kb-s3]、[KB retrieval][kb-retrieval]。
- [SQLite FTS5][sqlite-fts]、[Strands 官方 repo][strands]、[LangGraph 文件][langgraph]、[LangGraph repo／授權][langgraph-repo]、[官方 MCP Python SDK][mcp-sdk]。

[ac-overview]: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/what-is-bedrock-agentcore.html
[ac-price]: https://aws.amazon.com/bedrock/agentcore/pricing/
[ac-regions]: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/agentcore-regions.html
[ac-cross-region]: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/cross-region-inference.html
[runtime-contract]: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-service-contract.html
[runtime-mcp-contract]: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-mcp-protocol-contract.html
[runtime-oauth]: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-oauth.html
[gateway-mcp]: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-target-MCPservers.html
[gateway-auth]: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-building-adding-targets-authorization.html
[identity-custom]: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/identity-add-oauth-client-custom.html
[memory]: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/memory.html
[observability]: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability.html
[harness]: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/harness.html
[policy]: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/policy.html
[evaluations]: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/evaluations.html
[optimization]: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/optimization.html
[events-mcp]: https://docs.aws.amazon.com/events/latest/devguide/mcp-server.html
[events-signin]: https://docs.aws.amazon.com/events/latest/devguide/auth-signing-in.html
[events-quotas]: https://docs.aws.amazon.com/events/latest/devguide/quotas.html
[nova-price-blog]: https://aws.amazon.com/blogs/machine-learning/prompting-for-the-best-price-performance/
[nova-price-campaign]: https://aws.amazon.com/cn/campaigns/nc202501/
[nova-micro]: https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-amazon-nova-micro.html
[bedrock-price]: https://aws.amazon.com/bedrock/pricing/
[s3-price]: https://aws.amazon.com/s3/pricing/
[kb-data]: https://docs.aws.amazon.com/bedrock/latest/userguide/kb-how-data.html
[kb-s3]: https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-vectors-bedrock-kb.html
[kb-retrieval]: https://docs.aws.amazon.com/bedrock/latest/userguide/kb-how-retrieval.html
[sqlite-fts]: https://www.sqlite.org/fts5.html
[strands]: https://github.com/strands-agents/harness-sdk
[langgraph]: https://docs.langchain.com/oss/python/langgraph/overview
[langgraph-repo]: https://github.com/langchain-ai/langgraph
[mcp-sdk]: https://github.com/modelcontextprotocol/python-sdk