# M3a · 室內與地標資料可用性備忘錄

- **研究日期：2026-11-07**
- **適用專案：** re:Invent Nova Copilot／Event Atlas
- **範圍：** Venetian／Palazzo／Venetian Expo、Wynn、Encore、Caesars Forum、Caesars Palace、MGM Grand、Mandalay Bay。
- **方法：** 唯讀檢查專案程式與地圖資產，並使用公開網頁搜尋、官方網站及 PDF 文字核對。
- **交付狀態：** 可支持資料選擇與最小方案決策；OSM 即時室內覆蓋、逐館 App 實測及部分授權條款仍有缺口。未修改專案檔案。

## 1. 建議與判斷

**建議先做「有來源的場館地標、已核實入口、樓層文字提示、官方地圖連結」，維持現有場館間估時；暫不提供房間級室內導航。**

目前可確認的情況是：

1. **現有專案沒有室內路網。** 建築輪廓、建築總樓層數及場館中心座標，均不能直接轉成入口、會議室所在樓層或可通行路徑。
2. **OSM 是本次找到授權最明確的可重用地理資料來源。** OpenStreetMap（OSM，協作式開放地圖）的資料採 ODbL 1.0（Open Database License，要求署名及特定資料庫衍生分享義務的授權）；是否足以導航，仍須逐筆檢查實際標籤與連通性。[OSM 授權說明](https://www.openstreetmap.org/copyright)
3. **多數場館有公開會議樓層圖，但未取得產品重製授權。** 可供查閱的 PDF，不等於可描圖、轉成 GeoJSON、內嵌、再散布或建立衍生路網。
4. **AWS 官方 App 已公開宣告室內地圖及逐步導航功能，但沒有找到可重用的地圖匯出或室內路網介面。** App 使用授權亦不是資料再散布授權。[2026 官方 App 頁](https://aws.amazon.com/events/reinvent/mobile-app/)、[AWS Events App 條款](https://aws.amazon.com/events/appterms/app/)

另有一項活動範圍差異：AWS 2026 FAQ 列出 Caesars Forum、Caesars Palace、Encore、MGM Grand、The Venetian、Wynn，未列 Mandalay Bay。FAQ 使用「including」，因此不能據此斷言 Mandalay Bay 不參與；其 **2026 活動用途應標為未確認**，不可直接沿用 2025 配置。[AWS 2026 FAQ](https://aws.amazon.com/events/reinvent/faqs/)

## 2. 狀態定義與證據界線

本備忘錄分開評估「資料存在」與「產品可重用」：

| 狀態 | 意義 |
|---|---|
| **Yes** | 已核實具有該項資料或能力；仍須看授權及適用日期。 |
| **Partial** | 僅部分範圍、歷史版本、文字資訊，或缺少導航必需條件。 |
| **No** | 目前取得的資料不能支持指定交付能力；不表示世界上不存在其他資料。 |
| **未驗證** | 查詢、存取、版本或授權未完成核實，不應當成零覆蓋。 |

本文的授權判斷是專案採用依據；「未找到授權」與「任何使用都違法」是不同結論。少量事實性名稱、圖面著作、資料庫、網站使用條款及服務合約也應分開處理。

除另列發布或更新日期外，網頁與 PDF 均以 **2026-11-07 查閱**為準；搜尋引擎的抓取日期不視為圖面修訂日期。

## 3. 專案目前實際持有什麼

已檢查：

- `atlas/routing.py`
- `data/venue_graph.json`
- `docs/routing.md`
- `explorer/THIRD_PARTY_NOTICES.md`
- `explorer/ui/build-map.mjs`
- `explorer/ui/public/geo/manifest.json`
- `explorer/ui/public/geo/campus.json`
- `explorer/official_catalog.py`
- `explorer/ui/src/session-facets.mjs`

### 3.1 路由仍是場館間估計

`venue_graph.json` 明確將場館座標描述為 OSM 建築輪廓的近似中心。程式中的 `:door` 節點是模型中的門口樞紐，**不是已測繪入口**；`intra_minutes` 是同館轉場時間假設，並非室內導航結果。

因此，目前不能把路線終點標成某扇門，也不能把館內固定分鐘數畫成實際走廊路線。

### 3.2 Event Atlas 地圖不是室內資料集

地圖 manifest 記錄：

- 來源時間：**2026-10-24T14:41:20Z**
- 3,066 個地物：1,460 個建築／建築部分、1,606 個道路地物。
- 授權：ODbL 1.0。
- 建築幾何使用來源輪廓，未知高度保持平面。

目前輸出的 `campus.json` 沒有保留 `indoor`、`level`、`level:ref`、`entrance` 或 `door` 欄位。這是輸出格式與產生器的限制，**不能推論 OSM 原始資料沒有這些標籤**。

其中：

- `levels_raw` 來自 **`building:levels`，表示建築總樓層數**。
- 所有建築的 `room_geometry` 都標為 `unverified`。
- manifest 所指的原始 OSM sample 與 geometry audit，在本次 checkout 的預期位置未找到，因此無法從原始節點重新清點入口。
- Mandalay Bay 的 `way/27858550` 已存在於地圖中，但 `venue_id` 為空，尚未綁定為場館。

### 3.3 API 的 `level` 不是實體樓層

`official_catalog.py` 保留 session 的 `level`；介面將此欄位標為「難度」，並處理 100／200／300／400 等課程級別。

**不得將 session `level` 對接 OSM `level=*`。** 實體樓層應使用另外的欄位，例如 `floor_label`。

## 4. 逐館資料與可交付能力

下表的「房間級路徑」指本專案目前能否以已取得且授權明確的資料交付，並非官方 App 是否具備該功能。

| 場館 | AWS 2026 公開活動地圖 | 公開場館樓層圖 | OSM 建築地標 | 已核實入口選擇 | 樓層提示 | 本專案房間級路徑 |
|---|---|---|---|---|---|---|
| Venetian／Palazzo／Expo | **Partial**：找到 2026 展商平面圖；非全館會議導航圖 | **Yes**：官方會議 PDF | **Yes／Partial**：已有多個輪廓，複合園區覆蓋仍須核對 | **未驗證** | **Partial**：圖面有明示樓層，尚未建立房間對照 | **No** |
| Wynn | **Partial**：官方 App 宣告；未取得逐館公開圖檔 | **Yes**：官方 resort map、capacity chart | **Partial**：已有命名輪廓，不能代表完整會議區 | **未驗證** | **Partial**：有 Upper／Lower Convention 標示 | **No** |
| Encore | **Partial**：官方 App 宣告；未取得逐館公開圖檔 | **Yes**：官方會議 PDF | **Yes／Partial**：已有輪廓，室內未核實 | **未驗證** | **Partial**：圖面明示部分 Second Level 空間 | **No** |
| Caesars Forum | **Partial**：官方 App 宣告；未取得逐館公開圖檔 | **Partial**：有公開活動平面圖及場館資料；官方最新完整底圖未取得 | **Yes**：已有輪廓 | **未驗證** | **Partial**：公開資料可協助理解場館配置，非完整樓層資料庫 | **No** |
| Caesars Palace | **Partial**：列為 2026 場館；未取得逐館公開圖檔 | **Yes／歷史版本**：官方主機仍提供檔名含 2014 的 PDF | **Yes／Partial**：有飯店及會議中心輪廓 | **未驗證** | **Partial**：歷史圖面有 Pool／Promenade 等名稱 | **No** |
| MGM Grand | **Partial**：官方 App 宣告；未取得逐館公開圖檔 | **Yes**：官方 Facilities Guide | **Yes／Partial**：飯店與 Conference Center 已分別識別 | **未驗證** | **Partial**：官方圖面明示 Level 1–3 | **No** |
| Mandalay Bay | **未驗證**：2026 活動用途待確認 | **Yes**：官方會議設施及樓層資料 | **Partial**：輪廓存在但尚未綁定場館 | **未驗證** | **Partial**：官方資料明示 South Convention Center Level 1–3 | **No** |

### 4.1 Venetian／Palazzo／Venetian Expo

**存在的資料：**

官方 `M_FloorPlans.pdf` 可讀取，共 16 頁，包含 Level 1–5、會議空間名稱及電梯、手扶梯等圖例。可作為核對樓層名稱與房間配置的參考，但本次未核實其修訂日期或與 2026 活動分區的一致性。[Venetian 官方樓層圖](https://www.venetianlasvegas.com/content/dam/vlv/meetings/downloadable-pdfs/M_FloorPlans.pdf)

另找到標題為 **AWS re:Invent 2026 Exhibitor Floor Plan** 的 Map Your Show 頁面，列出 `Level 2 Expo` 與 `Hall G | Sponsorship Meeting Center`。頁面存在已核實；互動圖形、完整資料及從 AWS 官方網站連入的授權鏈未完整核實。[2026 展商平面圖](https://awsreinvent2026.mapyourshow.com/8_0/exhview/exhview.cfm?osmode=false&pBounds=false&projection=false&refreshinterval=60)

**授權：**

Venetian 網站條款更新於 **2026-07-08**，允許個人非商業用途的單份查閱／下載，公開或商業使用內容須事先取得書面同意。因此，不能據公開 PDF 直接認定可重製為本專案地圖。[Venetian Terms of Use，第 8 節](https://www.venetianlasvegas.com/legal/terms-of-use.html)

**可建置：**

- **入口：未驗證。** 須取得入口節點與公共步行連線。
- **樓層：Partial。** 可先建立待核對的房間—樓層文字清單；本備忘錄不視為已批准大量擷取或公開散布。
- **房間級路徑：No。** 缺少授權明確的室內通行圖與 2026 臨時配置。
- 應分開識別飯店塔樓、Palazzo 及 Expo，避免所有 session 都導向同一個建築中心。

### 4.2 Wynn

官方 Resort Maps 頁提供整體 resort map 與 Wynn／Encore capacity charts。Wynn 圖面明示 **Upper Convention Promenade、Lower Convention Promenade**、跨層電梯／手扶梯及通往 Encore 會議區等地標。[Wynn 官方地圖入口](https://www.wynnlasvegas.com/meetings/resort-maps)、[Wynn Capacity Chart](https://www.visitwynn.com/documents/Wynn_Capacity_Chart.pdf)

**授權：未驗證。** 官方頁尾連到的 Terms of Use 本次無法完整讀取；未找到開放授權。不能因 PDF 可下載而視為可內嵌或描圖。

**可建置：**

- **入口：未驗證。** 現有命名輪廓不足以決定會議入口；搜尋範圍須涵蓋會議區，不能只取酒店塔樓。
- **樓層：Partial。** 保留官方 Upper／Lower 原名；不可自行換算為 `level=0/1`。
- **房間級路徑：No。** 圖上有方向標示，不等於已取得可計算的連通圖。
- 可先提供官方圖面連結及有出處的區域名稱。

### 4.3 Encore

官方 Encore Capacity Chart 可讀取，共 4 頁。會議圖列出 Encore Ballroom、各命名會議室及通往 Wynn 的方向，並將 **Bach／Beethoven** 區域標為 **Second Level**。[Encore 官方會議圖](https://cdn.wynnresorts.com/image/upload/v1745932355/visitwynn_pdfs_files/Encore_Capacity_Chart.pdf)

**授權：未驗證。** 與 Wynn 相同，沒有取得可供本專案重製的明確授權。

**可建置：**

- **入口：未驗證。**
- **樓層：Partial。** 對圖面明示的空間可建立來源紀錄；不能把所有 Encore 會議室推定在同一樓層。
- **房間級路徑：No。**
- OSM 塔樓的 `building:levels=52` 只代表來源中的建築總樓層標籤，與會議區所在樓層不同。

### 4.4 Caesars Forum

官方場館網站可定位，但本次工具只能讀到極少內容，未取得最新完整官方平面圖。官方 2022 factsheet 可確認 Forum Plaza、可變隔間與公共空間等場館特徵。[Caesars Forum 官方入口](https://www.caesars.com/meetings/properties/caesars-forum)、[官方 2022 factsheet](https://s202.q4cdn.com/508919455/files/doc_downloads/factsheets/caesars_forum/CAESARS-FORUM-fact-sheet-2022-UPDATED.pdf)

公開的 AIAA ASCEND 2024 活動手冊亦含 Caesars Forum 平面圖與入口／交通方向，但它是**其他活動的歷史配置**，不是 re:Invent 2026 圖面。[AIAA ASCEND 2024 手冊](https://eppro02.ativ.me/doc/clients/AIAA/AIAAASCEND24/library/pdf/AVAS_Full_Final_Program_3_2-compressed.pdf)

**授權：未驗證。** 未取得 Caesars 官方樓層圖的開放授權；不能以其他 Caesars 博彩、票務網站的條款替代本場館條款。

另有公開 AAPEX 2024 圖面，明載 Freeman 版權、專有資訊及用途限制。這類圖面應排除於可直接重用的來源之外。[AAPEX 2024 圖面及限制](https://www.aapexshow.com/wp-content/uploads/2024/07/AAPEX24-Caesars-Forum-L13136922-FP-2.pdf)

**可建置：**

- **入口：未驗證。** 歷史圖上的入口及橋接方向僅作查核線索。
- **樓層：Partial。** 不應以單層會議空間概念推定所有入口、停車場及連接橋都在同一標高。
- **房間級路徑：No。** 活動隔間配置仍可能改變。
- 名稱比對必須區分 **Caesars Forum、Caesars Palace 的 Forum Ballroom、Forum Shops**。

### 4.5 Caesars Palace

官方網站仍提供 8 頁會議設施 PDF，檔名包含 **2014**；文字列出 Pool Level、Promenade Level 與各會議空間。[Caesars Palace 官方歷史樓層資料](https://www.caesars.com/content/dam/meetings/PDFs/FloorPlans/Caesars_Palace_Las_Vegas-2014-FLOOR-PLAN.pdf)

檔名是年代警訊，不能證明其最後修訂年；本次未取得更新版本或 2026 活動對照。

**授權：未驗證。** 官方主機提供 PDF，不代表已授權本專案轉繪或再散布。

**可建置：**

- **入口：未驗證。**
- **樓層：Partial／歷史參考。** 必須重新核對 room alias 與現場樓層名稱。
- **房間級路徑：No。**
- 地圖應識別會議中心輪廓，避免只以整座飯店定位。

### 4.6 MGM Grand

官方 Document Library 直接列出 Property Map 與 Facilities Guide。其官方 PDF 可讀取，共 14 頁，明示 Conference Center **Level 1、2、3** 及各層會議空間。[MGM Grand 官方文件入口](https://mgmgrand.mgmresorts.com/en/meetings-groups/document-library.html)、[官方 Facilities Guide](https://static.mgmresorts.com/content/dam/MGM/mgm-grand/meetings/facilities-guide/mgm-grand-meetings-conference-center-facilities-guide.pdf)

**授權：受限。** MGM 條款第 4 節要求內容重製、再發布、散布等須有明確書面許可；第 7 節亦限制未經許可監看或複製內容。網站提供 View PDF，不等於提供產品重製權。[MGM Terms of Use](https://www.mgmresorts.com/policies/terms-of-use.html)

**可建置：**

- **入口：未驗證。** 飯店大廳、Conference Center、Monorail 與接送區須分別核對。
- **樓層：Partial。** 官方文件有足夠資訊供人工核實，但尚無本專案完整房間對照。
- **房間級路徑：No。**
- 房號即使看似符合樓層，也不可只靠第一位數決定所在層。

### 4.7 Mandalay Bay

官方會議設施頁明示：

- South Convention Center Level 1：Bayside 等空間。
- Level 2：Mandalay Bay Ballroom、Shoreline 等空間。
- Level 3：South Seas Ballroom 等空間。
- North Convention Center 另外列示。

官方亦提供 Capacities and Dimensions PDF。[Mandalay Bay 官方會議設施](https://mandalaybay.mgmresorts.com/en/meetings-groups/meeting-convention-facilities.html)、[官方容量與尺寸資料](https://static.mgmresorts.com/content/dam/MGM/mandalay-bay/meetings/documents/mandalay-bay-meetings-capacities-and-dimensions-new-version-two.pdf)

**授權：** 適用的 MGM 網站條款未提供開放重製權；不能直接轉為本專案底圖。

**可建置：**

- **入口：未驗證。** Resort 與 Convention Center 不可共用一個假定入口。
- **樓層：Partial。** 可辨識部分會議區樓層，2026 session 使用情況仍待核對。
- **房間級路徑：No。**
- 可先完成既有 OSM 輪廓的場館識別審核；不要因此自動把 Mandalay Bay 納入已確認的 2026 session 場館。

## 5. OSM 室內標籤覆蓋：已知與未知

### 5.1 逐館核實程度

以下 ID 來自專案 **2026-10-24** 衍生地圖，不代表已即時重查 OSM。建築總樓層數欄僅記錄現有資產中可見的值。

| 場館 | 既有 OSM 識別 | 已見 `building:levels` | `indoor=*` | 實體 `level=*` | `entrance=*` |
|---|---|---|---|---|---|
| Venetian／Expo | relation/7770314；way/30618090、111367819 | Venetian Tower：37；其餘未保留值 | 未驗證 | 未驗證 | 未驗證 |
| Wynn | way/205501268 | 未保留值 | 未驗證 | 未驗證 | 未驗證 |
| Encore | way/135291730、27910891 | Encore tower：52 | 未驗證 | 未驗證 | 未驗證 |
| Caesars Forum | way/762169780 | 未保留值 | 未驗證 | 未驗證 | 未驗證 |
| Caesars Palace | way/115672893、134949715 | 未保留值 | 未驗證 | 未驗證 | 未驗證 |
| MGM Grand | way/116770006、27897924、115093734 | 飯店輪廓：2；未命名建築部分：30 | 未驗證 | 未驗證 | 未驗證 |
| Mandalay Bay | way/27858550；尚未綁定場館 | 本次未核對 | 未驗證 | 未驗證 | 未驗證 |

**不能報告任何一館「OSM 室內覆蓋為零」。** 本次 shell 無法解析公開網路主機，網頁工具也未成功取得 Overpass／OSM 物件資料；既有產生器又沒有保留入口與室內標籤。

### 5.2 標籤存在後仍須驗證什麼

OSM 的 Simple Indoor Tagging（簡易室內標註方式）可表達房間、走廊、門、樓梯與樓層，但資料可能只有局部。`level=*` 的數值亦可能需要以 `level:ref=*` 對應現場樓層名稱。[OSM Simple Indoor Tagging](https://wiki.openstreetmap.org/wiki/Simple_Indoor_Tagging)、[OSM level 說明](https://wiki.openstreetmap.org/wiki/Levels)

| 發現的資料 | 可以支持 | 尚不能證明 |
|---|---|---|
| `entrance=*` 節點 | 顯示「OSM 標註入口」候選 | 是活動入口、對外開放、適合輪椅或接駁 |
| 有名稱及 `level=*` 的房間／地標 | 樓層提示、搜尋地標 | 能從指定入口抵達 |
| `indoor=corridor/area`、門及垂直連接 | 經連通性驗證後建立局部路網 | 全館完整、2026 活動期間可通行 |
| `building:levels=*` | 建築總樓層資訊 | 任一 session 所在樓層 |

公共步行導航還須考慮 `access`、`foot`、`wheelchair`、營業／開放時間及樓層連通性。[OSM 步行導航指引](https://wiki.openstreetmap.org/wiki/Guidelines_for_pedestrian_navigation)

### 5.3 後續可重現查詢

下列 Overpass 查詢**本次未成功執行**。範圍是涵蓋七館的初步搜尋框，不是場館產權邊界：

```overpass
[out:json][timeout:90][bbox:36.080,-115.190,36.135,-115.150];
(
  nwr["indoor"];
  nwr["level"];
  nwr["level:ref"];
  nwr["entrance"];
  nwr["door"];
  nwr["highway"="elevator"];
  way["highway"~"^(footway|path|pedestrian|steps)$"];
);
out meta geom;
```

取得結果後應：

1. 保留查詢、OSM 資料時間、物件 ID、版本、原始 tags 及幾何。
2. 依完整 resort／conference complex 歸屬地物，人工排除鄰館及非公共區域。
3. 分別清點入口、具樓層的地標、房間、走廊、樓梯及電梯。
4. 檢查入口到室外步道、房間到走廊、跨層連接是否真正連通。
5. 對每個可發布入口記錄活動適用性；OSM 標註本身不保證 re:Invent 開放狀態。

### 5.4 OSM 重用義務

OSM 資料可在符合 ODbL 的情況下用於產品，包括商業用途。應保留可見署名與授權連結，識別原始／衍生地理資料，並在觸發公開使用或散布義務時提供相應資料庫來源。

將 OSM 放進 MIT 程式庫，不會使地理資料自動變成 MIT；同時，OSM 地圖也不會自動使整個應用程式都必須採 ODbL。圖面作品、衍生資料庫及獨立資料層有不同判斷。[OSMF 法律 FAQ](https://osmfoundation.org/wiki/Licence/Licence_and_Legal_FAQ)、[OSMF Produced Work 指引](https://osmfoundation.org/wiki/Licence/Community_Guidelines/Produced_Work_-_Guideline)

## 6. 官方 re:Invent 地圖與 App：可用到哪裡

### 6.1 官方活動地圖

找到 AWS 官方主機上的 **2024 attendee guide**，包含 campus map，標示 Venetian、Wynn、Encore、Caesars Forum、MGM Grand、Mandalay Bay 等位置。它可證明歷史活動曾公開 campus map，但不能支持 2026 逐房間導航。[AWS 2024 attendee guide](https://pages.awscloud.com/rs/112-TZM-766/images/2024%20reInvent%20Attendee%20Guide_Energy%20%26%20Utilities_final.pdf?version=1)

2026 官方網站導向 Venues & Hotels 頁；本次取得的是動態頁面入口，未能核對完整圖面。沒有取得七館各自的 2026 公開室內圖檔。[2026 Venues & Hotels](https://registration.awsevents.com/flow/awsevents/reinvent2026/venueshotel/page/venuehotel)

**授權結論：**

- AWS Site Terms 更新於 **2025-06-04**，保留網站內容及供應商內容權利，限制衍生、商業重製與資料擷取。
- 活動地圖不能因為由 AWS 發布，就套用 AWS 文件網站的開放文件授權。
- Map Your Show 條款更新於 **2025-03-09**，授予個人非商業使用服務內容的有限許可；本次未核實 re:Invent 子站是否另有合約，但沒有取得開放重用權。

因此，現階段適合作為官方查閱入口；不應將圖面下載打包、轉描或嵌入本專案。[AWS Site Terms](https://aws.amazon.com/terms/)、[Map Your Show Terms](https://www.mapyourshow.com/map-your-show-terms-and-conditions)

### 6.2 AWS Events App 暴露的能力

依 2026 官方公開說明，可確認：

| 項目 | 狀態 |
|---|---|
| 室內地圖 | **Yes：官方公開宣告** |
| Turn-by-turn wayfinding，逐步導航 | **Yes：官方公開宣告** |
| App 內 shuttle times | **Yes：官方公開宣告** |
| 七館各自的樓層與房間完整度 | **未驗證：未逐館實測** |
| 可匯出的地圖、GeoJSON、室內圖網 | **未找到公開文件** |
| 可供第三方使用的導航 API | **未找到公開文件** |
| 穩定的場館／房間 deep link scheme | **未驗證** |

上述能力來自官方產品說明，不能當成已在本次研究操作驗證的結果。[AWS 2026 App 說明](https://aws.amazon.com/events/reinvent/mobile-app/)

公開 App Terms 最後更新於 **2021-09-08**。第 2.1 節是個人安裝與使用許可；第 2.3 節限制將服務納入自有程式、散布、製作衍生服務及逆向工程。故不能將正常使用 App 的權限解讀為抽取地圖資產或重播內部導航請求的許可。[AWS Events App Terms](https://aws.amazon.com/events/appterms/app/)

**可重用的最低範圍：** 官方公開功能說明的簡要轉述與外部查閱連結。App 內幾何、路網、定位與交通服務資料，須另有授權或正式文件；本次沒有取得。

## 7. 最小可行方案

### 第一步：立即可採用

**保留場館間估時，增加資料來源與官方查閱入口。**

- 明確將現有座標標為「場館近似位置」。
- 場館卡片提供官方地圖／會議設施頁的外部連結，點擊時離開本專案查閱。
- 分開飯店、會議中心及 Expo 的名稱與識別。
- 保留 `estimate: True`；不畫出未驗證的室內路線。
- Mandalay Bay 的 2026 活動用途維持待確認。
- 楼層未知時顯示「樓層待確認」，不預設為地面層。

### 第二步：取得 OSM 原始資料後

**只加入已實際找到的入口與樓層地標。**

入口至少應具備：

- 原始 OSM ID、版本、座標、查詢時間及授權。
- 正確場館歸屬。
- 與公共步道的連通證據。
- 公共進入／活動入口的驗證狀態。

未確認活動適用性的入口可以顯示為「OSM 標註入口」，不能推薦為「最佳入口」或「接駁入口」。

樓層資料應分開保存 `level_osm` 與現場 `floor_label`；沒有明確對照時，不互相換算。可先提供搜尋與文字提示，無須先建 3D 樓層模型。

### 第三步：選一條有完整證據的局部路徑試作

只有當某一入口到某一房間具備以下條件，才值得提供局部房間級導航：

- 幾何與路網使用權明確。
- 房門、走廊及跨層節點連通。
- 公共通行及活動期間開放狀態可核實。
- 相關樓層名稱已對應。
- 有實際走訪或其他可靠驗證。

不必以「整館完成」作為首次試作目標；但缺漏區域必須清楚停止導航。

### 建議資料紀錄

```text
venue_id
feature_type          # entrance / room / landmark / vertical_connector
name
source_type
source_url
source_id
source_version
observed_at
valid_for_event
license
reuse_status
coordinates           # 沒有來源時為 null
level_osm             # 沒有來源時為 null
floor_label           # 保留現場名稱
access_status
verification_status
```

**驗收條件：每個顯示的入口、樓層或連線，都能回到具日期的來源；未知值保留為未知。**

## 8. 絕不能虛構或誤標的資訊

1. **入口座標：** 不以建築中心、最近輪廓頂點或外牆中點代替。
2. **房間位置：** 不依房號、名稱、排序或模型猜測生成座標。
3. **樓層：** 不將課程難度 `level`、`building:levels` 或 3D 高度當成房間樓層。
4. **走廊與穿越：** 不在多邊形內畫直線，就宣稱能穿越牆、賭場或服務區。
5. **垂直連通：** 兩個點平面重疊，不代表有電梯、樓梯或公共跨層通道。
6. **活動開放狀態：** 不把歷年臨時通道、入口或隔間當成 2026 已確認配置。
7. **無障礙能力：** 不因看見電梯圖示就宣稱整條路線適合輪椅。
8. **時間與交通：** 不把假定接駁站、班距、館內分鐘數稱為即時或官方數據。
9. **來源與授權：** 不將公開 PDF、App 截圖或轉描結果標成 OSM／開放資料；轉成向量格式不會消除原本的權利限制。
10. **場館身分：** 不把 Caesars Forum、Palace 的 Forum Ballroom 與 Forum Shops 合併。

## 9. 尚待補足的項目

| 缺口 | 對交付的影響 | 下一個必要證據 |
|---|---|---|
| 七館 OSM 即時 `indoor/level/entrance` 覆蓋 | 無法提供可靠數量或完整度百分比 | 成功取得並保存原始查詢結果 |
| Wynn／Encore 完整適用條款 | 無法批准圖面重製 | 可讀取的官方條款或書面許可 |
| Caesars 官方最新底圖及重用條款 | 無法批准最新配置或轉描 | 官方現行圖面與權利聲明 |
| 七館 2026 App 實測 | 無法確認逐館房間、樓層與導航覆蓋 | 正常 App 使用中的逐館驗證紀錄 |
| AWS／供應商正式地圖整合權限 | 無法重用 App 資產及導航服務 | 公開開發文件或書面資料授權 |
| Mandalay Bay 2026 活動用途 | 無法視為已確認 session 場館 | 2026 官方場館頁或當期 session 資料 |
| PDF 圖面完整視覺核對 | 本次不支持精確門位或幾何量測 | 可用圖面渲染及逐頁檢查 |

本次有可用網頁搜尋；OSM 原始資料的即時取得失敗。PDF 結論以可讀文字及官方連結為主，未據此製作幾何或量測結果。

**獨立複核揭露：** 本次未完成 Claude Opus 5.5 獨立複核，也未驗證該模型的可用連線；本文為 Codex 的研究結果，以上缺口仍保留。