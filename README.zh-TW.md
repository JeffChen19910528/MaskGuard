# MaskGuard

**[English](README.md) | [繁體中文](README.zh-TW.md)**

圖片敏感資料偵測與遮罩處理管線。透過本機 OCR + 規則式／本機 AI 分類,
偵測圖片中的個人資料、財務資料、憑證與商業機密文字,並就地進行遮罩／
模糊化／馬賽克處理。完整規格請見 `Skill.md`。

## 安裝設定

```bash
python -m pip install -e .
```

OCR 需要安裝 **Tesseract 執行檔** 並加入 `PATH`(這與 `pytesseract`
Python 套件是分開的——`pytesseract` 只是呼叫 Tesseract 執行檔的一層薄包
裝,兩者都需要)。

### Windows

```powershell
winget install --id UB-Mannheim.TesseractOCR -e
```

會安裝到 `C:\Program Files\Tesseract-OCR`,並(重新開啟終端機/工作階段
後)把 `tesseract.exe` 加入 `PATH`。winget/UB-Mannheim 套件附帶的
`tessdata` 只包含 `eng`(+`osd`)——`chi_tra`(繁體中文)需要另外手動加
入:

```powershell
# 下載 Tesseract 官方專案發布的語言包:
Invoke-WebRequest -Uri "https://github.com/tesseract-ocr/tessdata/raw/main/chi_tra.traineddata" -OutFile "$env:LOCALAPPDATA\tessdata\chi_tra.traineddata"
Copy-Item "C:\Program Files\Tesseract-OCR\tessdata\eng.traineddata" "$env:LOCALAPPDATA\tessdata\"
Copy-Item "C:\Program Files\Tesseract-OCR\tessdata\osd.traineddata" "$env:LOCALAPPDATA\tessdata\"
# 讓 Tesseract 指向一個不需要系統管理員權限即可寫入的語言資料目錄:
$env:TESSDATA_PREFIX = "$env:LOCALAPPDATA\tessdata"
```

以 `tesseract --list-langs` 驗證——應會列出 `chi_tra`、`eng`、`osd`。若
`tesseract` 完全不在 `PATH` 中,請開啟新的終端機(winget 只會更新登錄檔
中的 `PATH`,不會更新目前已開啟的終端機工作階段),或直接指定執行檔路
徑:`LocalOcrEngine(tesseract_cmd=r"C:\Program Files\Tesseract-OCR\tesseract.exe")`。

### Linux(Debian/Ubuntu)

```bash
sudo apt-get update
sudo apt-get install -y tesseract-ocr tesseract-ocr-chi-tra tesseract-ocr-eng
```

其他發行版:`dnf install tesseract tesseract-langpack-chi_tra`
(Fedora)或自行從 https://github.com/tesseract-ocr/tesseract 建置。以
`tesseract --list-langs` 驗證。

### macOS

```bash
brew install tesseract tesseract-lang   # tesseract-lang 包含所有語言包,含 chi_tra
```

以 `tesseract --list-langs` 驗證。

### 驗證環境

```bash
python tests/e2e/_environment.py
```

會印出 Python 版本、`pytesseract` 是否能匯入、實際解析到的 `tesseract`
執行檔路徑、`tesseract --version` 的輸出,以及 `eng`/`chi_tra` 是否實際
可用。

## CLI 使用方式

```bash
imgmask input.png --output ./output
imgmask input.png --output ./output --mode strict --verify
imgmask ./input_folder --output ./output --recursive
```

輸出目錄結構:

```
output/
├── processed/<name>_masked.png
├── report/<name>_masked.json      # processing_report.json —— 不含原始敏感文字
└── audit.log                      # 只附加不覆寫,只記錄類型/信心度/區域
```

`--mode strict` 會啟用嚴格模式:僅使用本機 OCR/AI、不上傳雲端、必須通過
驗證,且驗證失敗時會完全阻擋輸出(不會寫出任何圖片)。

## HTTP API

選用的 FastAPI 層(`maskguard/api/`)以 HTTP 方式提供與 CLI 相同的
MaskGuard 管線。

### 安裝並啟動伺服器

```bash
python -m pip install -e ".[api]"   # 在核心之上安裝 fastapi/uvicorn/pydantic/python-multipart
python -m uvicorn maskguard.api.app:app --host 127.0.0.1 --port 8000
# 或者:
python -m maskguard.api
```

