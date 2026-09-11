# MaskGuard

**[English](README.md) | [繁體中文](README.zh-TW.md)**

圖片敏感資料偵測與遮罩處理管線。透過本機 OCR + 規則式／本機 AI 分類，
偵測圖片中的個人資料、財務資料、憑證與商業機密文字，並就地進行遮罩／
模糊化／馬賽克處理。完整規格請見 `Skill.md`。

## 安裝設定

```bash
python -m pip install -e .
```

OCR 需要安裝 **Tesseract 執行檔** 並加入 `PATH`（這與 `pytesseract`
Python 套件是分開的——`pytesseract` 只是呼叫 Tesseract 執行檔的一層薄包
裝，兩者都需要）。

### Windows

```powershell
winget install --id UB-Mannheim.TesseractOCR -e
```

會安裝到 `C:\Program Files\Tesseract-OCR`，並（重新開啟終端機/工作階段
後）把 `tesseract.exe` 加入 `PATH`。**本專案已確認的已知問題：**
winget/UB-Mannheim 套件附帶的 `tessdata` 只包含 `eng`（+`osd`）——
`chi_tra`（繁體中文）**未包含在內**，需要另外手動加入：

```powershell
# 下載 Tesseract 官方專案發布的語言包：
Invoke-WebRequest -Uri "https://github.com/tesseract-ocr/tessdata/raw/main/chi_tra.traineddata" -OutFile "$env:LOCALAPPDATA\tessdata\chi_tra.traineddata"
Copy-Item "C:\Program Files\Tesseract-OCR\tessdata\eng.traineddata" "$env:LOCALAPPDATA\tessdata\"
Copy-Item "C:\Program Files\Tesseract-OCR\tessdata\osd.traineddata" "$env:LOCALAPPDATA\tessdata\"
# 讓 Tesseract 指向一個不需要系統管理員權限即可寫入的語言資料目錄：
$env:TESSDATA_PREFIX = "$env:LOCALAPPDATA\tessdata"
```

（直接寫入 `C:\Program Files\Tesseract-OCR\tessdata\` 需要系統管理員權限
的終端機——把 `TESSDATA_PREFIX` 指向使用者可寫入的副本可以避免這個問
題。）以 `tesseract --list-langs` 驗證——應會列出 `chi_tra`、`eng`、
`osd`。

若 `tesseract` 完全不在 `PATH` 中，請開啟新的終端機（winget 只會更新
登錄檔中的 `PATH`，不會更新目前已開啟的終端機工作階段），或直接指定執
行檔路徑：`LocalOcrEngine(tesseract_cmd=r"C:\Program Files\Tesseract-OCR\tesseract.exe")`。

### Linux（Debian/Ubuntu）

```bash
sudo apt-get update
sudo apt-get install -y tesseract-ocr tesseract-ocr-chi-tra tesseract-ocr-eng
```

其他發行版：`dnf install tesseract tesseract-langpack-chi_tra`（Fedora）
或自行從 https://github.com/tesseract-ocr/tesseract 建置。以
`tesseract --list-langs` 驗證。

### macOS

```bash
brew install tesseract tesseract-lang   # tesseract-lang 包含所有語言包，含 chi_tra
```

以 `tesseract --list-langs` 驗證。

### 自行驗證環境

```bash
python tests/e2e/_environment.py
```

會印出 Python 版本、`pytesseract` 是否能匯入、實際解析到的 `tesseract`
執行檔路徑、`tesseract --version` 的輸出，以及 `eng`/`chi_tra` 是否實際
可用——這與 E2E 測試套件（`pytest -m e2e`）在每次測試前，透過
`tests/e2e/conftest.py` 的 `ocr_env` fixture 所做的檢查相同。若環境尚未
就緒，E2E 測試會回報 **SKIPPED**（絕不會假裝通過），並具體指出缺少哪
一項。

## 使用方式

```bash
imgmask input.png --output ./output
imgmask input.png --output ./output --mode strict --verify
imgmask ./input_folder --output ./output --recursive
```

輸出目錄結構（Skill.md §24）：

```
output/
├── processed/<name>_masked.png
├── report/<name>_masked.json      # processing_report.json —— 不含原始敏感文字
└── audit.log                      # 只附加不覆寫，只記錄類型/信心度/區域
```

`--mode strict` 會啟用 Skill.md §40 的嚴格模式：僅使用本機 OCR/AI、不
上傳雲端、必須通過驗證，且驗證失敗時會完全阻擋輸出（不會寫出任何圖
片）。

## HTTP API（Phase 8.1）

選用的 FastAPI 層（`maskguard/api/`）以 HTTP 方式提供與 CLI 相同的
MaskGuard 核心管線，供瀏覽器/非終端機的用戶端使用。這只是一層薄封裝——
每個請求都直接呼叫 `Pipeline`/`WholeImageSanityScanner`，與 `imgmask`
CLI 使用的是完全相同的類別；偵測/風險/政策/遮罩/驗證/OCR 邏輯全部都在
核心（Core），不在任何 API 路由中。CLI 完全不受影響，行為與過去相
同——CLI 與 API 是建立在同一個核心之上的兩個獨立前端。

### 安裝並啟動伺服器

```bash
python -m pip install -e ".[api]"   # 在核心之上安裝 fastapi/uvicorn/pydantic/python-multipart
python -m uvicorn maskguard.api.app:app --host 127.0.0.1 --port 8000
# 或者：
python -m maskguard.api
```

預設只綁定 `127.0.0.1`（僅限本機）。**請勿**在未加上反向代理、認證與
TLS 的情況下使用 `--host 0.0.0.0`（或設定
`MASKGUARD_API_HOST=0.0.0.0`）——Phase 8.1 本身不包含任何認證機制（那是
後續 Phase 的範圍）。

### 端點

全部位於 `/api/v1/` 之下。伺服器啟動後可在
`http://127.0.0.1:8000/docs` 查看互動式文件。

