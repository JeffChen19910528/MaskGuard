/**
 * All UI-facing text lives here, in two locales. This is PRESENTATION
 * ONLY — nothing here decides risk/action/redaction; those decisions are
 * made server-side (see utils/presentation.ts's own docstring, unchanged
 * by localization). Every backend-facing value (detection type strings,
 * API error codes, review status enums) stays in English — only the
 * DISPLAYED label is localized.
 */
import type { OverallStatus, RiskLevel } from "../api/types";

export type Locale = "zh-TW" | "en";

export const LOCALES: { value: Locale; label: string }[] = [
  { value: "zh-TW", label: "繁體中文" },
  { value: "en", label: "English" },
];

export interface Translations {
  app: {
    title: string;
  };
  auth: {
    loggedInFallback: string;
    noReviewPermission: string;
    logout: string;
    login: string;
  };
  privacy: {
    notice: string;
  };
  uploader: {
    dropzoneLabel: string;
    hint: string;
    errorGeneric: string;
    errorInvalidType: string;
    errorEmptyFile: string;
    errorTooLarge: string;
  };
  manualTypes: Record<string, string>;
  manualBox: {
    addedByPrefix: string;
    removeAriaLabel: (label: string) => string;
  };
  manualForm: {
    typeLabel: string;
    toggleDrawOn: string;
    toggleDrawOff: string;
    drawHint: string;
    pendingListLabel: string;
    pendingSourceLabel: (label: string) => string;
    cancel: string;
  };
  detectionOverlay: {
    ariaLabel: (count: number) => string;
  };
  detectionList: {
    empty: string;
    ariaLabel: string;
    actionLabel: string;
    confidenceLabel: string;
    sourceAuto: string;
    needsReviewNote: string;
    statusLabel: string;
    reasonLabel: string;
    accept: string;
    reject: string;
    reasonPrompt: string;
    submitReason: string;
    cancel: string;
    status: Record<"PENDING" | "ACCEPTED" | "REJECTED", string>;
  };
  statusBanner: {
    statusLabel: string;
    totalDetections: string;
    critical: string;
    high: string;
    medium: string;
    low: string;
    needsReview: string;
  };
  errorNotice: {
    requestIdHint: string;
  };
  presentation: {
    risk: Record<RiskLevel, string>;
    status: Record<OverallStatus, string>;
  };
  home: {
    imageAreaLabel: string;
    resultsAreaLabel: string;
    actionsAreaLabel: string;
    emptyState: string;
    originalAlt: string;
    originalLabel: string;
    redactedAlt: string;
    redactedLabel: string;
    reviewedAlt: string;
    reviewedLabel: string;
    detectionResultsHeading: string;
    analyzing: string;
    redacting: string;
    reviewing: string;
    blockedTitle: string;
    blockedNeedsReview: string;
    reviewResultPrefix: string;
    reviewResultPassed: string;
    reviewResultNeedsReview: string;
    reviewResultFailed: string;
    reviewResultBlocked: string;
    startAnalyze: string;
    runRedact: string;
    submitReview: string;
  };
  errors: Record<string, string>;
}