預設只綁定 `127.0.0.1`(僅限本機)。**請勿**在未加上反向代理、認證與
TLS 的情況下使用 `--host 0.0.0.0`(或設定
`MASKGUARD_API_HOST=0.0.0.0`)——API 本身不包含任何認證機制。

### 端點

全部位於 `/api/v1/` 之下。伺服器啟動後可在
`http://127.0.0.1:8000/docs` 查看互動式文件。

| 方法 | 路徑 | 用途 |
|---|---|---|
| GET | `/api/v1/health` | 存活檢查。不會執行 OCR。 |
| POST | `/api/v1/analyze` | 完整管線;以 JSON 回傳偵測結果(不含圖片)。 |
| POST | `/api/v1/process` | 與 `/analyze` 相同——明確的別名。 |
| POST | `/api/v1/redact` | 完整管線;回傳遮罩後的圖片(`image/png`)。 |
| POST | `/api/v1/verify` | 獨立的整張圖片健全性檢查——不需要先前的偵測結果。 |
| POST | `/api/v1/review` | 針對先前 `/analyze` 產生的 `review_token`,提交人工確認決定;回傳確認後遮罩的圖片(`image/png`)。 |

```bash
curl http://127.0.0.1:8000/api/v1/health

curl -X POST http://127.0.0.1:8000/api/v1/analyze -F "file=@example.png"

curl -X POST http://127.0.0.1:8000/api/v1/redact -F "file=@example.png" --output redacted.png

curl -X POST http://127.0.0.1:8000/api/v1/verify -F "file=@redacted.png"
```

(上面的 `example.png` 應為你自己的測試圖片——切勿隨意上傳真實的個人/
財務資料到本機開發伺服器。)

`/api/v1/analyze` 回應範例(僅供示意,非真實資料):

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

`status` 結合了驗證狀態與 `needs_human_review`/`blocked`,統一為一個欄
位:`PASSED` / `FAILED` / `SKIPPED` / `NEEDS_REVIEW` / `BLOCKED`。這是
MaskGuard 自身的處理狀態,不是 HTTP 錯誤——即使結果是 `NEEDS_REVIEW`
甚至 `BLOCKED`,HTTP 狀態碼仍然是 `200`。

偵測結果只包含 `type` / `risk_level` / `action` / `confidence` /
`needs_review` / `bbox`——絕不包含比對到的原始文字。

### 設定

所有 HTTP 層的限制都集中在 `maskguard/api/config.py`(`ApiSettings`)
中,透過環境變數設定:

| 變數 | 預設值 | 說明 |
|---|---|---|
| `MASKGUARD_MAX_UPLOAD_SIZE_BYTES` | `10485760`(10 MB) | 超過此值以 `413` 拒絕。 |
| `MASKGUARD_MAX_IMAGE_WIDTH` | `8000` | 超過此值以 `422` 拒絕。 |
| `MASKGUARD_MAX_IMAGE_HEIGHT` | `8000` | 超過此值以 `422` 拒絕。 |
| `MASKGUARD_MAX_IMAGE_PIXELS` | `40000000` | 超過此值以 `422` 拒絕。 |
| `MASKGUARD_PROCESSING_TIMEOUT_SECONDS` | `60` | 請求層級的軟性逾時;超過則回傳 `504`。 |
| `MASKGUARD_CORS_ALLOWED_ORIGINS` | *(空)* | 以逗號分隔的允許來源清單。空值代表不允許跨來源存取。 |
| `MASKGUARD_REVIEW_TOKEN_TTL_SECONDS` | `600` | `/analyze` 產生的人工確認權杖有效時間。 |
| `MASKGUARD_MAX_REVIEW_REASON_LENGTH` | `200` | REJECTED 項目 `reason` 文字的最大長度。 |
| `MASKGUARD_MIN_REVIEW_BBOX_WIDTH` / `_HEIGHT` | `4` | 人工新增偵測框的最小尺寸。 |
| `MASKGUARD_MAX_REVIEW_BBOX_AREA_RATIO` | `0.9` | 人工框最多可佔圖片面積的比例上限。 |
| `MASKGUARD_MAX_REQUEST_BODY_BYTES` | `12582912`(12 MB) | 整個請求主體在 ASGI 層級的外層上限。 |
| `MASKGUARD_MAX_REVIEW_ITEMS` | `200` | 單次 `/review` 提交中,接受/拒絕/人工新增項目的總數上限。 |
| `MASKGUARD_MAX_MANUAL_DETECTIONS` | `50` | 其中,全新「人工新增」偵測的數量上限。 |
| `MASKGUARD_MAX_REVIEW_PAYLOAD_BYTES` | `262144`(256 KB) | `review` JSON 表單欄位的原始位元組大小上限。 |
| `MASKGUARD_MAX_REVIEW_TOKEN_BYTES` | `65536`(64 KB) | 傳入的 `review_token` 最大長度。 |
| `MASKGUARD_MAX_CONCURRENT_JOBS` | `4` | 同時處理的工作數量上限;超過時回傳 `429`。 |