| 方法 | 路徑 | 用途 |
|---|---|---|
| GET | `/api/v1/health` | 存活檢查。不會執行 OCR。 |
| POST | `/api/v1/analyze` | 完整核心管線；以 JSON 回傳偵測結果（不含圖片）。 |
| POST | `/api/v1/process` | 與 `/analyze` 相同——明確作為統一管線呼叫的別名。 |
| POST | `/api/v1/redact` | 完整核心管線；回傳遮罩後的圖片（`image/png`）。 |
| POST | `/api/v1/verify` | 獨立的整張圖片健全性檢查（`WholeImageSanityScanner`）——不需要先前的偵測結果。 |
| POST | `/api/v1/review` | Phase 8.3：針對先前 `/analyze` 產生的 `review_token`，提交人工確認決定；回傳確認後遮罩的圖片（`image/png`）並附上 `X-Review-*` 結果標頭。 |

```bash
curl http://127.0.0.1:8000/api/v1/health

curl -X POST http://127.0.0.1:8000/api/v1/analyze -F "file=@example.png"

curl -X POST http://127.0.0.1:8000/api/v1/redact -F "file=@example.png" --output redacted.png

curl -X POST http://127.0.0.1:8000/api/v1/verify -F "file=@redacted.png"
```

（上面的 `example.png` 應為你自己的測試圖片——切勿隨意上傳真實的個人/
財務資料到本機開發伺服器。）

`/api/v1/analyze` 回應範例（僅供示意，非真實資料）：

```json
{
  "status": "PASSED",
  "needs_human_review": false,
  "blocked": false,
  "detections": [
    {"type": "TaiwanID", "risk_level": "CRITICAL", "action": "FULL_MASK",
     "confidence": 0.85, "needs_review": false,
     "bbox": {"x": 144, "y": 160, "width": 175, "height": 25}}
  ],
  "verification": {"status": "PASSED", "attempts": 1, "residual_count": 0, "needs_human_review": false},
  "summary": {"total_detections": 1, "critical_count": 1, "needs_review_count": 0, "blocked": false}
}
```

`status` 結合了核心的驗證狀態與 `needs_human_review`/`blocked`，統一為
一個欄位：`PASSED` / `FAILED` / `SKIPPED` / `NEEDS_REVIEW` /
`BLOCKED`。**這是 MaskGuard 自身的安全處理狀態，不是 HTTP
錯誤**——即使結果是 `NEEDS_REVIEW` 甚至 `BLOCKED`，HTTP 狀態碼仍然是
`200`；HTTP 狀態碼（`400`/`413`/`415`/`422`/`500`/`504`）只描述「這次
API 呼叫本身」是否成功。

### API 絕不回傳或記錄的內容

偵測結果只包含 `type` / `risk_level` / `action` / `confidence` /
`needs_review` / `bbox`——絕不包含比對到的原始文字（不含密碼、API
金鑰、信用卡號、身分證字號、銀行帳號或任何其他敏感值）。應用程式日誌同
樣受到限制，只記錄 request id、耗時、檔案大小與偵測數量——即使在 DEBUG
層級也絕不記錄 OCR 文字、檔名或偵測值。相關測試見
`tests/api/test_security_logging.py`，涵蓋
Email/TaiwanID/CreditCard/BankAccount/APIKey/Password 等測試素材。

### 檔案限制與設定

所有 HTTP 層的限制都集中在 `maskguard/api/config.py`（`ApiSettings`）
中，透過環境變數設定——絕不寫死在路由裡：

| 變數 | 預設值 | 說明 |
|---|---|---|
| `MASKGUARD_MAX_UPLOAD_SIZE_BYTES` | `10485760`（10 MB） | 超過此值以 `413` 拒絕。 |
| `MASKGUARD_MAX_IMAGE_WIDTH` | `8000` | 超過此值以 `422` 拒絕。 |
| `MASKGUARD_MAX_IMAGE_HEIGHT` | `8000` | 超過此值以 `422` 拒絕。 |
| `MASKGUARD_MAX_IMAGE_PIXELS` | `40000000` | 超過此值以 `422` 拒絕（防解壓縮炸彈）。 |
| `MASKGUARD_PROCESSING_TIMEOUT_SECONDS` | `60` | 請求層級的軟性逾時；超過則回傳 `504`（見下方「已知限制」）。 |
| `MASKGUARD_CORS_ALLOWED_ORIGINS` | *（空）* | 以逗號分隔的允許來源清單。空值代表不允許跨來源存取——預設絕不是 `*`。 |
| `MASKGUARD_REVIEW_TOKEN_TTL_SECONDS` | `600` | Phase 8.3：`/analyze` 產生的人工確認權杖有效時間。 |
| `MASKGUARD_MAX_REVIEW_REASON_LENGTH` | `200` | Phase 8.3：REJECTED 項目 `reason` 文字的最大長度。 |
| `MASKGUARD_MIN_REVIEW_BBOX_WIDTH` / `_HEIGHT` | `4` | Phase 8.3：人工新增偵測框的最小尺寸。 |
| `MASKGUARD_MAX_REVIEW_BBOX_AREA_RATIO` | `0.9` | Phase 8.3：人工框最多可佔圖片面積的比例上限。 |

上傳的檔案會實際以 Pillow 解碼驗證（絕不信任客戶端的 `Content-Type`
標頭），並以固定的伺服器端檔名寫入安全建立的暫存目錄——**絕不**使用
客戶端提供的檔名——且在每一種結束路徑（成功或例外）都會清除。

### 無持久化儲存

Phase 8.1 是無狀態的處理型 API：沒有資料庫、沒有使用者帳號、不儲存圖
片，也沒有下載/工作歷史紀錄。每個請求的暫存檔案都會在回應送出前清除完
畢。

