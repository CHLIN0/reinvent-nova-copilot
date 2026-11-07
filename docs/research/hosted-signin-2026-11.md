# M4a · Hosted deployment 與登入限制

日期：2026-11-07  
範圍：AWS Events 登入、部署選項、安全邊界、100 位使用者的 AWS 月成本估算。  
方法：唯讀檢查 repo，並透過 web search 重新取得 AWS 官方文件。未修改檔案、執行登入、轉送憑證、呼叫 Bedrock 或部署服務。

**結論：截至本次查閱，沒有文件支援的「零安裝、純 hosted web app」AWS Events 登入路徑。** 官方明確表示沒有 hosted redirect URI，登入程式必須在參加者電腦上執行。本機 helper 可以構成混合方案，但把 token 交給雲端是額外的憑證委託，尚未取得 AWS 對這種模式的支援確認。建議先向 AWS 申請專用 HTTPS callback 與登出 URL；取得確認前，維持 MIT 本機版，雲端可提供 synthetic demo。

下述架構是 **AWS 核准 hosted callback 後的 M4b 設計草案**，不是今天已可完成登入的部署成果。

## 1. 證據與判讀方式

本文區分三種狀態：

- **已核對**：2026-11-07 取得的官方文件，或當次讀取的 repo 程式碼。
- **工程判斷**：根據協定與程式結構提出的設計、風險和人日估算。
- **未驗證**：沒有官方明示、未做端到端實測，或未取得實際帳號／區域的報價。

官方頁面未顯示明確修訂日期時，本文日期代表查閱日期，不代表 AWS 發布日期。文件描述也不等於服務端行為已經實測。

Repo 查閱基準為當次 HEAD `190b839`，主要來源包括：

| Repo 來源 | 本次相關觀察 |
|---|---|
| [`atlas/official_auth.py`](../../atlas/official_auth.py) | PKCE、loopback callback、記憶體 token、程序共用 `_AUTH` |
| [`explorer/official_auth.py`](../../explorer/official_auth.py) | 相同 OAuth 端點，另接受 `localhost` callback |
| [`web.py`](../../web.py) | 本機 HTTP server，程序共用 agent、登入與寫入確認狀態 |
| [`atlas/profile.py`](../../atlas/profile.py) | 透過程序環境選取 profile，資料存於本機 JSON |
| [`atlas/official_mcp.py`](../../atlas/official_mcp.py) | 程序共用 MCP session |
| [`atlas/agent.py`](../../atlas/agent.py) | 預設 Nova Pro、最多六輪工具迴圈 |
| [`2026-11-07 roadmap`](../plans/2026-11-07-ux-overhaul.md) | M4 先釐清登入；T5 禁止 token 持久化；AgentCore 遷移另由 M2 評估 |

## 2. 現行官方登入契約

### Callback 限制仍然存在

官方 **Signing an attendee in** 明載：

> “There is no hosted redirect URI”

