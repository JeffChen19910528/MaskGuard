# Image Sensitive Data Masking Skill

## 1. Skill Overview

### Skill Name

**Image Sensitive Data Masking**

### Purpose

本 Skill 用於建立一套跨平台的圖片敏感資訊自動偵測與去識別化應用程式。

系統可讀取使用者提供的圖片，透過 OCR、影像分析與敏感資料規則辨識圖片中的文字內容，判斷其中是否包含個人資料、帳務資料、認證資訊、機密資訊或其他敏感資料。

系統在辨識後，自動於原始圖片對應位置執行：

- 遮罩（Mask）
- 模糊化（Blur）
- 像素化（Pixelation）
- 部分遮罩（Partial Mask）
- 完全移除（Redaction）

最後輸出已完成去識別化處理的圖片。

---

# 2. Core Objective

系統的核心目標：

```text
Input Image
    ↓
Image Preprocessing
    ↓
OCR / Vision Analysis
    ↓
Text Detection
    ↓
Sensitive Data Classification
    ↓
Risk Assessment
    ↓
Mask / Blur Decision
    ↓
Coordinate Mapping
    ↓
Image Redaction
    ↓
Verification
    ↓
Safe Output Image
```

系統必須確保：

1. 敏感文字能被正確辨識。
2. 敏感文字的位置能映射回原始圖片。
3. 敏感資料不能因為處理不完整而殘留。
4. 輸出的圖片不應包含原始敏感資訊。
5. 不應修改非敏感區域。
6. 使用者可以確認哪些內容被處理。
7. 原始圖片與處理後圖片可以分離管理。
8. 系統應避免將敏感資訊寫入一般 Log。

---

# 3. Supported Sensitive Data

系統應支援可擴充的敏感資料分類。

## 3.1 Personal Information

### High Risk

- 身分證字號
- 護照號碼
- 居留證號碼
- 駕照號碼
- 社會安全號碼
- 個人識別碼

### Medium Risk

- 姓名
- 電話號碼
- Email
- 地址
- 生日
- 公司名稱與個人職稱組合
- 員工編號
- 客戶編號

---

# 4. Financial Information

應偵測：

- 信用卡號
- 銀行帳號
- 銀行卡號
- IBAN
- 金融交易編號
- 發票資訊
- 付款資訊
- 帳單資訊
- 交易金額與帳戶資訊組合

對於信用卡等資訊，應支援：

```text
1234 5678 9012 3456
```

辨識為：

```text
**** **** **** 3456
```

或直接完全遮罩。

---

# 5. Authentication and Security Information

此類資訊應視為高風險資料。

系統應偵測：

- Password
- PIN
- API Key
- Access Token
- Refresh Token
- JWT
- Secret Key
- Private Key
- SSH Key
- Connection String
- Database Password
- Cloud Credential
- Authorization Header
- Bearer Token
- Session ID
- Cookie
- QR Code 中可能包含的敏感資訊

例如：

```text
API_KEY=xxxxxxxxxxxxxxxx
```

應直接完全遮罩，而非僅模糊化。

---

# 6. Business Sensitive Information

可選擇支援：

- 公司內部文件
- 合約資訊
- 報價
- 成本
- 客戶資料
- 供應商資料
- 員工資料
- 內部帳號
- 內部 IP
- Server 資訊
- Database 資訊
- Internal URL
- 系統設定資訊

此部分應透過：

- Regex
- Keyword
- Dictionary
- Pattern
- AI Classification
- User-defined rules

進行擴充。

---

# 7. Detection Architecture

系統應採用多階段偵測機制。