### 已知限制

- 每個請求都是單一同步呼叫，交由工作執行緒處理——沒有工作佇列，因此處
  理時間超過 `MASKGUARD_PROCESSING_TIMEOUT_SECONDS` 的請求會對客戶端回
  傳 `504`，但底層的工作執行緒不會被強制中止（Tesseract/OpenCV 呼叫無
  法安全地中途中斷）；它會在背景繼續執行完畢，其暫存目錄仍會被清除。
- 沒有認證/授權機制——在對外開放之前，請將其置於受信任的網路邊界之
  後，或透過反向代理額外加上一層。

## 網頁前端（Phase 8.2）

一個 React + TypeScript + Vite 瀏覽器介面（`frontend/`）——是上述 HTTP
API 的一個薄用戶端。它只顯示後端的偵測/遮罩結果；前端完全不存在任何
OCR/偵測/風險/政策/遮罩/驗證邏輯。使用者只需要瀏覽器即可；Node.js 僅
為開發期相依（正式版建置產物是純靜態 HTML/CSS/JS）。

### 本機執行

```bash
# 終端機 1 —— 後端（見上方「HTTP API」）
python -m uvicorn maskguard.api.app:app --host 127.0.0.1 --port 8000

# 終端機 2 —— 前端開發伺服器
cd frontend
npm install
npm run dev   # 預設在 http://127.0.0.1:5173 開啟，代理至 VITE_API_BASE_URL
```

`frontend/.env.development` 設定了
`VITE_API_BASE_URL=http://127.0.0.1:8000`。可修改此值（或在建置時設定
對應環境變數）指向不同的後端——絕不要把正式環境伺服器位址寫死在原始碼
中。

### 正式版建置

```bash
cd frontend
npm run build     # tsc -b && vite build -> frontend/dist/（靜態資源）
```

在正式環境中提供 `frontend/dist/`（nginx、CDN 等）在 Phase 8.2 中不在
範圍內——請參考 Phase 9（Docker 部署）。

### 前端功能範圍

- 上傳圖片、呼叫 `POST /api/v1/analyze`，並以 SVG 疊加層在原始圖片上繪
  製回傳的偵測框——後端的 `(x, y, width, height)` 值才是權威來源；前端
  只是依照 `<img>` 實際顯示的大小重新縮放，絕不重新計算。
- 每筆偵測只顯示 `type` / `risk_level` / `action` / `confidence` /
  `needs_review`——**絕不**顯示比對到的原始值（身分證字號、卡號、密碼
  或 API 金鑰絕不會出現在 DOM 或瀏覽器主控台中）。
- 「執行遮罩」按鈕會呼叫 `POST /api/v1/redact`（再次使用真正的核心管
  線，不是前端自行遮罩），並將回傳的圖片與原圖並排顯示——原圖絕不會被
  覆寫。
- `BLOCKED`（嚴格模式）的遮罩回應會顯示為阻擋提示，絕不會被當成成功的
  圖片顯示。
- 不使用 `localStorage`/`sessionStorage`/IndexedDB 持久化圖片資料；
  物件 URL（`URL.createObjectURL`）在被取代或元件卸載時會被釋放。
- 人工確認（接受/拒絕偵測結果、新增人工偵測框）屬於 Phase
  8.3——見下方章節。**不**包含部署（Docker/nginx/HTTPS/認證）——屬於後
  續 Phase。

### 前端測試

```bash
cd frontend
npm test                                   # Vitest —— 元件/單元測試，不需要後端
VITE_TEST_REAL_BACKEND=1 npm test          # 同時執行真實後端整合測試 —— 需先啟動後端
```

## 人工確認（Phase 8.3）

人工確認是疊加在自動化管線之上的**額外**安全控制——它永遠無法繞過
RiskEngine/PolicyEngine/RedactionEngine/VerificationEngine。瀏覽器只會
送出*確認意圖*（以 `detection_id` 接受/拒絕既有偵測結果，或提交新偵測
結果的*類型*與*區域座標*）；實際的安全決策——風險等級、遮罩動作、敏感
值是否真的已消除——仍然完全由伺服器端的核心決定，與過去完全相同：

```
自動偵測（核心）
        |
        v
人工確認（瀏覽器：接受 / 拒絕 / 新增人工偵測框）
        |
        v
後端驗證（簽章確認權杖、區域/類型檢查）
        |
        v
政策判斷（既有 PolicyEngine —— 僅針對新增的人工偵測重新執行）
        |
        v
遮罩處理（既有 RedactionEngine）
        |
        v
驗證（既有 VerificationEngine + 整張圖片健全性掃描）
        |
        v
最終結果
```

### 為何不能信任瀏覽器提供風險/動作/類型

`POST /api/v1/analyze` 的回應現在還包含一個 `review_token`——這是一個
以 HMAC 簽章、短期有效的不透明資料，精確記錄了核心針對*這張圖片*找到
的內容（`detection_id`、類型、風險等級、動作、信心度、區域座標）。
`POST /api/v1/review` 會在伺服器端解碼並驗證此權杖，並依據**權杖內容**
（而非請求主體宣稱的任何內容）解析每一項接受/拒絕決定。具體來說：
`ReviewItemRequest`（請求綱要）根本沒有 risk_level/action/confidence
欄位，因此即使客戶端試圖夾帶也無從夾帶；人工新增偵測的 `type`
必須在伺服器端允許清單中，其 `bbox` 也會針對真實圖片尺寸完整重新驗證
（邊界、最小/最大尺寸）。詳見 `maskguard/api/review_token.py` 與
`maskguard/api/review_service.py`。

### 接受 / 拒絕

- **接受**：不影響遮罩結果（該偵測本來就會被遮罩）——僅清除「待確認」
  標記，代表已有人工確認過。