上傳的檔案會實際以 Pillow 解碼驗證(絕不信任客戶端的 `Content-Type`
標頭),且不會保留客戶端提供的檔名或圖片資料。

## 網頁前端

一個 React + TypeScript + Vite 瀏覽器介面(`frontend/`)——是上述 HTTP
API 的一個薄用戶端。使用者只需要瀏覽器即可;Node.js 僅為開發期相依。

### 本機執行

```bash
# 終端機 1 —— 後端(見上方「HTTP API」)
python -m uvicorn maskguard.api.app:app --host 127.0.0.1 --port 8000

# 終端機 2 —— 前端開發伺服器
cd frontend
npm install
npm run dev   # 預設在 http://127.0.0.1:5173 開啟,代理至 VITE_API_BASE_URL
```

`frontend/.env.development` 設定了
`VITE_API_BASE_URL=http://127.0.0.1:8000`。可修改此值(或在建置時設定
對應環境變數)指向不同的後端。

### 正式版建置

```bash
cd frontend
npm run build     # tsc -b && vite build -> frontend/dist/(靜態資源)
```

### 功能說明

- 上傳圖片、呼叫 `POST /api/v1/analyze`,並在原始圖片上繪製回傳的偵測
  框。
- 每筆偵測只顯示 `type` / `risk_level` / `action` / `confidence` /
  `needs_review`——絕不顯示比對到的原始值。
- 「執行遮罩」按鈕會呼叫 `POST /api/v1/redact`,並將回傳的圖片與原圖並
  排顯示。
- 支援人工確認:接受/拒絕既有偵測結果,或在圖片上拖曳繪製矩形並選擇類
  型來新增人工偵測。

### 前端測試

```bash
cd frontend
npm test                                   # Vitest —— 元件/單元測試,不需要後端
VITE_TEST_REAL_BACKEND=1 npm test          # 同時執行真實後端整合測試 —— 需先啟動後端
```

## Docker / 正式環境部署

### 架構

```
瀏覽器 --HTTPS--> [frontend 容器: Nginx]
                       - 提供建置好的 React 應用程式(靜態檔案)
                       - 反向代理 /api/ --> [api 容器: FastAPI/Uvicorn]
                                                       - 核心管線、Tesseract
```

API 容器的 8000 埠絕不對外公開至主機——frontend/proxy 容器是唯一的對外
進入點。

### 前置需求

- **Windows 11**:Docker Desktop(建議使用 WSL2 後端)、`docker compose` v2。
- **Linux**:Docker Engine 24+、`docker compose` v2 外掛程式。

### 開發環境部署(純 HTTP,僅限本機)

```bash
docker compose up --build -d
docker compose ps                 # 等待兩個服務皆為 "healthy"
curl http://localhost:8080/api/v1/health
```

使用 `docker-compose.yml`:暫時性、自動產生的確認權杖密鑰(僅適合本機
測試)、純 HTTP、監聽 `localhost:8080`。

### 正式環境部署(HTTPS、外部化密鑰)

1. 為部署的主機名稱產生一組真實的確認權杖密鑰與真實的 TLS 憑證/私鑰:
   ```bash
   mkdir -p secrets certs
   openssl rand -base64 48 > secrets/review_token_secret.txt
   # certs/cert.pem + certs/key.pem:由你的 CA / 企業 PKI 提供
   ```
   `secrets/` 與 `certs/` 皆絕不會被提交至版本控制(見 `.gitignore`)。
2. ```bash
   docker compose -f docker-compose.prod.yml up -d --build
   ```
3. 若密鑰檔案缺失、為空或短於 32 字元,API 容器會拒絕啟動
   (`InsecureProductionConfigError`)。若服務堆疊未能正常啟動,請檢查
   `docker compose -f docker-compose.prod.yml logs api`。
4. ```bash
   curl -k https://localhost/api/v1/health   # -k 僅在使用自簽測試憑證時需要
   ```

### 設定