```text
                ┌──────────────┐
                │   Image      │
                └──────┬───────┘
                       ↓
              ┌─────────────────┐
              │ Image Preprocess│
              └────────┬────────┘
                       ↓
              ┌─────────────────┐
              │ OCR / Vision    │
              └────────┬────────┘
                       ↓
          ┌──────────────────────────┐
          │ Text + Bounding Boxes    │
          └────────────┬─────────────┘
                       ↓
       ┌────────────────────────────────┐
       │ Sensitive Data Detection       │
       │                                │
       │ Regex                         │
       │ Keyword                       │
       │ Dictionary                    │
       │ Pattern                       │
       │ AI Classification             │
       └───────────────┬────────────────┘
                       ↓
              ┌─────────────────┐
              │ Risk Assessment │
              └────────┬────────┘
                       ↓
              ┌─────────────────┐
              │ Masking Policy  │
              └────────┬────────┘
                       ↓
              ┌─────────────────┐
              │ Image Redaction │
              └────────┬────────┘
                       ↓
              ┌─────────────────┐
              │ Verification    │
              └────────┬────────┘
                       ↓
              ┌─────────────────┐
              │ Output Image    │
              └─────────────────┘
```

---

# 8. OCR Requirements

OCR Engine 必須提供至少：

```text
recognized_text
confidence
bounding_box
page / region
```

例如：

```json
{
  "text": "A123456789",
  "confidence": 0.97,
  "bounding_box": {
    "x": 420,
    "y": 320,
    "width": 180,
    "height": 35
  }
}
```

系統不得只取得文字內容，而必須保留文字在圖片中的座標。

---

# 9. Multi-Engine OCR Architecture

OCR 應採用可替換架構：

```text
IOcrEngine
    ├── LocalOcrEngine
    ├── CloudOcrEngine
    ├── WindowsOcrEngine
    └── CustomVisionEngine
```

避免將系統綁定於單一 OCR Provider。

建議至少提供：

### Offline Mode

圖片不離開本機。

適用：

- 公司內部文件
- 個資
- 機密文件
- 無網路環境

### Cloud AI Mode

使用外部 Vision / OCR API。

適用：

- OCR accuracy 優先
- 複雜文件
- 手寫文字
- 多語言圖片

使用 Cloud Mode 時，UI 必須明確提示使用者圖片可能會傳送至第三方服務。

---

# 10. Sensitive Data Detection

敏感資料辨識採用多層策略。

## Layer 1 — Regex

例如：

```text
Email
Phone
Credit Card
Taiwan ID
Passport
IP Address
URL
JWT
API Key
```

Regex 適合處理具有固定格式的資訊。

---

## Layer 2 — Keyword Detection

例如：

```text
Password
密碼
帳號
身分證
護照
信用卡
銀行帳號
API Key
Token
Secret
Private Key
```

Keyword 本身不應直接判定為敏感資料，而應提高該區域的風險分數。

---

## Layer 3 — Context Analysis

例如：

```text
姓名：王小明
電話：0912345678
身分證：A123456789
```

即使單獨的「王小明」無法透過 Regex 判定，透過上下文可以判斷其為個人資料。

---

## Layer 4 — AI Classification

AI 可分析：

```text
Text
+
Surrounding Text
+
Document Context
+
OCR Position
```

判斷：

```text
Sensitive
Non-Sensitive
Unknown
```

AI 不應直接擁有最終遮罩權限。

最終決策應由 Policy Engine 控制。

---

# 11. Risk Scoring

每一個偵測結果應具有 Risk Score。

例如：

```text
0.00 - 0.29
LOW

0.30 - 0.59
MEDIUM

0.60 - 0.79
HIGH

0.80 - 1.00
CRITICAL
```

例如：

```json
{
  "text": "A123456789",
  "type": "TaiwanID",
  "confidence": 0.98,
  "risk": "CRITICAL"
}
```

---

# 12. Masking Policy

不同敏感資料應使用不同處理方式。

## Critical

預設：

```text
FULL_MASK
```

例如：

- Password
- Private Key
- API Key
- Token
- 身分證號
- 信用卡號
- 銀行帳號

---

## High

預設：

```text
BLUR
```

例如：

- 姓名
- 電話
- 地址
- Email

---

## Medium

可使用：

```text
PARTIAL_MASK
```

例如：

```text
0912****78
john****@gmail.com
****3456
```

---

# 13. Redaction Methods

系統至少支援以下模式。

## 13.1 Solid Mask

以實心矩形覆蓋：

```text
████████████████
```

適合：

- Password
- Token
- API Key
- ID
- Credit Card

---

## 13.2 Blur

使用 Gaussian Blur。

可設定：

```text
blur_radius
kernel_size
```

---