- **拒絕**：對於非關鍵類型（Email、電話、姓名、地址等），該偵測會從
  遮罩結果中移除——這是合理的誤判修正。但對於本質上屬於關鍵的類型
  （身分證字號、護照號碼、銀行帳號、信用卡號、密碼/金鑰、Bearer
  Token、JWT），拒絕**絕不會移除遮罩**——該區域仍會被遮罩，且結果會標
  記為 `needs_human_review`（顯示為 `NEEDS_REVIEW` 狀態），以便主管再
  次確認。「使用者拒絕了它」絕不會被視為「因此它是安全的」。

### 人工新增偵測

審核人員從伺服器定義的下拉選單中選擇類型，並在**原始**圖片上拖曳繪製
矩形；前端會在送出前將畫面上的矩形轉換為圖片本身的像素座標（純粹是視
覺轉換——後端會針對真實圖片獨立重新驗證結果）。後端接著會對其執行真正
的 `RiskEngine`/`PolicyEngine`（信心度 = 1.0，因為是人工目視確認了區
域與類型）——與自動化管線使用完全相同的引擎，絕不採用客戶端提供的風
險/動作。

### 過期與重放

確認權杖會在 `MASKGUARD_REVIEW_TOKEN_TTL_SECONDS`（預設 600 秒）後過
期，且只能被送出一次——同一個權杖第二次送出會被拒絕並回傳
`REVIEW_CONFLICT`（409），已過期的權杖則回傳 `REVIEW_EXPIRED`
（409）。簽章金鑰與一次性使用防護皆僅存在於伺服器行程記憶體中（沒有資
料庫——Phase 8.3 維持無狀態設計）；伺服器重新啟動會使進行中的人工確認
失效，此時只需重新分析圖片即可。

### 無持久化儲存

與 Phase 8.1 相同：沒有資料庫、不儲存確認歷史、沒有稽核紀錄表。
`POST /api/v1/review` 會在單一請求中重新送出原始圖片與確認決定——沒有
之後可再次取回的內容。

## API 安全強化（Phase 8.4）

Phase 8.4 針對既有的 HTTP/API 層進行攻擊測試，並修補了發現的濫用情
境。核心模組（OCR/偵測/風險/政策/遮罩/驗證）完全未變動——以下所有控制
措施都位於 `maskguard/api/` 之中。

**本版本並非設計為在未加上認證與正式環境部署控制措施（反向代理、
TLS、邊界速率限制、認證——皆屬後續 Phase）的情況下直接對外公開**。
本階段強化的是抵禦*濫用/惡意輸入*的能力，而非「完全沒有存取控制」的
情況。

### 限制值（全部位於 `ApiSettings`，可透過環境變數覆寫）

| 變數 | 預設值 | 用途 |
|---|---|---|
| `MASKGUARD_MAX_REQUEST_BODY_BYTES` | `12582912`（12 MB） | 整個請求主體在 ASGI 層級的外層上限——在主體**串流輸入時**就會強制執行，而非等完全緩衝完畢後才檢查（見下方）。 |
| `MASKGUARD_MAX_UPLOAD_SIZE_BYTES` | `10485760`（10 MB） | 精確的、權威的單檔案限制（與 Phase 8.1 相同未變）。 |
| `MASKGUARD_MAX_REVIEW_ITEMS` | `200` | 單次 `/review` 提交中，接受/拒絕/人工新增項目的總數上限。 |
| `MASKGUARD_MAX_MANUAL_DETECTIONS` | `50` | 其中，全新「人工新增」偵測的數量上限（這是會觸發真正 RiskEngine/PolicyEngine 運算的子集合）。 |
| `MASKGUARD_MAX_REVIEW_PAYLOAD_BYTES` | `262144`（256 KB） | `review` JSON 表單欄位的原始位元組大小，在解析**之前**就會檢查。 |
| `MASKGUARD_MAX_REVIEW_TOKEN_BYTES` | `65536`（64 KB） | 傳入的 `review_token` 超過此長度會在進行任何 base64/HMAC 運算前直接拒絕。 |
| `MASKGUARD_MAX_CONCURRENT_JOBS` | `4` | 核心（OCR/偵測/.../驗證）同時處理的工作數量上限——見下方。 |

（圖片尺寸/像素限制、確認區域/原因文字限制，以及確認權杖 TTL 與
Phase 8.1/8.3 相同未變——見前述章節。）

### 上傳大小：串流強制執行，而非事後檢查

FastAPI 在路由函式執行**之前**，就會先完整解析 `UploadFile`
參數的 multipart 主體——這代表「讀取後再檢查 `len(data)`」這種簡單做
法（Phase 8.1 原始設計）只能在伺服器已經完整接收並緩衝整個檔案**之
後**才拒絕過大的上傳。`maskguard/api/middleware.py` 的
`MaxRequestBodySizeMiddleware` 在最原始的 ASGI 層級、比其他所有處理都
更早地解決了這個問題：

1. `Content-Length` 快速路徑：若宣告的大小明顯超過上限，會在讀取任何
   一個位元組之前，立即以乾淨的 `413` 拒絕。
2. 串流位元組計數後備機制：無論 `Content-Length`
   是否有送出或是否被偽造，都會限制實際消耗的位元組數（攻擊者省略或
   偽造該標頭也無法繞過）。已直接驗證：200MB 的串流主體在 12MB 上限
   下，會在剛好 12MB 處被截斷，耗時不到 20ms。

已知且經測試的串流後備機制限制：以這種方式中途中斷 Starlette 的
multipart 解析器，會被其自身的內部錯誤處理攔截，並以一般性的 `400`
（透過既有的 `StarletteHTTPException` 處理器）呈現，而非精確編碼的
`413`。真正重要的安全性質——有界的資源消耗、不當機、不外洩——在兩種情
況下都成立；只有確切的狀態碼與 `Content-Length` 快速路徑的情況不同。

