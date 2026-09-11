import { useEffect, useRef, useState } from "react";
import { ApiClientError, analyzeImage, redactImage, submitReview, type RedactResult, type ReviewResult } from "../api/client";
import type { AnalyzeResponse, BBox, ReviewItemRequest } from "../api/types";
import { AuthStatus } from "../components/AuthStatus";
import { DetectionList, type ReviewState } from "../components/DetectionList";
import { ErrorNotice } from "../components/ErrorNotice";
import { ImageUploader } from "../components/ImageUploader";
import { ImageViewer } from "../components/ImageViewer";
import { ManualDetectionForm } from "../components/ManualDetectionForm";
import type { PendingManualBox } from "../components/ManualBoxOverlay";
import { PrivacyNotice } from "../components/PrivacyNotice";
import { ProcessingIndicator } from "../components/ProcessingIndicator";
import { StatusBanner } from "../components/StatusBanner";
import { MANUAL_DETECTION_TYPES } from "../utils/reviewTypes";

type Phase = "idle" | "analyzing" | "analyzed" | "redacting" | "redacted" | "reviewing" | "reviewed";

const NETWORK_ERROR_MESSAGES: Record<string, string> = {
  INVALID_IMAGE: "上傳的檔案不是有效的圖片格式。",
  FILE_TOO_LARGE: "檔案超過允許的大小上限。",
  IMAGE_DIMENSIONS_INVALID: "圖片尺寸超過允許的範圍。",
  PROCESSING_TIMEOUT: "處理時間過長，請稍後再試。",
  VALIDATION_ERROR: "請求格式不正確，請重新選擇圖片。",
  NETWORK_ERROR: "無法連線至 MaskGuard 伺服器，請確認伺服器是否啟動。",
  CLIENT_TIMEOUT: "等待伺服器回應逾時，請稍後再試。",
  HTTP_ERROR: "伺服器回應發生非預期錯誤。",
  INTERNAL_ERROR: "伺服器發生非預期錯誤。",
  // Phase 8.3
  INVALID_REVIEW: "人工確認資料無效，請重新分析圖片。",
  UNKNOWN_DETECTION: "找不到對應的偵測項目，請重新分析圖片。",
  INVALID_BBOX: "選取的敏感區域無效。",
  INVALID_DETECTION_TYPE: "選取的敏感資料類型不受支援。",
  REVIEW_EXPIRED: "人工確認資料已過期，請重新分析圖片。",
  REVIEW_CONFLICT: "此次人工確認已送出過，請重新分析圖片後再試一次。",
};

function friendlyMessage(error: unknown): { message: string; requestId: string | null } {
  if (error instanceof ApiClientError) {
    return { message: NETWORK_ERROR_MESSAGES[error.code] ?? "發生非預期錯誤，請稍後再試。", requestId: error.requestId };
  }
  return { message: "發生非預期錯誤，請稍後再試。", requestId: null };
}

function createLocalId(): string {
  return typeof crypto !== "undefined" && "randomUUID" in crypto ? crypto.randomUUID() : `local-${Date.now()}-${Math.random()}`;
}