## 13.3 Pixelation

將區域縮小後放大，產生馬賽克效果。

---

## 13.4 Partial Mask

只保留部分資訊。

例如：

```text
A123456789

→

A********
```

---

# 14. Coordinate Handling

OCR Bounding Box 必須轉換成影像座標。

系統必須考慮：

- Image Scaling
- Rotation
- EXIF Orientation
- DPI
- Cropping
- Perspective
- Multi-page Image
- Screenshot Resolution

處理流程：

```text
OCR Coordinate
       ↓
Normalize
       ↓
Transform
       ↓
Original Image Coordinate
       ↓
Redaction Rectangle
```

---

# 15. Image Preprocessing

OCR 前可進行：

- Resize
- Grayscale
- Contrast Enhancement
- Noise Reduction
- Sharpen
- Deskew
- Rotation Detection
- Perspective Correction
- Adaptive Threshold

但必須保留原始圖片座標映射資訊。

---

# 16. Verification

遮罩完成後必須再次執行 OCR。

```text
Original Image
      ↓
OCR
      ↓
Sensitive Detection
      ↓
Mask
      ↓
OCR Again
      ↓
Sensitive Detection Again
```

如果處理後仍偵測到原敏感資料：

```text
Verification Failed
```

系統應自動：

1. 擴大遮罩範圍。
2. 提高 Blur 強度。
3. 改用 Solid Mask。
4. 再次 OCR。
5. 直到通過驗證或標記為需要人工確認。

---

# 17. False Positive Handling

系統不得將所有符合格式的文字直接遮罩。

例如：

```text
Version: 1.2.3.4
```

不應直接認定為 IP。

因此應使用：

```text
Pattern
+
Context
+
Confidence
+
Risk Score
```

共同判斷。

---

# 18. False Negative Protection

對於高風險資訊：

```text
Password
Private Key
API Key
Token
Credit Card
ID Number
```

如果 AI / OCR 判斷不確定：

```text
UNKNOWN
```

應採用：

```text
Fail-Safe Policy
```

必要時要求人工確認。

---

# 19. Human Review

UI 應提供人工確認模式。

例如：

```text
┌──────────────────────────────┐
│ Sensitive Data Review        │
├──────────────────────────────┤
│                              │
│ [Image Preview]              │
│                              │
│ ██████████████               │
│                              │
│ Detected: Credit Card        │
│ Confidence: 98%              │
│ Action: Full Mask            │
│                              │
│ [Keep] [Mask] [Blur] [Ignore]│
└──────────────────────────────┘
```

使用者可以：

- 確認遮罩
- 修改遮罩範圍
- 改變 Blur / Mask
- 忽略誤判
- 手動新增遮罩區域

---

# 20. User Defined Rules

使用者應可以建立自訂敏感資料規則。

例如：

```yaml
name: InternalEmployeeID

pattern: "EMP-[0-9]{6}"

action: MASK

risk: HIGH
```

或：

```yaml
name: InternalServer

keywords:
  - "DB Server"
  - "Internal Server"
  - "Production"

action: BLUR
```

---

# 21. Configuration

設定檔例如：

```yaml
ocr:
  engine: local
  language:
    - zh-TW
    - en

detection:
  enable_regex: true
  enable_keyword: true
  enable_context: true
  enable_ai: true

masking:
  default_action: blur
  critical_action: mask
  verification: true

output:
  format: png
  preserve_metadata: false
```

---

# 22. Privacy Requirements

這是本工具的重要設計要求。

## 原始圖片

預設：

```text
Never upload without user consent.
```

如果使用 Cloud AI：

```text
User must explicitly enable Cloud Processing.
```

---

## Log

Log 不得記錄：

```text
原始敏感文字
完整 OCR Text
Password
Token
API Key
Credit Card
ID Number
```

應記錄：

```text
Detected Type
Confidence
Bounding Box
Action
Timestamp
Processing ID
```

例如：

```json
{
  "type": "CreditCard",
  "confidence": 0.98,
  "action": "MASK",
  "region": [120, 240, 320, 280]
}
```

---

# 23. Metadata Protection

輸出圖片時預設移除可能包含敏感資訊的 Metadata。