### 併發：有上限，而非無限制

最多同時執行 `MASKGUARD_MAX_CONCURRENT_JOBS` 個核心處理呼叫
（analyze/redact/verify/review），使用的是整個行程已共用的**同一個**
`Pipeline`/OCR 引擎執行個體（Phase 8.1 §20——絕不會建立第二個引擎）。
當所有工作槽都忙碌時，新請求會立即被拒絕並回傳
`429`——絕不會被排入佇列等待。已直接驗證：在上限為 4 的情況下送出 10
個併發 `/analyze` 請求，恰好產生 4 個成功回應與 6 個立即（約 20ms）的
`429`，總耗時與單一處理批次相當，而非 10 倍。

**逾時與併發的交互作用——在假設逾時會「取消」任何事情之前請先閱讀本
段。** Python 無法強制終止正在執行的工作執行緒。當請求處理時間超過
`MASKGUARD_PROCESSING_TIMEOUT_SECONDS` 時，HTTP 呼叫會回傳
`504 PROCESSING_TIMEOUT`——但底層的 OCR/核心工作仍會在背景繼續執行至
完成（這在 Phase 8.1 中已經如此並已記載）。Phase 8.4
新增的是：該「幽靈工作者」佔用的併發工作槽，**不會**只因為 HTTP
回應已放棄等待就被釋放——它會保持佔用，直到該工作者真正完成為止。這正
是實際限制最差情況下併發 CPU 使用量的關鍵：在持續逾時請求的洪水攻擊
下，最多只會有 `MAX_CONCURRENT_JOBS` 個幽靈工作者同時存在，絕不會更
多，即使每個個別呼叫都已經回應過。已直接在
`tests/api/test_security_hardening.py` 中驗證。

### 暫存檔案

設計與 Phase 8.1 相同未變：每個請求使用一個
`tempfile.TemporaryDirectory()`，使用固定的伺服器端產生檔名（絕不使用
客戶端檔名），並在每一種結束路徑（成功、驗證失敗、例外、逾時——因為清
除邏輯是 context manager 的 `__exit__`，無論 `with`
區塊是如何結束的都會觸發）都會清除。已在重複失敗情況下驗證：不會累積
任何目錄。

平台注意事項（§26）：`tempfile` 在 POSIX 系統上預設會以 `0o700`
（僅擁有者）模式建立目錄；在 Windows 上，暫存目錄會繼承使用者自身
`%TEMP%` 設定檔目錄的 ACL。MaskGuard 本身不會在標準函式庫已提供的基礎
上額外強化權限——這裡只是記載此事實而非重新實作，因為本階段是單一使
用者、單一行程的本機服務（尚無多租戶隔離需求）。

### HTTP 安全標頭

僅套用於 `/api/v1/*` 回應——絕不套用於
`/docs`/`/openapi.json`/`/redoc`，否則會破壞 Swagger UI 自身的資源載
入：

- `X-Content-Type-Options: nosniff`
- `Cache-Control: no-store`——每個 `/api/v1`
  回應都可能帶有業務敏感內容（偵測結果、遮罩後的圖片本身），因此絕不
  允許被瀏覽器、代理伺服器或 CDN 快取。
- `X-Frame-Options: DENY`——本 API 絕不應被框架/嵌入。

刻意**沒有**加上嚴格的 `Content-Security-Policy`——這是一個 API，而非
會渲染不受信任 HTML 的頁面，加上 CSP 只會有破壞開發模式 `/docs`
介面的風險而沒有實際效益。

### CORS（預設值未變，已在攻擊測試下重新確認）

依然預設為空（Phase 8.1 §19）——絕不是 `*`。已直接驗證：
`Origin: https://evil.example` 請求（包含 CORS 預檢請求）完全不會收到
`Access-Control-Allow-Origin` 標頭，因此無論回應內容為何，瀏覽器都無
法跨來源讀取該回應。

### 錯誤外洩

契約未變（Phase 8.1 §17）：每個錯誤都是 `{"error": {"code",
"message", "request_id"}}` 的格式，絕不包含追蹤堆疊、檔案系統路徑、模
組名稱或環境變數。已直接驗證：故意製造一個內含偽造密鑰/路徑字串的內
部例外，該字串完全不會出現在回傳給客戶端的回應中。

### 日誌注入

`X-Request-ID` 早已透過正規表示式驗證
（`^[A-Za-z0-9._-]{1,128}$`，Phase 8.1 §16）——此字元集本身就不可能包
含 `\r`/`\n`/控制字元，因此偽造日誌行在結構上本來就不可能發生；Phase
8.4 加上了直接測試證明這點（包含繞過客戶端函式庫的標頭驗證，直接測試
伺服器端自身的檢查）。確認原因文字與檔名完全不會被記錄（Phase
8.1/8.3——日誌僅記錄白名單欄位：路由、request id、耗時、檔案大小、偵測
數量、狀態）。

### 確認提交/權杖濫用

`/review` 提交在攻擊者可能利用的每個維度上都有上限：原始 `review`
欄位位元組大小（在 JSON 解析**之前**檢查）、項目總數、人工新增偵測數
量（會觸發真正風險/政策運算的子集合），以及傳入的 `review_token`
位元組大小（在任何 base64/HMAC 運算之前檢查）。這些都不會改變 Phase
8.3 已經保證的事：瀏覽器仍然無法設定偵測結果的
風險/動作/信心度/類型——見上方「人工確認」章節。

## Docker / 正式環境部署（Phase 9）

### 架構

```
瀏覽器 --HTTPS--> [frontend 容器: Nginx]
                       - 提供建置好的 React 應用程式（靜態檔案）
                       - 反向代理 /api/ --> [api 容器: FastAPI/Uvicorn]
                                                       - 核心管線、Tesseract
```