文件列出六個保留 loopback port：`8484`–`8489`，各自接受 `localhost` 與 `127.0.0.1`，路徑為 `/callback`。URI 完整比對，沒有 wildcard；授權與換 token 必須使用完全相同的字串。[AWS：Signing an attendee in，查閱 2026-11-07](https://docs.aws.amazon.com/events/latest/devguide/auth-signing-in.html)

這修正了原先背景資訊的一個細節：目前文件不只列 `127.0.0.1`，也接受 `localhost`。Repo 的 `atlas` 實作較窄，使用 `127.0.0.1:8484–8488`；`explorer` 接受兩種 host，但也排除 `8489`。排除該 port 是本機服務衝突的選擇，不是 AWS 只註冊五個 port。

瀏覽器導向 `127.0.0.1` 時，目標是**參加者的電腦**。在雲端容器內開啟相同 port，無法接到那個 callback；換成 ALB 網域或 tunnel URL，也不會自動符合已註冊 URI。

### 端點與值

下表已於 2026-11-07 核對。Client ID 是公開共用值，登入使用 **Proof Key for Code Exchange（PKCE，以一次性 verifier 保護授權碼交換）**，沒有需要藏在程式中的 client secret。[AWS：Endpoints and values](https://docs.aws.amazon.com/events/latest/devguide/auth-endpoints.html)

| 項目 | 值 |
|---|---|
| Authorization endpoint | `https://oauth.awsevents.com/oauth2/authorize` |
| Token endpoint | `https://oauth.awsevents.com/oauth2/token` |
| Revocation endpoint | `https://oauth.awsevents.com/oauth2/revoke` |
| Broker logout | `https://oauth.awsevents.com/logout` |
| Builder ID logout | `https://idp.awsevents.com/oidc/logout` |
| Public client ID | `7vmom55m1qstvq8i71ph127bfq` |
| Scope | `openid email events/access` |
| Identity provider | `AWSBuilderID` |
| Access token | JWT，文件列有效期 60 分鐘 |
| Refresh token | 不透明字串，文件列有效期 30 天 |

授權流程使用 authorization code、每次新建的 PKCE S256 verifier/challenge，以及隨機 `state`。Events API 接受 access token；ID token 不能拿來替代。[AWS：Signing an attendee in](https://docs.aws.amazon.com/events/latest/devguide/auth-signing-in.html)

### 更新、撤銷與儲存

實作應以 token 回應的 `expires_in` 排程更新；若 refresh 回應帶回新 refresh token，必須替換舊值。API 回傳 `401` 時，只更新並重試一次，仍失敗就重新登入。Refresh 不會延長 Builder ID 瀏覽器登入 session。[AWS：Keeping the attendee signed in，查閱 2026-11-07](https://docs.aws.amazon.com/events/latest/devguide/auth-refreshing.html)

AWS 的安全指引要求 access token 僅送往 `https://api.awsevents.com`；送往其他地方會向該接收方揭露憑證。瀏覽器內的 token 應僅留在記憶體；伺服器端 token 應留在伺服器端。這是 helper 上傳模式必須正面處理的信任邊界，不能只因 HTTPS 或 PKCE 就視為已解決。[AWS：Handling tokens safely，查閱 2026-11-07](https://docs.aws.amazon.com/events/latest/devguide/auth-handling-tokens.html)

撤銷 refresh token **不會立即使已發出的 access token 失效**；既有 access token 可用至到期。完整登出還涉及 Builder ID 與 broker 的瀏覽器 session，且 logout URI 有獨立的註冊清單。本機 `/callback` 的註冊不代表任意 hosted `/logout` 也可使用。[AWS：Signing an attendee out，查閱 2026-11-07](https://docs.aws.amazon.com/events/latest/devguide/auth-signing-out.html)

## 3. 五條路徑的比較

以下 effort 是一位熟悉 repo 的工程師之**工程估算**，不是已量測工時。各登入選項之外，共用的多人隔離、部署、成本控制與驗證約另需 **8–15 人日**；AWS 審核等待時間不包含在內。

| 路徑 | 今天的可行性 | 安全重點 | 使用者摩擦 | 額外 effort |
|---|---|---|---|---|
| 直接 hosted HTTPS redirect | **目前沒有文件支援**；既有共用 client 無此 callback | 核准後可讓 token 全程留在 backend | 最低，只需瀏覽器 | 核准後約 3–5 人日 |
| Device-style flow | **未驗證、不可列為可交付方案**；未找到此 Events client 的 device grant 文件 | 需真正的授權伺服器支援，不能自行畫一個配對碼頁取代 | 若受支援，通常低至中 | AWS 確認後約 2–4 人日 |
| 本機 helper 完成 OAuth，再上傳 token | 本機 OAuth 有文件依據；**上傳混合流程未實測、支援範圍未確認** | 雲端取得代操作能力；需安全配對、明確同意與憑證生命週期管理 | 中至高，需安裝／執行 helper | 單一桌面 OS 約 5–10 人日 |
| Desktop／Electron wrapper | **本機登入可行**；尚未完成包裝實測 | 系統瀏覽器登入，token 留主程序，限制 renderer 權限 | 需下載、安裝、更新；手機另有缺口 | 多 OS 發行約 10–20 人日 |
| 向 AWS 申請 registered redirect | **需要外部核准**；未找到公開自助註冊程序 | 最符合 hosted backend 持有 token 的設計 | 核准後最低 | 申請資料約 1 人日；整合如第一列 |

### 3.1 Hosted redirect：不能靠部署設定補出來

把前端與 backend 放到 AWS，並不改變 OAuth client 的 callback 註冊。自建 Cognito user pool 也只能解決自己應用程式的登入，不能自行取得被 AWS Events 接受的 attendee token。

官方 MCP 文件列有個別 installed client 的 callback 設定，顯示 AWS 確實維護其他註冊值；這不代表任意第三方網域可以使用那些註冊，或存在開放的動態註冊機制。[AWS：Using the MCP server，查閱 2026-11-07](https://docs.aws.amazon.com/events/latest/devguide/mcp-server.html)

### 3.2 Device flow：目前只有待確認的可能性

**OAuth 2.0 Device Authorization Grant（裝置授權流程，讓使用者在另一個瀏覽器輸入代碼授權）**需要授權伺服器提供 device authorization endpoint，並支援相應 grant。[RFC 8628，2019-08；查閱 2026-11-07](https://www.rfc-editor.org/rfc/rfc8628.html)

本次查閱的 Events 認證文件未提供這些端點或此 client 的啟用方式。這表示**沒有可據以實作的公開契約**，不等於已證明所有未公開能力都不存在。

其他 AWS 產品的 device flow、IAM OAuth 或 token exchange，不能直接推論適用於 `oauth.awsevents.com` 與 `events/access`。必須由 AWS 確認對應 issuer、client、scope 與 Events API 接受的 token。

### 3.3 本機 helper：技術上可設計，但不是低風險捷徑

helper 能接住合法的 loopback callback，完成本機 OAuth；困難在於後續把憑證安全地交給正確的 hosted session。

若 AWS 確認允許此模式，最低限度應採：

1. **先建立配對。** Hosted 頁面建立伺服器端 session；helper 與該 session 透過短效、單次、高熵配對憑證綁定。使用者確認目的網域與配對對象。短顯示碼只能輔助確認，不能是唯一上傳授權。
2. **本機先綁定 callback，再開始 OAuth。** 僅監聽 loopback，驗證 Host、path、`state`，並使用一次性 PKCE verifier；拒絕過期與重播。
3. **helper 只信任固定 hosted origin。** 不接受任意目的 URL，也不提供通用 token forwarder。
4. **以 HTTPS POST 直接交給 backend。** Token 不經瀏覽器 JavaScript、剪貼簿、URL 或 browser storage。OAuth 本身必要的 callback `code` query 是例外：callback 不載入第三方資源、不記錄完整 URL，完成後導向乾淨頁面。
5. **優先只上傳 access token。** Refresh token 留在 helper，降低雲端長期代操作能力；代價是 helper 必須持續執行並補充 access token，否則到期後需重連。上傳 refresh token 會擴大風險，不應列為預設。
6. **登出必須協調兩端。** Hosted backend 清除自己的副本；helper 負責 refresh token 撤銷。不能承諾外流的 access token 立即失效。

PKCE 保護的是授權碼交換，**不保護交換完成後的 bearer token**。即使應用只展示唯讀功能，取得的 `events/access` token 仍不能被假設具有唯讀權限。

另一種混合模式是 token 始終留在 helper，由 helper 呼叫 Events API，只把必要資料交給雲端。它能減少憑證外流面，但仍需要安裝、可信配對、受限制的命令通道與資料同意；也不是純 hosted 登入。

### 3.4 Desktop／Electron：可用的本機產品路徑

桌面版可沿用已文件化的 loopback OAuth，但應在**系統瀏覽器**完成 Builder ID 登入，避免把登入頁放進可讀取使用者憑證的內嵌 WebView。這符合 native OAuth 的標準建議。[RFC 8252，2017-10，§8.12；查閱 2026-11-07](https://www.rfc-editor.org/rfc/rfc8252.html)

Electron 版本應將 token 留在主程序，renderer 使用 sandbox、context isolation，關閉 Node integration，並僅暴露狹窄的 IPC 操作介面。單純用 Electron 包住遠端網站，不會自動得到這些隔離。[Electron：Security，查閱 2026-11-07](https://www.electronjs.org/docs/latest/tutorial/security)

它符合「他人可自行使用」的部分需求，但仍須處理下載信任、簽章、更新與多 OS 支援，無法提供零安裝的 web 體驗。

## 4. 現有程式不能直接變成多人服務

這些是部署前提，不是本次已修正的缺陷：

| 現況與位置 | Hosted 版必須改成 |
|---|---|
| `web.py:34` 的 `_state` 共用 agent、登入及 `allow_write` | 每位使用者獨立的對話、登入狀態與操作確認 |
| `atlas/official_auth.py:316` 的程序共用 `_AUTH` | 依伺服器驗證身份取得的逐使用者 auth context |
| `atlas/profile.py:55` 以名稱／程序環境選 profile | 由 session 決定 owner，禁止前端任意指定他人 profile |
| `atlas/official_mcp.py:56` 的共用 `_session` | 每位使用者獨立 MCP session |
| `atlas/catalog.py:233` 的程序快取 | 先驗證讀取者的 event 權限，再使用合適範圍的快取 |
| `web.py:187` 的 loopback Host／Origin allowlist | 明確的 hosted origin 與可信 proxy 設定，保留跨站防護 |

如果只把 listener 改成 `0.0.0.0`，不同使用者可能共用 token、對話或寫入授權。這是多人部署的阻擋條件。

此外，roadmap 的 T5 明確禁止 token 落盤。因此「逐使用者伺服器端狀態」不能被解讀為已授權把 refresh token 存到 DynamoDB 或 Secrets Manager。Profile、plan、成本紀錄可以持久化；憑證預設仍留在 RAM。若要讓登入跨重啟保留，必須另行決定 token custody 與儲存政策。

## 5. AWS 核准 callback 後的最小 hosted 架構

這是一個 **100 位月活躍使用者的試營運架構**，不是 100 人同時使用的容量保證。

```text
參加者瀏覽器
  │ HTTPS；僅持有 opaque app-session cookie
  ▼
ALB + ACM 憑證
  ▼
ECS Fargate：單一容器、單一 application worker
  ├─ 靜態 UI + Backend for Frontend（BFF，專供此 UI 的後端）
  ├─ 每位使用者的 OAuth／agent／MCP context
  ├─ DynamoDB：profile、plan、session metadata、cost ledger
  ├─ Secrets Manager：應用程式 secrets
  ├─ Bedrock：透過 IAM task role 呼叫
  └─ AWS Events：使用該參加者的 access token

AWS OAuth ──► HTTPS /oauth/callback
              此箭頭須先取得 AWS 註冊核准
```

### 容器與網路

- ECR 保存映像；Fargate 起始配置為 Linux x86、`0.5 vCPU / 1 GiB`。
- ALB 位於兩個 Availability Zone 的 public subnet。
- Fargate task 配 public IPv4，以 internet gateway 對外連線；入站 security group 只接受 ALB。
- 此低成本版本不配置 NAT Gateway。AWS 文件支援 Fargate public subnet 加 assigned public IP 的對外連線方式；必須限制入站規則。[AWS ECS：Connect applications to the internet，查閱 2026-11-07](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/networking-outbound.html)
- 使用正式 HTTP application server，明確處理健康檢查、併發、timeout 與 graceful shutdown；不直接公開現有本機 `http.server`。
- 不在 M4 預設導入 AgentCore；依 roadmap，該決定須由 M2 的同工作負載量測支持。

### 身份與逐使用者狀態

瀏覽器只持有 `Secure`、`HttpOnly`、適當 `SameSite` 的不透明 session cookie。OAuth callback 成功後輪替 app session ID，避免 session fixation；需要寫入的 browser request 另做跨站請求偽造防護。

Backend 必須根據可信 issuer 與 signing keys 驗證身份，再建立內部 `user_id`。不可只解碼 JWT 或相信 helper 提供的 email。實際 ID token audience、access token 的 client/audience 欄位、穩定 subject 與 token type 規則，須取得 AWS 契約後實作，不能憑一般 Cognito 經驗硬填。

DynamoDB 可依內部 owner 與 event 分區保存：

```text
USER#<internal-user-id>
  PROFILE
  EVENT#<event-id>#PLAN
  EVENT#<event-id>#SNAPSHOT
  CHAT#<conversation-id>#<sequence>
  COST#<timestamp>#<invocation-id>
```

每個 API 都從已驗證 session 取得 owner；前端傳入的 `user_id`、profile 名稱或 partition key 不能決定授權。對話、write confirmation、refresh lock、MCP session 與私人快取均須隔離。

需要 event registration 的 catalog 也必須保留權限檢查，不能用 BR 的 token 預載後公開給所有人。官方區分登入與 event registration：缺 token 可得到 `401`，有 token 但未註冊則為 `403`。[AWS：Access token and event registration，查閱 2026-11-07](https://docs.aws.amazon.com/events/latest/devguide/auth-two-requirements.html)

### Token 與 secrets

- Token、PKCE verifier 僅留在逐使用者 RAM context；DynamoDB 只保存不含憑證的 session metadata。
- 單一 task **還不足以**保證 RAM token 可取得；試營運先使用單一 application worker，避免多 worker 各有一份不相通的 token map。
- Task 重啟或部署會要求重新登入，UI 必須明示。增加 worker／副本前，要先解決 credential owner 與路由；不能只加 sticky session 就宣稱問題已解決。
- 每位使用者序列化 refresh，防止 rotation 競態；logout 後不得由尚未完成的 refresh 把登入狀態復活。
- Secrets Manager 保存應用 secrets；公開 OAuth client ID 不需要當 secret。AWS 存取使用 IAM task role，不把長期 AWS keys 或 `.env` 打進映像。
- Profile、plan 與 ledger 加密並限制存取；token 不進 browser、模型 prompt、trace 或錯誤回應。

OAuth callback 的 query 含授權碼。Application log 不記錄它，設定 `Cache-Control: no-store`、`Referrer-Policy: no-referrer`，並立即導向固定的乾淨 URL。本試營運不啟用 ALB access logs；未來若啟用，必須先處理 callback query 的記錄風險，不能假設 ALB 已自動遮罩。

## 6. 每位使用者的成本 ledger

Ledger 應記錄**每次實際模型 invocation**，包含工具迴圈、中間回應、重試、briefing 與 translation；不能只計算最後呈現給使用者的一段回答。

建議最小紀錄：

```text
timestamp, internal_user_id, event_id, feature,
interaction_id, invocation_id, attempt,
model_id, region, service_tier,
input_tokens, output_tokens, cache_usage,
price_snapshot_id, currency, estimated_usd,
usage_status
```

價格快照另保存來源、查閱日期、適用區域與計價單位。成本紀錄不包含 prompt、token、行程內容或健康／住宿等 profile 原文。

控制方式應包括：

- 呼叫前原子預留該使用者的額度，完成後依回傳 usage 結算。
- 限制迴圈、輸出長度、單人併發及每日／每月用量；全站另有總預算。
- 重試若產生新的計費 invocation，分別記錄；同一筆 usage 重送入帳則去重。
- Timeout 或缺少 usage 時記為 `unknown`，不能算成零；後續與 AWS 帳單核對。
- 共用基礎設施分攤與直接模型成本分開呈現。內部估算不等於 AWS 最終帳單，也不自動構成對使用者收費授權。

Events API 自身另有逐參加者、逐操作 quota，不能只做全站 rate limit。遇到 `429` 應遵守 `Retry-After`。[AWS：Quotas and throttling，查閱 2026-11-07](https://docs.aws.amazon.com/events/latest/devguide/quotas.html)

## 7. 100 位使用者的每月成本估算

### 假設與可信度

- 區域：`us-east-1`；每月 `730` 小時。
- 100 位月活躍使用者，不代表同時在線 100 人。
- 一個 Fargate task，不是應用層高可用配置。
- On-demand，未扣 credits、Free Tier 或承諾折扣。
- 價格查閱日為 2026-11-07；用量及容量均未實測。

### 基礎設施

| 項目 | 計算／假設 | USD／月 |
|---|---|---:|
| Fargate | `730 × 3600 × (0.5 × 0.000011244 + 1 × 0.000001235)` | 18.02 |
| ALB | `730 × (0.0225 + 0.008 × 1 LCU)` | 22.27 |
| Public IPv4 | 起始估三個：ALB 兩個、task 一個；`3 × 730 × 0.005` | 10.95 |
| DynamoDB | 約 1 GB、200 萬 WRU、200 萬 RRU，另留少量空間 | 2.00 |
| Secrets Manager | 兩個 secrets 與少量讀取 | 0.81 |
| KMS | 一個尚未輪替的自管 key、約一萬次對稱操作 | 1.03 |
| ECR、CloudWatch、DNS、小量流量／備份 | 用量預留額，未逐項實測 | 5–8 |
| **基礎設施合計** | | **約 60–63** |

單價依據：

- Fargate 官方頁面的 N. Virginia Linux x86 範例列出上述 CPU／memory 秒價。[AWS Fargate Pricing](https://aws.amazon.com/fargate/pricing/)
- ALB 為每小時 `$0.0225`，加 `$0.008/LCU-hour`。表中的平均一個 LCU 是估算用量，不是必須購買的最低 reservation。[Elastic Load Balancing Pricing](https://aws.amazon.com/elasticloadbalancing/pricing/)
- Public IPv4 為每個每小時 `$0.005`；ALB 擴展或部署重疊可能增加位址數。[Amazon VPC Pricing](https://aws.amazon.com/vpc/pricing/)
- DynamoDB Standard 範例單價為每百萬 WRU `$0.625`、RRU `$0.125`，storage `$0.25/GB-month`；實際單位消耗取決於 item 大小與交易模式。[DynamoDB Pricing](https://aws.amazon.com/dynamodb/pricing/)
- Secrets Manager 為 `$0.40/secret-month`，加 `$0.05/10,000` 次 API 呼叫。[Secrets Manager Pricing](https://aws.amazon.com/secrets-manager/pricing/)
- KMS 自管 key 起價 `$1/month`，對稱操作範例為 `$0.03/10,000` 次；key rotation 可能增加費用。[KMS Pricing](https://aws.amazon.com/kms/pricing/)
- 小項預留額包含 ECR 儲存與 DNS zone；官方分別列 `$0.10/GB-month` 與首批 hosted zone `$0.50/month`。[ECR Pricing](https://aws.amazon.com/ecr/pricing/)、[Route 53 Pricing](https://aws.amazon.com/route53/pricing/)

### Nova Pro 模型用量

**價格狀態：估算基準有官方範例支持，但部署時單價仍未驗證。** 本次取得 Bedrock／Nova pricing 頁面後，文字擷取未呈現 Nova Pro 的完整區域與 tier 價格表。AWS 官方 solution 成本範例使用 input `$0.0008/1K`、output `$0.0032/1K`，本文以此試算；不能把它當作部署帳號的正式報價。[AWS：Generative AI Application Builder cost examples，查閱 2026-11-07](https://docs.aws.amazon.com/solutions/latest/generative-ai-application-builder-on-aws/cost.html)

假設：

```text
100 位使用者
× 每人每月 30 次互動
× 每次互動平均 3 次 Converse invocation
= 9,000 次 invocation

每次 invocation 平均：
4,000 input tokens，包含 system、history 與 tools
800 output tokens
```

因此：

| 用量 | 計算 | USD／月 |
|---|---|---:|
| Input | 3,600 萬 tokens × `$0.80/百萬` | 28.80 |
| Output | 720 萬 tokens × `$3.20/百萬` | 23.04 |
| **模型合計** | | **51.84** |
| **基礎設施＋模型** | | **約 112–115** |

規劃可取整為 **US$110–120／月**，試營運預算先抓 **US$150／月**，並用實際 ledger 修正。這是上述工作負載的估算，不是固定的 100 人費率；模型用量十倍時，模型費即約 `$518`。

未包含開發工時、網域註冊、桌面簽章、稅金、Support、額外防護服務，以及**尚未確認的 Events API 費用**。本文不宣稱 Events API 免費。

第二個相同 Fargate task 至少增加約 `$18.02` compute 與 `$3.65` IPv4；它還需要先解決 RAM token 的多副本設計。單一小容器是否能承受活動期間尖峰，仍須壓測。

## 8. MIT、驗證範圍與未解問題

Repo 已有 [MIT License](../../LICENSE)，可維持程式開源與自行執行路徑。Hosted 服務的 credentials、attendee records 與部署 secrets 不應進入公開 repo。

MIT 不會自動涵蓋 AWS 活動資料、品牌或第三方地圖資料。[既有 third-party notices](../../explorer/THIRD_PARTY_NOTICES.md) 已區分程式、地圖來源與官方資料；本次沒有確認 catalog 大量重發布的授權。Hosted 版應透過使用者自己的授權讀取受限制資料，並向 AWS 確認可接受的快取與再利用範圍。

本次完成官方文件、程式結構與試算數學核對，以下仍未完成：

- Hosted callback、device grant、helper token handoff、Electron 的端到端登入測試。
- 實際 token issuer／JWKS／身份欄位契約確認。
- 多人隔離、安全測試、負載與容量測試。
- 實際部署區域／tier 的 Nova Pro 單價與帳單核對。
- AWS 對第三方 hosted token custody、資料使用及費用的確認。

依工作規約，已透過 [`claude-delegate`](https://github.com/CHLIN0/reinvent-nova-copilot) 的唯讀 architecture 路徑要求獨立審查；呼叫在 120 秒後逾時，沒有取得審查結果或可核實的實際模型證據。因此，**本 memo 尚未完成 Claude Opus 5.5 獨立審查**，不能把 `opus` alias 當作已驗證模型。

## 9. 建議與應向 AWS 詢問的事項

**建議：先申請 AWS 核准的專用 HTTPS redirect，作為個人化 hosted 版的前提；核准前保留本機 MIT 版，雲端只提供明確標示的 synthetic demo。** 不以未確認的 device flow 或 token-upload helper 作為公開 hosted 版的既定登入方案。

應向 AWS Events API 團隊提出以下具體問題；目前未確認有公開自助申請入口：

1. **Hosted client 註冊**  
   是否接受公開、多使用者、MIT 開源應用？能否為自有網域註冊精確 HTTPS callback 與獨立 logout URI？應使用專用 client，還是現有共用 client？審核條件與聯絡窗口為何？

2. **Server-side token custody**  
   是否允許應用 backend 代表 attendee 保存、更新及使用 Events token？需要哪些 consent、retention 與刪除安排？若 helper 上傳 access token 或 refresh token，是否屬受支援模式？

3. **其他授權流程**  
   此 Events client／scope 是否支援 RFC 8628 device grant、核准的 code relay 或 token exchange？若支援，請提供正式端點與契約。Installed MCP client 的特殊 callback 是否有第三方申請程序？

4. **身份與生命週期契約**  
   請提供可信 issuer、JWKS、ID／access token 的 client 或 audience 驗證規則、穩定 user subject，以及 refresh rotation、撤銷與重新登入行為。

5. **多人代管條件**  
   除逐參加者 quota 外，是否有共用出口 IP、client 或整體服務限制？Catalog 快取、資料再利用與費用規則為何？

**若 AWS 不提供核准的 hosted callback 或其他正式授權路徑，則零安裝、純 hosted 的個人化登入目前不可交付；有文件依據的登入產品仍須包含在參加者電腦上執行的本機元件。**