例如：

- EXIF
- GPS
- Camera Information
- Author
- Software
- Comments
- Embedded Thumbnail

預設：

```text
preserve_metadata = false
```

---

# 24. Output

輸出應至少包含：

```text
original/
processed/
report/
```

例如：

```text
output/
├── processed_image.png
├── processing_report.json
└── audit.log
```

但：

**processing_report.json 不得保存完整敏感文字。**

---

# 25. Processing Report

範例：

```json
{
  "processing_id": "20260910-000001",
  "input": "document.png",
  "output": "document_masked.png",
  "detections": [
    {
      "type": "TaiwanID",
      "confidence": 0.97,
      "risk": "CRITICAL",
      "action": "MASK",
      "region": [100, 250, 300, 290]
    },
    {
      "type": "Email",
      "confidence": 0.94,
      "risk": "HIGH",
      "action": "BLUR",
      "region": [120, 310, 400, 340]
    }
  ],
  "verification": {
    "status": "PASSED"
  }
}
```

---

# 26. Supported Image Formats

至少支援：

```text
PNG
JPG / JPEG
WEBP
BMP
TIFF
```

可選：

```text
PDF
HEIC
```

PDF 若支援，應先轉換為影像再處理。

---

# 27. Batch Processing

系統應支援：

```text
Single Image
Folder
Multiple Images
```

例如：

```text
input/
├── image001.png
├── image002.jpg
├── screenshot.png
└── document.jpg
```

輸出：

```text
output/
├── image001_masked.png
├── image002_masked.jpg
├── screenshot_masked.png
└── document_masked.jpg
```

---

# 28. API Architecture

如果未來需要整合其他系統，提供 REST API。

例如：

```http
POST /api/v1/analyze
```

```http
POST /api/v1/redact
```

```http
POST /api/v1/process
```

Response：

```json
{
  "status": "success",
  "output": "processed_image.png",
  "verification": "passed"
}
```

---

# 29. Recommended Architecture

建議採用模組化架構：

```text
Application
│
├── UI
│
├── Image Processor
│
├── OCR Engine
│
├── Detection Engine
│   ├── Regex Detector
│   ├── Keyword Detector
│   ├── Context Detector
│   └── AI Detector
│
├── Risk Engine
│
├── Policy Engine
│
├── Redaction Engine
│   ├── Mask
│   ├── Blur
│   ├── Pixelate
│   └── Partial Mask
│
├── Verification Engine
│
├── Audit Logger
│
└── Configuration
```

---

# 30. Recommended Technology

## Desktop Version

Windows：

```text
.NET 8
WPF
```

或：

```text
.NET 8
WinUI 3
```

跨平台：

```text
.NET 8
Avalonia UI
```

Linux / Windows / macOS：

```text
Python
OpenCV
PaddleOCR / Tesseract
```

---

# 31. AI Integration

AI 應設計為 Optional Provider。

```text
IAiDetector
    ├── OpenAIProvider
    ├── LocalLLMProvider
    ├── OllamaProvider
    └── CustomVisionProvider
```

系統必須允許：

```text
Rule Only
Rule + Local AI
Rule + Cloud AI
```

三種模式。

---

# 32. Local AI Mode

如果公司資料不能離開內部環境，可以使用 Local AI。

例如：

```text
Application
      ↓
OCR
      ↓
Local AI
      ↓
Sensitive Classification
      ↓
Redaction
```

Local AI 不應將圖片或文字傳送至外部服務。

---

# 33. Security Principles

系統必須遵循：

### Privacy by Design

敏感資料預設不外傳。

### Least Privilege

AI、OCR、File System 等元件只取得必要權限。

### Fail Safe

高風險資料判斷不確定時，不應直接忽略。

### No Sensitive Logging

Log 不保存敏感原文。

### Secure Temporary Files

暫存圖片應：

- 使用隨機檔名
- 限制權限
- 完成後刪除
- 避免寫入公開 Temp Directory

---

# 34. Performance Requirements

單張圖片處理應提供：

```text
OCR Time
Detection Time
Redaction Time
Verification Time
Total Time
```

例如：