兩個容器，一個專用 Docker 網路（`maskguard_net`），不使用
`network_mode: host`。API 容器的 8000 埠**絕不**對外公開至主機或網
際網路——frontend/proxy 容器是唯一的對外進入點，且在正式環境中僅透過
HTTPS。

### 前置需求

- **Windows 11**：Docker Desktop（建議使用 WSL2 後端）、`docker
  compose` v2（Docker Desktop 已內建）。PowerShell 或 Git Bash
  皆可執行以下指令。
- **Linux**：Docker Engine 24+、`docker compose` v2 外掛程式。本設定完
  全不需要特權容器、`docker.sock` 掛載，或 `network_mode: host`。

### 開發環境部署（純 HTTP，僅限本機）

```bash
docker compose up --build -d
docker compose ps                 # 等待兩個服務皆為 "healthy"
curl http://localhost:8080/api/v1/health
```
PowerShell：指令完全相同——`docker compose` 在兩種 shell 中行為一致。

此設定使用 `docker-compose.yml`：`MASKGUARD_ENV=development`（暫時性、
自動產生的確認權杖密鑰——適合本機測試，**絕不**應在重新啟動間重複使
用）、純 HTTP、監聽 `localhost:8080`、無 TLS。

### 正式環境部署（HTTPS、外部化密鑰）

1. 為部署的主機名稱產生一組真實的確認權杖密鑰（32 個以上隨機字元）與
   真實的 TLS 憑證/私鑰：
   ```bash
   mkdir -p secrets certs
   openssl rand -base64 48 > secrets/review_token_secret.txt
   # certs/cert.pem + certs/key.pem：由你的 CA / 企業 PKI 提供——
   # 本專案絕不會提供或產生任何「正式環境」憑證。
   ```
   `secrets/` 與 `certs/` 皆絕不會被提交至版本控制（見 `.gitignore`）。
2. ```bash
   docker compose -f docker-compose.prod.yml up -d --build
   ```
3. 若密鑰檔案缺失、為空、是明顯的預留值（如 `changeme`），或短於 32
   字元，API 容器會在啟動時**拒絕啟動**
   （`InsecureProductionConfigError`）——絕不會默默退回到不安全的預設
   值。若服務堆疊未能正常啟動，請檢查
   `docker compose -f docker-compose.prod.yml logs api`。
4. ```bash
   curl -k https://localhost/api/v1/health   # -k 僅在使用自簽測試憑證時需要
   ```

### 設定

所有 API 層的限制（上傳大小、圖片尺寸、併發數、逾時、確認權杖 TTL、
CORS、環境/密鑰設定）都集中在 `maskguard/api/config.py`
中，並可透過 `.env.example` 所列的 `MASKGUARD_*`
環境變數覆寫。Nginx 層的設定（上游主機、請求大小上限、代理逾時、TLS
路徑）則透過 `docker-compose*.yml` 的 `environment:`
區塊設定，並在容器啟動時渲染成實際的 Nginx 設定檔
（`frontend/nginx/entrypoint.sh`）——絕不寫死在映像檔中。

### 密鑰

- **確認權杖密鑰**（`MASKGUARD_REVIEW_TOKEN_SECRET` /
  `MASKGUARD_REVIEW_TOKEN_SECRET_FILE`）：用來簽署 Phase 8.3
  的人工確認權杖。在正式環境中，來源為 Docker secret 檔案
  （`./secrets/review_token_secret.txt`，掛載於
  `/run/secrets/review_token_secret`）——絕不使用一般環境變數、絕不提
  交至版本控制、絕不傳送至前端。**更換此密鑰會使所有尚未使用的確認權
  杖失效**（這是設計上如此——可接受且已記載）。**此密鑰與確認權杖狀
  態皆為單一行程本機狀態**：此容器拓撲架構僅支援**單一** API
  執行個體（見下方「後端啟動方式」）；若要在負載平衡器後方執行多個副
  本，需要共用的密鑰與共用的權杖/限制器儲存（見下方「企業安全性」章
  節，Phase 10.6 已提供）。
- **TLS 憑證/私鑰**：由操作者提供，以唯讀方式從 `./certs/`
  掛載。絕不提交至版本控制。更換憑證只需取代檔案並重新啟動
  `frontend` 容器（`docker compose -f docker-compose.prod.yml restart
  frontend`）——不需要重新建置映像檔。

### TLS

`docker-compose.prod.yml` 的 `frontend` 服務以
`nginx.prod.conf.template` 監聽 443 埠（80 埠的 HTTP
只會重新導向至 HTTPS——絕不會以明文提供應用程式內容或代理
`/api/`）。`TLS_CERT_PATH`/`TLS_KEY_PATH`
指向掛載的檔案；本專案不提供任何自身的憑證。

### 資源限制

以實際量測為依據（詳細方法見 `docs/deployment.md`「資源限制」，非隨意
選定：API 容器閒置時約使用 ~51 MiB，在 4 個併發請求各處理一張 3600
萬像素圖片時（`MASKGUARD_MAX_CONCURRENT_JOBS=4`
在接近 4000 萬像素上限時的最差情況）峰值約 ~2.82 GiB RSS。兩個 compose
檔案皆設定了 `deploy.resources.limits`（api：2 CPU / 4 GiB / 200
PIDs；frontend：1 CPU / 256 MiB / 50
PIDs），皆遠高於上述量測峰值。在刻意設定極低限制下驗證的 OOM
終止行為顯示：**完全沒有回應**（連線被重置，沒有部分/不安全的輸
出）——詳見 `docs/deployment.md`。

### 健康檢查 / 啟動順序

兩個容器皆內建 `HEALTHCHECK`；`frontend`
只會在 `api` 回報健康後才啟動（`depends_on: condition:
service_healthy`——絕不使用任意的 `sleep`）。`GET /api/v1/health`
絕不會執行 OCR。