export function Home() {
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [phase, setPhase] = useState<Phase>("idle");

  const [analyzeResult, setAnalyzeResult] = useState<AnalyzeResponse | null>(null);
  const [analyzeError, setAnalyzeError] = useState<{ message: string; requestId: string | null } | null>(null);

  const [redactResult, setRedactResult] = useState<RedactResult | null>(null);
  const [redactedUrl, setRedactedUrl] = useState<string | null>(null);
  const [redactError, setRedactError] = useState<{ message: string; requestId: string | null } | null>(null);

  // Phase 8.3: Human Review state — entirely LOCAL until "提交人工確認結果"
  // is clicked; nothing here reaches the backend a byte at a time.
  const [reviewState, setReviewState] = useState<Map<string, ReviewState>>(new Map());
  const [manualBoxes, setManualBoxes] = useState<PendingManualBox[]>([]);
  const [drawEnabled, setDrawEnabled] = useState(false);
  const [selectedManualType, setSelectedManualType] = useState(MANUAL_DETECTION_TYPES[0].value);
  const [reviewResult, setReviewResult] = useState<ReviewResult | null>(null);
  const [reviewedUrl, setReviewedUrl] = useState<string | null>(null);
  const [reviewError, setReviewError] = useState<{ message: string; requestId: string | null } | null>(null);

  // Object URLs must be revoked when replaced or on unmount (§27) — track
  // the current ones in refs so cleanup always targets the latest value.
  const previewUrlRef = useRef<string | null>(null);
  const redactedUrlRef = useRef<string | null>(null);
  const reviewedUrlRef = useRef<string | null>(null);

  useEffect(() => {
    return () => {
      if (previewUrlRef.current) URL.revokeObjectURL(previewUrlRef.current);
      if (redactedUrlRef.current) URL.revokeObjectURL(redactedUrlRef.current);
      if (reviewedUrlRef.current) URL.revokeObjectURL(reviewedUrlRef.current);
    };
  }, []);

  function handleFileSelected(file: File) {
    if (previewUrlRef.current) URL.revokeObjectURL(previewUrlRef.current);
    if (redactedUrlRef.current) {
      URL.revokeObjectURL(redactedUrlRef.current);
      redactedUrlRef.current = null;
    }
    if (reviewedUrlRef.current) {
      URL.revokeObjectURL(reviewedUrlRef.current);
      reviewedUrlRef.current = null;
    }
    const url = URL.createObjectURL(file);
    previewUrlRef.current = url;

    setSelectedFile(file);
    setPreviewUrl(url);
    setPhase("idle");
    setAnalyzeResult(null);
    setAnalyzeError(null);
    setRedactResult(null);
    setRedactedUrl(null);
    setRedactError(null);
    setReviewState(new Map());
    setManualBoxes([]);
    setDrawEnabled(false);
    setReviewResult(null);
    setReviewedUrl(null);
    setReviewError(null);
  }

  async function handleAnalyze() {
    if (!selectedFile || phase === "analyzing" || phase === "redacting" || phase === "reviewing") return;
    setPhase("analyzing");
    setAnalyzeError(null);
    try {
      const result = await analyzeImage(selectedFile);
      setAnalyzeResult(result);
      // Every finding starts PENDING — untouched by the reviewer (§16: a
      // PENDING CRITICAL item still gets redacted; see review_service.py).
      setReviewState(new Map(result.detections.map((d) => [d.detection_id, { status: "PENDING" as const, reason: "" }])));
      setManualBoxes([]);
      setReviewResult(null);
      setReviewedUrl(null);
      setPhase("analyzed");
    } catch (error) {
      setAnalyzeError(friendlyMessage(error));
      setPhase("idle");
    }
  }

  async function handleRedact() {
    if (!selectedFile || phase === "analyzing" || phase === "redacting" || phase === "reviewing") return;
    setPhase("redacting");
    setRedactError(null);
    try {
      const result = await redactImage(selectedFile);
      setRedactResult(result);
      if (result.kind === "image") {
        if (redactedUrlRef.current) URL.revokeObjectURL(redactedUrlRef.current);
        const url = URL.createObjectURL(result.blob);
        redactedUrlRef.current = url;
        setRedactedUrl(url);
      }
      setPhase("redacted");
    } catch (error) {
      setRedactError(friendlyMessage(error));
      setPhase("analyzed");
    }
  }

  function handleAccept(detectionId: string) {
    setReviewState((prev) => new Map(prev).set(detectionId, { status: "ACCEPTED", reason: "" }));
  }

  function handleReject(detectionId: string, reason: string) {
    setReviewState((prev) => new Map(prev).set(detectionId, { status: "REJECTED", reason }));
  }

  function handleBoxDrawn(bbox: BBox) {
    setManualBoxes((prev) => [...prev, { localId: createLocalId(), type: selectedManualType, bbox }]);
  }

  function handleRemoveManualBox(localId: string) {
    setManualBoxes((prev) => prev.filter((box) => box.localId !== localId));
  }

  async function handleSubmitReview() {
    if (!selectedFile || !analyzeResult?.review_token || phase === "analyzing" || phase === "redacting" || phase === "reviewing") {
      return;
    }
    const items: ReviewItemRequest[] = [];
    for (const [detectionId, state] of reviewState.entries()) {
      if (state.status === "ACCEPTED") items.push({ detection_id: detectionId, review_status: "ACCEPTED" });
      else if (state.status === "REJECTED") items.push({ detection_id: detectionId, review_status: "REJECTED", reason: state.reason });
    }
    for (const box of manualBoxes) {
      items.push({ type: box.type, bbox: box.bbox, source: "MANUAL" });
    }

    setPhase("reviewing");
    setReviewError(null);
    try {
      const result = await submitReview(selectedFile, analyzeResult.review_token, items);
      setReviewResult(result);
      if (result.kind === "image") {
        if (reviewedUrlRef.current) URL.revokeObjectURL(reviewedUrlRef.current);
        const url = URL.createObjectURL(result.blob);
        reviewedUrlRef.current = url;
        setReviewedUrl(url);
      }
      setPhase("reviewed");
    } catch (error) {
      setReviewError(friendlyMessage(error));
      setPhase("analyzed");
    }
  }

  const isBusy = phase === "analyzing" || phase === "redacting" || phase === "reviewing";

  return (
    <main className="app-layout">
      <header className="app-header">
        <h1>MaskGuard — 圖片敏感資料防護</h1>
        <AuthStatus />
        <PrivacyNotice />
      </header>

      <section className="app-layout__image" aria-label="圖片">
        <ImageUploader onFileSelected={handleFileSelected} disabled={isBusy} />

        {!selectedFile && <p className="empty-state">請上傳圖片開始分析</p>}

        {selectedFile && previewUrl && (
          <div className="image-panels">
            <ImageViewer
              src={previewUrl}
              alt="原始圖片預覽"
              label="原始圖片"
              detections={analyzeResult?.detections}
              manualBoxes={manualBoxes}
              onRemoveManualBox={handleRemoveManualBox}
              drawEnabled={drawEnabled}
              onBoxDrawn={handleBoxDrawn}
            />
            {redactResult?.kind === "image" && redactedUrl && (
              <ImageViewer src={redactedUrl} alt="遮罩後圖片" label="遮罩後圖片" />
            )}
            {reviewResult?.kind === "image" && reviewedUrl && reviewResult.headers.status !== "FAILED" && (
              <ImageViewer src={reviewedUrl} alt="人工確認後之遮罩圖片" label="遮罩後圖片（人工確認後）" />
            )}
          </div>
        )}

        {analyzeResult && (
          <ManualDetectionForm
            drawEnabled={drawEnabled}
            onToggleDraw={() => setDrawEnabled((prev) => !prev)}
            selectedType={selectedManualType}
            onSelectedTypeChange={setSelectedManualType}
            pendingBoxes={manualBoxes}
            onRemove={handleRemoveManualBox}
            disabled={isBusy}
          />
        )}
      </section>

      <section className="app-layout__results" aria-label="偵測結果">
        {phase === "analyzing" && <ProcessingIndicator label="分析中…" />}
        {phase === "redacting" && <ProcessingIndicator label="遮罩處理中…" />}
        {phase === "reviewing" && <ProcessingIndicator label="人工確認處理中…" />}

        {analyzeError && <ErrorNotice message={analyzeError.message} requestId={analyzeError.requestId} />}
        {redactError && <ErrorNotice message={redactError.message} requestId={redactError.requestId} />}
        {reviewError && <ErrorNotice message={reviewError.message} requestId={reviewError.requestId} />}

        {analyzeResult && (
          <>
            <StatusBanner status={analyzeResult.status} summary={analyzeResult.summary} detections={analyzeResult.detections} />
            <h2>偵測結果</h2>
            <DetectionList
              detections={analyzeResult.detections}
              reviewState={reviewState}
              onAccept={handleAccept}
              onReject={handleReject}
            />
          </>
        )}

        {redactResult?.kind === "blocked" && (
          <div className="blocked-notice" role="alert">
            <p>輸出已被 MaskGuard 阻擋</p>
            <p>{redactResult.detail.message}</p>
            {redactResult.detail.verification.needs_human_review && <p>此圖片需要人工確認後才能輸出。</p>}
          </div>
        )}

        {reviewResult?.kind === "blocked" && (
          <div className="blocked-notice" role="alert">
            <p>輸出已被 MaskGuard 阻擋</p>
            <p>{reviewResult.detail.message}</p>
            {reviewResult.detail.verification.needs_human_review && <p>此圖片需要人工確認後才能輸出。</p>}
          </div>
        )}

        {reviewResult?.kind === "image" && (
          <div
            className={`status-banner status-banner--${reviewResult.headers.status === "FAILED" ? "danger" : reviewResult.headers.status === "NEEDS_REVIEW" ? "warning" : "ok"}`}
            role="status"
            aria-live="polite"
          >
            <p className="status-banner__status">
              人工確認結果：
              {reviewResult.headers.status === "PASSED" && "驗證通過"}
              {reviewResult.headers.status === "NEEDS_REVIEW" && "需要人工確認"}
              {reviewResult.headers.status === "FAILED" && "驗證未通過，請勿使用此輸出。"}
              {reviewResult.headers.status === "BLOCKED" && "已阻擋輸出"}
            </p>
          </div>
        )}
      </section>

      <section className="app-layout__actions" aria-label="操作">
        <button type="button" onClick={handleAnalyze} disabled={!selectedFile || isBusy}>
          開始分析
        </button>
        <button type="button" onClick={handleRedact} disabled={!analyzeResult || isBusy}>
          執行遮罩
        </button>
        <button type="button" onClick={handleSubmitReview} disabled={!analyzeResult?.review_token || isBusy}>
          提交人工確認結果
        </button>
      </section>
    </main>
  );
}