const zhTW: Translations = {
  app: {
    title: "MaskGuard — 圖片敏感資料防護",
  },
  auth: {
    loggedInFallback: "已登入",
    noReviewPermission: "（無審核權限）",
    logout: "登出",
    login: "登入",
  },
  privacy: {
    notice:
      "圖片會傳送至 MaskGuard 伺服器進行分析。" +
      "本版本採暫存處理，處理完成後會清理暫存檔案，不會永久保存圖片內容。",
  },
  uploader: {
    dropzoneLabel: "選擇圖片，或將圖片拖曳至此",
    hint: "支援 PNG、JPEG、WEBP、BMP、TIFF",
    errorGeneric: "無法使用此檔案。",
    errorInvalidType: "請選擇圖片檔案（PNG、JPEG、WEBP、BMP 或 TIFF）。",
    errorEmptyFile: "檔案內容為空，請重新選擇圖片。",
    errorTooLarge: "檔案過大，請選擇較小的圖片。",
  },
  manualTypes: {
    TaiwanID: "身分證字號",
    Passport: "護照號碼",
    BankAccount: "銀行帳號",
    CreditCard: "信用卡號",
    SecretKeyValue: "密碼 / API 金鑰",
    BearerToken: "存取權杖（Bearer Token）",
    JWT: "JWT",
    Email: "電子郵件",
    Phone: "電話號碼",
    PersonalName: "姓名",
    Address: "地址",
  },
  manualBox: {
    addedByPrefix: "人工新增：",
    removeAriaLabel: (label) => `移除人工新增的${label}區域`,
  },
  manualForm: {
    typeLabel: "敏感資料類型",
    toggleDrawOn: "取消新增敏感區域",
    toggleDrawOff: "新增敏感區域",
    drawHint: "請在原始圖片上拖曳滑鼠繪製矩形區域",
    pendingListLabel: "待送出的人工新增區域",
    pendingSourceLabel: (label) => `來源：人工新增 — ${label}`,
    cancel: "取消",
  },
  detectionOverlay: {
    ariaLabel: (count) => `偵測到 ${count} 個標記區域`,
  },
  detectionList: {
    empty: "未偵測到需要處理的敏感資料",
    ariaLabel: "偵測結果",
    actionLabel: "處理方式",
    confidenceLabel: "信心度",
    sourceAuto: "來源：自動偵測",
    needsReviewNote: "此項目需要人工確認",
    statusLabel: "狀態",
    reasonLabel: "原因",
    accept: "✓ 確認處理",
    reject: "✕ 誤判",
    reasonPrompt: "請說明誤判原因",
    submitReason: "送出誤判原因",
    cancel: "取消",
    status: {
      PENDING: "待確認",
      ACCEPTED: "已確認",
      REJECTED: "標記為誤判",
    },
  },
  statusBanner: {
    statusLabel: "狀態",
    totalDetections: "偵測項目",
    critical: "Critical",
    high: "High",
    medium: "Medium",
    low: "Low",
    needsReview: "需人工確認",
  },
  errorNotice: {
    requestIdHint: "請提供以下追蹤編號給系統管理員：",
  },
  presentation: {
    risk: {
      CRITICAL: "CRITICAL（極高風險）",
      HIGH: "HIGH（高風險）",
      MEDIUM: "MEDIUM（中風險）",
      LOW: "LOW（低風險）",
    },
    status: {
      PASSED: "分析完成",
      NEEDS_REVIEW: "需要人工確認",
      BLOCKED: "已阻擋輸出",
      FAILED: "處理失敗",
      SKIPPED: "已略過驗證",
    },
  },
  home: {
    imageAreaLabel: "圖片",
    resultsAreaLabel: "偵測結果",
    actionsAreaLabel: "操作",
    emptyState: "請上傳圖片開始分析",
    originalAlt: "原始圖片預覽",
    originalLabel: "原始圖片",
    redactedAlt: "遮罩後圖片",
    redactedLabel: "遮罩後圖片",
    reviewedAlt: "人工確認後之遮罩圖片",
    reviewedLabel: "遮罩後圖片（人工確認後）",
    detectionResultsHeading: "偵測結果",
    analyzing: "分析中…",
    redacting: "遮罩處理中…",
    reviewing: "人工確認處理中…",
    blockedTitle: "輸出已被 MaskGuard 阻擋",
    blockedNeedsReview: "此圖片需要人工確認後才能輸出。",
    reviewResultPrefix: "人工確認結果：",
    reviewResultPassed: "驗證通過",
    reviewResultNeedsReview: "需要人工確認",
    reviewResultFailed: "驗證未通過，請勿使用此輸出。",
    reviewResultBlocked: "已阻擋輸出",
    startAnalyze: "開始分析",
    runRedact: "執行遮罩",
    submitReview: "提交人工確認結果",
  },
  errors: {
    INVALID_IMAGE: "上傳的檔案不是有效的圖片格式。",
    FILE_TOO_LARGE: "檔案超過允許的大小上限。",
    IMAGE_DIMENSIONS_INVALID: "圖片尺寸超過允許的範圍。",
    PROCESSING_TIMEOUT: "處理時間過長，請稍後再試。",
    VALIDATION_ERROR: "請求格式不正確，請重新選擇圖片。",
    NETWORK_ERROR: "無法連線至 MaskGuard 伺服器，請確認伺服器是否啟動。",
    CLIENT_TIMEOUT: "等待伺服器回應逾時，請稍後再試。",
    HTTP_ERROR: "伺服器回應發生非預期錯誤。",
    INTERNAL_ERROR: "伺服器發生非預期錯誤。",
    INVALID_REVIEW: "人工確認資料無效，請重新分析圖片。",
    UNKNOWN_DETECTION: "找不到對應的偵測項目，請重新分析圖片。",
    INVALID_BBOX: "選取的敏感區域無效。",
    INVALID_DETECTION_TYPE: "選取的敏感資料類型不受支援。",
    REVIEW_EXPIRED: "人工確認資料已過期，請重新分析圖片。",
    REVIEW_CONFLICT: "此次人工確認已送出過，請重新分析圖片後再試一次。",
    GENERIC: "發生非預期錯誤，請稍後再試。",
  },
};