### 日誌

容器日誌絕不包含 OCR 文字、偵測值、圖片位元組資料，或確認權杖密鑰
（Phase 8.4 的日誌白名單機制未變）。請在 daemon 層級設定 Docker
的日誌輪替（`/etc/docker/daemon.json`：`{"log-driver": "json-file",
"log-opts": {"max-size": "10m", "max-file": "3"}}`），因為本專案的
compose 檔案刻意不寫死日誌驅動程式（讓其能在不同日誌設定的主機間保持
可攜性）。Nginx access log 只記錄方法/路徑/狀態碼/耗時——絕不記錄查詢
字串或請求主體。

### 升級 / 回滾

```bash
docker compose -f docker-compose.prod.yml pull            # 若使用登錄伺服器
docker compose -f docker-compose.prod.yml up -d --build    # 或本機重新建置
docker compose -f docker-compose.prod.yml ps               # 確認健康狀態
curl -k https://localhost/api/v1/health                    # 煙霧測試
```
請為映像檔標記版本號（`maskguard-api:9.x.x`），絕不依賴
`latest`，這樣回滾只需將 compose 檔案參照的標籤改回前一個版本後執行
`docker compose ... up -d` 即可。在新版本確認健康且通過煙霧測試前，請
勿刪除舊版映像檔。

### 備份

此部署方式不持久化任何內容（見下方 §9/§14）——沒有圖片儲存需要備份。
應備份的項目：`docker-compose*.yml`、`.env.example`/你實際使用的
`.env`、`certs/`、`secrets/`（依你組織的密鑰管理政策——絕不納入
Git），以及 `docs/` 中的操作手冊。

### 疑難排解

完整清單見 `docs/deployment.md`「疑難排解」；最常見的情況：正式環境啟
動時容器不健康，幾乎都是因為確認權杖密鑰缺失或強度不足
（`docker compose -f docker-compose.prod.yml logs api`）。

### Phase 9 基礎部署的安全限制（歷史紀錄）

以下項目描述的是 Phase 10「企業安全性」工作**之前**的部署狀態。這些限
制已被**取代**——見下方「企業安全性」章節了解各項目實際上是如何被解決
的——但為了保留 Phase 9 本身交付內容的歷史準確性，仍保留於此：

- ~~僅支援單一執行個體~~ → 現在已支援多執行個體部署，並以 Redis 共享
  狀態（Phase 10.6）。
- **無持久化圖片儲存**——此項目依然成立且未變：原始圖片、遮罩後圖片、
  OCR 文字與偵測值，在任何部署設定檔中，都絕不會被寫入請求自身暫存生
  命週期（`/tmp`，每次請求後清除）以外的磁碟位置。
- ~~無認證/授權層~~ → 現已提供 OIDC 認證 + 以權限為基礎的 RBAC（Phase
  10.2/10.3），透過 `OIDC_ENABLED`/`AUTHZ_ROLE_MAPPING_FILE` 選擇性啟
  用。
- ~~無內建速率限制~~ → 現已提供伺服器端速率限制（Phase
  10.5），並在多執行個體部署中透過 Redis 於各執行個體間共享（Phase
  10.6）。

### 後端啟動方式——為何每個容器僅使用單一 Uvicorn worker

`Dockerfile` 的 `CMD` 刻意執行 `uvicorn ... --workers 1`——核心處理狀
態（`ConcurrencyLimiter`）是單一行程層級的。請透過執行更多**容器**來
擴充規模（見下方「企業安全性」→「多執行個體部署」），而非替單一容器加
上 `--workers N`。一旦 `REDIS_ENABLED=true`，工作階段/確認重放/速率限
制狀態會在多個容器間正確共享；`ConcurrencyLimiter`
本身則依設計維持每個容器獨立（已記載，並非缺陷——跨 N
個容器的核心總併發量為 `MASKGUARD_MAX_CONCURRENT_JOBS × N`）。

## 企業安全性（Phase 10）

以下所有功能皆為**選用啟用**——未設定這些環境變數的部署，行為與上述
Phase 9 基礎部署完全相同。啟用這些功能是需要企業身分驗證、可歸責性與
多執行個體擴充能力的組織的刻意選擇；無論是否啟用，MaskGuard
核心（OCR → 偵測 → 風險 → 政策 → 遮罩 → 驗證）皆完全不受影響。

### 認證（OIDC）

`OIDC_ENABLED=true` 會啟用標準化的 OIDC 登入（Authorization Code +
PKCE——絕不使用 implicit flow，絕不直接從瀏覽器接受權杖）。伺服器會自
行驗證 ID Token 的簽章/發行者/受眾/過期時間；瀏覽器只會持有一個不透明
的、`HttpOnly`/`Secure`/`SameSite=Lax` 工作階段 cookie——存取/ID/更新
權杖絕不會暴露給 JavaScript 或儲存於
`localStorage`。透過 `OIDC_ISSUER`/`OIDC_CLIENT_ID`/
`OIDC_CLIENT_SECRET_FILE`/`OIDC_REDIRECT_URI` 設定（見
`.env.example`）。

### 授權（RBAC）

啟用認證後，`AUTHZ_ROLE_MAPPING_FILE` 會將「發行者 + 主體」對應到角色
（Operator、Reviewer、SecurityAdministrator、Auditor、
Administrator），每個角色都帶有固定的最小權限集合——在伺服器端於每個
請求時檢查，絕不從客戶端提供的標頭推斷。沒有對應項目的身分會取得零權
限（預設拒絕）。沒有任何角色（包含 Administrator）能繞過 PolicyEngine
或強制解除遮罩——程式碼庫中完全不存在任何管理員繞過路徑。

### 稽核