```text
OCR          1.2 sec
Detection    0.3 sec
Redaction    0.1 sec
Verification 0.8 sec
----------------------
Total        2.4 sec
```

Batch Processing 應支援平行處理，但必須避免因 CPU / Memory 使用過高導致系統不穩定。

---

# 35. Testing

測試資料至少包含：

### Personal Data

- 身分證
- 護照
- 電話
- Email
- 地址

### Financial

- 信用卡
- 銀行帳號
- 發票

### Security

- Password
- API Key
- JWT
- Private Key
- Connection String

### Image Conditions

- 清晰圖片
- 模糊圖片
- 低解析度
- 傾斜
- 旋轉
- 深色背景
- 淺色背景
- 中文
- 英文
- 中英混合
- 手寫文字

---

# 36. Security Verification Test

最重要的測試不是：

```text
有沒有成功遮罩
```

而是：

```text
遮罩後是否仍能還原敏感資料？
```

測試流程：

```text
Input
 ↓
OCR
 ↓
Sensitive Detection
 ↓
Redaction
 ↓
OCR Again
 ↓
Sensitive Detection
 ↓
PASS / FAIL
```

對於 Critical Data：

```text
Residual Detection = 0
```

才算通過。

---

# 37. Acceptance Criteria

MVP 至少必須完成：

- [ ] 圖片載入
- [ ] OCR
- [ ] Bounding Box
- [ ] 敏感資料辨識
- [ ] Regex Detection
- [ ] Keyword Detection
- [ ] Risk Score
- [ ] Mask
- [ ] Blur
- [ ] Pixelation
- [ ] 手動調整遮罩
- [ ] 輸出圖片
- [ ] OCR Verification
- [ ] Processing Report
- [ ] Sensitive Data 不寫入 Log
- [ ] EXIF 清除
- [ ] Batch Processing

---

# 38. Future Features

後續可加入：

- PDF Sensitive Data Redaction
- Video Sensitive Data Redaction
- Webcam Real-time Redaction
- Screen Capture Redaction
- Face Detection
- License Plate Detection
- QR Code Detection
- Barcode Detection
- Handwriting Recognition
- Document Classification
- Enterprise Policy Server
- Centralized Audit
- RBAC
- Digital Signature
- Hash Verification
- Docker Deployment
- REST API
- CLI
- Windows Service
- Linux Service

---

# 39. CLI Example

應提供 CLI：

```bash
imgmask input.png --output masked.png
```

指定模式：

```bash
imgmask input.png \
  --mode strict \
  --ocr local \
  --verify
```

批次：

```bash
imgmask ./input \
  --output ./output \
  --recursive
```

---

# 40. Strict Mode

提供企業環境使用的 Strict Mode：

```text
Strict Mode
│
├── Local OCR only
├── Local AI only
├── No Cloud Upload
├── No Sensitive Logging
├── Remove EXIF
├── Critical Data → Full Mask
├── Verification Required
└── Verification Failure → Block Output
```

若 Verification 未通過：

```text
Do NOT release processed image.
```

---

# 41. Important Design Rule

系統最重要的原則：

> **「AI 負責理解，Rule Engine 負責判定，Policy Engine 負責決定處理方式，Redaction Engine 負責執行，Verification Engine 負責確認。」**

不要讓單一 AI 模型直接決定最終結果。

推薦架構：

```text
                 AI / OCR
                    │
                    ↓
             ┌──────────────┐
             │ Detection    │
             └──────┬───────┘
                    ↓
             ┌──────────────┐
             │ Risk Engine  │
             └──────┬───────┘
                    ↓
             ┌──────────────┐
             │ Policy Engine│
             └──────┬───────┘
                    ↓
             ┌──────────────┐
             │ Redaction    │
             └──────┬───────┘
                    ↓
             ┌──────────────┐
             │ Verification │
             └──────┬───────┘
                    ↓
              Safe Image
```

這樣的設計可以同時兼顧：

- OCR Accuracy
- AI Reasoning
- Deterministic Rules
- Privacy
- Security
- Auditability
- 可維護性
- 跨平台部署
- 未來 Enterprise Integration

並避免「AI 說這不是敏感資料，所以沒有遮罩」這類不可控結果。