const en: Translations = {
  app: {
    title: "MaskGuard — Sensitive Data Protection for Images",
  },
  auth: {
    loggedInFallback: "Signed in",
    noReviewPermission: " (no review permission)",
    logout: "Sign out",
    login: "Sign in",
  },
  privacy: {
    notice:
      "Images are sent to the MaskGuard server for analysis. " +
      "This version processes files in temporary storage only; temp files are removed after processing and no image content is retained permanently.",
  },
  uploader: {
    dropzoneLabel: "Choose an image, or drag one here",
    hint: "Supports PNG, JPEG, WEBP, BMP, TIFF",
    errorGeneric: "This file can't be used.",
    errorInvalidType: "Please choose an image file (PNG, JPEG, WEBP, BMP, or TIFF).",
    errorEmptyFile: "The file is empty. Please choose a different image.",
    errorTooLarge: "The file is too large. Please choose a smaller image.",
  },
  manualTypes: {
    TaiwanID: "Taiwan National ID",
    Passport: "Passport Number",
    BankAccount: "Bank Account Number",
    CreditCard: "Credit Card Number",
    SecretKeyValue: "Password / API Key",
    BearerToken: "Bearer Token",
    JWT: "JWT",
    Email: "Email Address",
    Phone: "Phone Number",
    PersonalName: "Personal Name",
    Address: "Address",
  },
  manualBox: {
    addedByPrefix: "Manually added: ",
    removeAriaLabel: (label) => `Remove the manually added ${label} region`,
  },
  manualForm: {
    typeLabel: "Sensitive data type",
    toggleDrawOn: "Cancel adding a sensitive region",
    toggleDrawOff: "Add a sensitive region",
    drawHint: "Drag on the original image to draw a rectangle",
    pendingListLabel: "Manually added regions pending submission",
    pendingSourceLabel: (label) => `Source: Manually added — ${label}`,
    cancel: "Cancel",
  },
  detectionOverlay: {
    ariaLabel: (count) => `${count} marked region(s) detected`,
  },
  detectionList: {
    empty: "No sensitive data requiring action was detected",
    ariaLabel: "Detection results",
    actionLabel: "Action",
    confidenceLabel: "Confidence",
    sourceAuto: "Source: Automatic detection",
    needsReviewNote: "This item requires human review",
    statusLabel: "Status",
    reasonLabel: "Reason",
    accept: "✓ Confirm",
    reject: "✕ False positive",
    reasonPrompt: "Please explain why this is a false positive",
    submitReason: "Submit reason",
    cancel: "Cancel",
    status: {
      PENDING: "Pending",
      ACCEPTED: "Confirmed",
      REJECTED: "Marked false positive",
    },
  },
  statusBanner: {
    statusLabel: "Status",
    totalDetections: "Detections",
    critical: "Critical",
    high: "High",
    medium: "Medium",
    low: "Low",
    needsReview: "Needs review",
  },
  errorNotice: {
    requestIdHint: "Please provide the following tracking ID to your system administrator:",
  },
  presentation: {
    risk: {
      CRITICAL: "CRITICAL",
      HIGH: "HIGH",
      MEDIUM: "MEDIUM",
      LOW: "LOW",
    },
    status: {
      PASSED: "Analysis complete",
      NEEDS_REVIEW: "Needs human review",
      BLOCKED: "Output blocked",
      FAILED: "Processing failed",
      SKIPPED: "Verification skipped",
    },
  },
  home: {
    imageAreaLabel: "Image",
    resultsAreaLabel: "Detection results",
    actionsAreaLabel: "Actions",
    emptyState: "Upload an image to begin analysis",
    originalAlt: "Original image preview",
    originalLabel: "Original image",
    redactedAlt: "Redacted image",
    redactedLabel: "Redacted image",
    reviewedAlt: "Redacted image after human review",
    reviewedLabel: "Redacted image (after review)",
    detectionResultsHeading: "Detection results",
    analyzing: "Analyzing…",
    redacting: "Redacting…",
    reviewing: "Processing review…",
    blockedTitle: "Output was blocked by MaskGuard",
    blockedNeedsReview: "This image requires human review before it can be released.",
    reviewResultPrefix: "Review result: ",
    reviewResultPassed: "Verification passed",
    reviewResultNeedsReview: "Needs human review",
    reviewResultFailed: "Verification failed — do not use this output.",
    reviewResultBlocked: "Output blocked",
    startAnalyze: "Start analysis",
    runRedact: "Run redaction",
    submitReview: "Submit review",
  },
  errors: {
    INVALID_IMAGE: "The uploaded file is not a valid image format.",
    FILE_TOO_LARGE: "The file exceeds the maximum allowed size.",
    IMAGE_DIMENSIONS_INVALID: "The image dimensions exceed the allowed range.",
    PROCESSING_TIMEOUT: "Processing took too long. Please try again later.",
    VALIDATION_ERROR: "The request was malformed. Please choose the image again.",
    NETWORK_ERROR: "Could not connect to the MaskGuard server. Please check that it's running.",
    CLIENT_TIMEOUT: "Timed out waiting for a server response. Please try again later.",
    HTTP_ERROR: "The server returned an unexpected error.",
    INTERNAL_ERROR: "The server encountered an unexpected error.",
    INVALID_REVIEW: "The review data is invalid. Please re-analyze the image.",
    UNKNOWN_DETECTION: "The corresponding detection could not be found. Please re-analyze the image.",
    INVALID_BBOX: "The selected sensitive region is invalid.",
    INVALID_DETECTION_TYPE: "The selected sensitive data type is not supported.",
    REVIEW_EXPIRED: "The review data has expired. Please re-analyze the image.",
    REVIEW_CONFLICT: "This review has already been submitted. Please re-analyze the image and try again.",
    GENERIC: "An unexpected error occurred. Please try again later.",
  },
};

export const translations: Record<Locale, Translations> = { "zh-TW": zhTW, en };