`AUDIT_ENABLED=true` 會將持久化、僅可附加的安全相關事件紀錄（登入、
授權決策、analyze/redact/verify/review 動作）寫入本機 SQLite
資料庫，並以有金鑰的 HMAC-SHA256 串鏈方式保護，因此任何竄改（修改、刪
除或重新排序紀錄）都能透過 `GET /api/v1/audit/integrity`
偵測到。稽核紀錄絕不包含 OCR 文字、偵測值、權杖或密鑰——只包含「誰在何
時做了什麼」的中介資料。讀取稽核紀錄需要 `audit.read`
權限（Auditor 角色）。

### 速率限制

`RATE_LIMIT_ENABLED=true` 會依端點類別（認證、
analyze/redact/verify、確認、稽核查詢）限制請求速率，以受信任的已認證
身分或網路客戶端位址為鍵值——絕不使用可偽造的標頭。此功能獨立於既有的
`MASKGUARD_MAX_CONCURRENT_JOBS` 併發限制之外並額外疊加（速率限制回答
的是「一段時間內有多少請求」，併發限制回答的是「同時有多少在執行」——
是兩種不同的控制）。

### 多執行個體部署

`REDIS_ENABLED=true` 會透過 Redis 在多個 API
容器間共享工作階段、確認重放與速率限制狀態，讓負載平衡器可以在各節點
間輪詢分配流量，不需要黏性工作階段，也不會有節點間的安全決策不一致（無
論請求被哪個節點處理，看到的都是相同的已認證身分、相同的確認權杖重放
防護，以及相同的速率限制計數）。Redis 是*狀態儲存*，絕非*決策權
威*——它絕不會做出任何認證、授權或政策決策，只儲存那些決策已經產生的
結果。Redis 發生故障時，所有依賴它的操作都會安全地*失敗關閉*（明確錯
誤），絕不會變成開放通行。可執行的雙節點 + Redis + Nginx
拓撲範例見 `docker-compose.multi.yml`。

### 正式環境部署設定檔

三種設定檔，透過 `MASKGUARD_DEPLOYMENT_PROFILE` 選擇：

| 設定檔 | Compose 檔案 | 需求 |
|---|---|---|
| `development`（預設） | `docker-compose.yml` | 無——以上所有控制皆保持關閉 |
| `single-instance-enterprise` | `docker-compose.prod.yml` | 需同時啟用 OIDC + 授權 + 稽核 + 速率限制 |
| `multi-instance-enterprise` | `docker-compose.multi.yml` | 上述項目，再加上 Redis |

宣告企業設定檔後，若其所需的控制項未全部一致啟用，應用程式會**拒絕啟
動**——設定不完整的「企業」部署會是啟動時的直接失敗，絕不會默默退回較
弱的安全性設定。

### 存活 / 就緒檢查

`GET /api/v1/health`——存活檢查（行程是否存活；絕不檢查
Redis）。`GET /api/v1/ready`——就緒檢查（安全運作所需的相依服務是否可
用；`REDIS_ENABLED=true` 時會回報 Redis 可用性）。兩者皆絕不會回傳密
鑰、連線字串或內部例外細節。

## 測試

```bash
python -m pytest              # 僅單元測試 —— 不需要 Tesseract
python -m pytest -m e2e       # 真實 OCR 端對端測試 —— 需要 Tesseract（見上方）
python -m pytest -m benchmark # OCR 效能基準測試套件 —— 需要 Tesseract；見 benchmarks/README.md
python -m pytest -m api       # HTTP API 測試 —— 需要 `api` extra；大多數也需要 Tesseract
```

`-m api` 包含 Phase 10.x 企業功能測試套件（`tests/api/auth/`、
`tests/api/authorization/`、`tests/api/audit/`、
`tests/api/ratelimit/`、`tests/api/distributed/`）。認證/授權測試是針
對完全行程內模擬的 OIDC 提供者執行（使用真實 RSA 金鑰、真實 JWT
簽章——不需要外部 IdP）。多執行個體狀態與 Redis
相關的單元測試（`tests/api/distributed/`、`tests/test_redis_*.py`）需
要能連線至 `TEST_REDIS_URL` 的真實 Redis，或有本機 Docker daemon
可自動啟動一個暫時性的 Redis 容器（`tests/redis_env.py`）——若兩者皆不
可用，這些測試會**跳過**（絕不會失敗）。

單元測試直接針對合成的 OCR token 與假的 OCR
引擎測試偵測/風險/政策/遮罩邏輯，因此完全不會碰到 Tesseract
執行檔。`-m e2e` 會選取獨立的真實 OCR 套件（位於
`tests/e2e/`），對產生的測試圖片執行完整的「圖片 -> 前處理 -> 真實 OCR
-> 偵測 -> 風險 -> 政策 -> 遮罩 -> 驗證 -> 輸出」管線。純粹執行
`pytest`（不加 `-m`）會透過 `pyproject.toml` 的 `addopts`
自動排除 `e2e`，讓 CI/本機的單元測試維持快速且不需要安裝
Tesseract。

E2E 測試絕不會在缺少真實 OCR 環境的情況下悄悄通過：若 Tesseract 或
`chi_tra` 語言資料缺失，每個 E2E 測試都會回報 **SKIPPED**（而非
PASS），並具體指出缺少哪一項。

### 產生 E2E 測試素材

```bash
python scripts/generate_test_images.py
```

重新產生 `tests/fixtures/*.png` + `manifest.json`。所有測試素材文字皆
為合成資料（虛構的格式，以及每個支付處理商官方文件都會使用的標準
Luhn 合法*測試*信用卡號 `4111 1111 1111 1111`），且每張圖片都帶有明顯
的「TEST DATA（SYNTHETIC）」浮水印。若修改
`scripts/generate_test_images.py` 中的測試素材內容，請重新執行此指
令。