API 層的限制透過 `.env.example` 所列的 `MASKGUARD_*` 環境變數設定。
Nginx 層的設定(上游主機、請求大小上限、代理逾時、TLS 路徑)則透過
`docker-compose*.yml` 的 `environment:` 區塊設定。

### 密鑰

- **確認權杖密鑰**(`MASKGUARD_REVIEW_TOKEN_SECRET` /
  `MASKGUARD_REVIEW_TOKEN_SECRET_FILE`):正式環境中來源為 Docker
  secret 檔案(`./secrets/review_token_secret.txt`)。更換此密鑰會使所
  有尚未使用的確認權杖失效。
- **TLS 憑證/私鑰**:由操作者提供,以唯讀方式從 `./certs/` 掛載。更換
  憑證只需取代檔案並重新啟動 `frontend` 容器(`docker compose -f
  docker-compose.prod.yml restart frontend`)。

### 升級 / 回滾

```bash
docker compose -f docker-compose.prod.yml pull            # 若使用登錄伺服器
docker compose -f docker-compose.prod.yml up -d --build    # 或本機重新建置
docker compose -f docker-compose.prod.yml ps               # 確認健康狀態
curl -k https://localhost/api/v1/health                    # 煙霧測試
```

請為映像檔標記版本號(`maskguard-api:9.x.x`),而非依賴
`latest`,這樣回滾只需將標籤改回前一個版本後執行
`docker compose ... up -d` 即可。

### 疑難排解

完整清單見 `docs/deployment.md`「疑難排解」;最常見的情況:正式環境啟
動時容器不健康,幾乎都是因為確認權杖密鑰缺失或強度不足
(`docker compose -f docker-compose.prod.yml logs api`)。

## 企業安全性

以下功能皆為選用啟用——未設定這些環境變數的部署,行為與上述基礎部署完
全相同。

- **認證(OIDC)**:`OIDC_ENABLED=true`,透過
  `OIDC_ISSUER`/`OIDC_CLIENT_ID`/`OIDC_CLIENT_SECRET_FILE`/
  `OIDC_REDIRECT_URI` 設定(見 `.env.example`)。
- **授權(RBAC)**:`AUTHZ_ROLE_MAPPING_FILE` 將身分對應到角色
  (Operator、Reviewer、SecurityAdministrator、Auditor、
  Administrator)。
- **稽核**:`AUDIT_ENABLED=true` 會將安全事件記錄至本機的防竄改
  SQLite 資料庫,讀取需要 `audit.read` 權限。
- **速率限制**:`RATE_LIMIT_ENABLED=true` 依端點類別限制請求速率。
- **多執行個體部署**:`REDIS_ENABLED=true` 在多個 API 容器間共享工作
  階段、確認重放與速率限制狀態。

三種部署設定檔,透過 `MASKGUARD_DEPLOYMENT_PROFILE` 選擇:

| 設定檔 | Compose 檔案 | 需求 |
|---|---|---|
| `development`(預設) | `docker-compose.yml` | 無 |
| `single-instance-enterprise` | `docker-compose.prod.yml` | 需同時啟用 OIDC + 授權 + 稽核 + 速率限制 |
| `multi-instance-enterprise` | `docker-compose.multi.yml` | 上述項目,再加上 Redis |

宣告企業設定檔後,若其所需的控制項未全部一致啟用,應用程式會拒絕啟
動。

`GET /api/v1/health`(存活檢查)與 `GET /api/v1/ready`(就緒檢查,
`REDIS_ENABLED=true` 時會回報 Redis 可用性)隨時可用。

## 測試

```bash
python -m pytest              # 僅單元測試 —— 不需要 Tesseract
python -m pytest -m e2e       # 真實 OCR 端對端測試 —— 需要 Tesseract(見上方)
python -m pytest -m benchmark # OCR 效能基準測試套件 —— 需要 Tesseract;見 benchmarks/README.md
python -m pytest -m api       # HTTP API 測試 —— 需要 `api` extra;大多數也需要 Tesseract
```

E2E 測試絕不會在缺少真實 OCR 環境的情況下悄悄通過:若 Tesseract 或
`chi_tra` 語言資料缺失,每個 E2E 測試都會回報 **SKIPPED**(而非
PASS),並具體指出缺少哪一項。

### 產生 E2E 測試素材

```bash
python scripts/generate_test_images.py
```

重新產生 `tests/fixtures/*.png` + `manifest.json`,內容皆為合成測試資
料。若修改 `scripts/generate_test_images.py` 中的測試素材內容,請重新
執行此指令。
