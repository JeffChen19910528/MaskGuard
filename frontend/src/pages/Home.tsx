import { useEffect, useRef, useState } from "react";
import { ApiClientError, analyzeImage, redactImage, submitReview, type RedactResult, type ReviewResult } from "../api/client";
import type { AnalyzeResponse, BBox, ReviewItemRequest } from "../api/types";
import { AuthStatus } from "../components/AuthStatus";
import { DetectionList, type ReviewState } from "../components/DetectionList";
import { ErrorNotice } from "../components/ErrorNotice";
import { ImageUploader } from "../components/ImageUploader";
import { ImageViewer } from "../components/ImageViewer";
import { LanguageSwitcher } from "../components/LanguageSwitcher";
import { ManualDetectionForm } from "../components/ManualDetectionForm";
import type { PendingManualBox } from "../components/ManualBoxOverlay";
import { PrivacyNotice } from "../components/PrivacyNotice";
import { ProcessingIndicator } from "../components/ProcessingIndicator";
import { StatusBanner } from "../components/StatusBanner";
import { useLanguage } from "../i18n/LanguageContext";
import type { Translations } from "../i18n/translations";
import { MANUAL_DETECTION_TYPE_VALUES } from "../utils/reviewTypes";

type Phase = "idle" | "analyzing" | "analyzed" | "redacting" | "redacted" | "reviewing" | "reviewed";

function friendlyMessage(error: unknown, t: Translations): { message: string; requestId: string | null } {
  if (error instanceof ApiClientError) {
    return { message: t.errors[error.code] ?? t.errors.GENERIC, requestId: error.requestId };
  }
  return { message: t.errors.GENERIC, requestId: null };
}

function createLocalId(): string {
  return typeof crypto !== "undefined" && "randomUUID" in crypto ? crypto.randomUUID() : `local-${Date.now()}-${Math.random()}`;
}

export function Home() {
  const { t } = useLanguage();
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [phase, setPhase] = useState<Phase>("idle");

  const [analyzeResult, setAnalyzeResult] = useState<AnalyzeResponse | null>(null);
  const [analyzeError, setAnalyzeError] = useState<{ message: string; requestId: string | null } | null>(null);

  const [redactResult, setRedactResult] = useState<RedactResult | null>(null);
  const [redactedUrl, setRedactedUrl] = useState<string | null>(null);
  const [redactError, setRedactError] = useState<{ message: string; requestId: string | null } | null>(null);

  // Phase 8.3: Human Review state — entirely LOCAL until "submit review"
  // is clicked; nothing here reaches the backend a byte at a time.
  const [reviewState, setReviewState] = useState<Map<string, ReviewState>>(new Map());
  const [manualBoxes, setManualBoxes] = useState<PendingManualBox[]>([]);
  const [drawEnabled, setDrawEnabled] = useState(false);
  const [selectedManualType, setSelectedManualType] = useState(MANUAL_DETECTION_TYPE_VALUES[0]);
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
      setAnalyzeError(friendlyMessage(error, t));
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
      setRedactError(friendlyMessage(error, t));
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
      setReviewError(friendlyMessage(error, t));
      setPhase("analyzed");
    }
  }

  const isBusy = phase === "analyzing" || phase === "redacting" || phase === "reviewing";

  return (
    <main className="app-layout">
      <header className="app-header">
        <h1>{t.app.title}</h1>
        <LanguageSwitcher />
        <AuthStatus />
        <PrivacyNotice />
      </header>

      <section className="app-layout__image" aria-label={t.home.imageAreaLabel}>
        <ImageUploader onFileSelected={handleFileSelected} disabled={isBusy} />

        {!selectedFile && <p className="empty-state">{t.home.emptyState}</p>}

        {selectedFile && previewUrl && (
          <div className="image-panels">
            <ImageViewer
              src={previewUrl}
              alt={t.home.originalAlt}
              label={t.home.originalLabel}
              detections={analyzeResult?.detections}
              manualBoxes={manualBoxes}
              onRemoveManualBox={handleRemoveManualBox}
              drawEnabled={drawEnabled}
              onBoxDrawn={handleBoxDrawn}
            />
            {redactResult?.kind === "image" && redactedUrl && (
              <ImageViewer src={redactedUrl} alt={t.home.redactedAlt} label={t.home.redactedLabel} />
            )}
            {reviewResult?.kind === "image" && reviewedUrl && reviewResult.headers.status !== "FAILED" && (
              <ImageViewer src={reviewedUrl} alt={t.home.reviewedAlt} label={t.home.reviewedLabel} />
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

      <section className="app-layout__results" aria-label={t.home.resultsAreaLabel}>
        {phase === "analyzing" && <ProcessingIndicator label={t.home.analyzing} />}
        {phase === "redacting" && <ProcessingIndicator label={t.home.redacting} />}
        {phase === "reviewing" && <ProcessingIndicator label={t.home.reviewing} />}

        {analyzeError && <ErrorNotice message={analyzeError.message} requestId={analyzeError.requestId} />}
        {redactError && <ErrorNotice message={redactError.message} requestId={redactError.requestId} />}
        {reviewError && <ErrorNotice message={reviewError.message} requestId={reviewError.requestId} />}

        {analyzeResult && (
          <>
            <StatusBanner status={analyzeResult.status} summary={analyzeResult.summary} detections={analyzeResult.detections} />
            <h2>{t.home.detectionResultsHeading}</h2>
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
            <p>{t.home.blockedTitle}</p>
            <p>{redactResult.detail.message}</p>
            {redactResult.detail.verification.needs_human_review && <p>{t.home.blockedNeedsReview}</p>}
          </div>
        )}

        {reviewResult?.kind === "blocked" && (
          <div className="blocked-notice" role="alert">
            <p>{t.home.blockedTitle}</p>
            <p>{reviewResult.detail.message}</p>
            {reviewResult.detail.verification.needs_human_review && <p>{t.home.blockedNeedsReview}</p>}
          </div>
        )}

        {reviewResult?.kind === "image" && (
          <div
            className={`status-banner status-banner--${reviewResult.headers.status === "FAILED" ? "danger" : reviewResult.headers.status === "NEEDS_REVIEW" ? "warning" : "ok"}`}
            role="status"
            aria-live="polite"
          >
            <p className="status-banner__status">
              {t.home.reviewResultPrefix}
              {reviewResult.headers.status === "PASSED" && t.home.reviewResultPassed}
              {reviewResult.headers.status === "NEEDS_REVIEW" && t.home.reviewResultNeedsReview}
              {reviewResult.headers.status === "FAILED" && t.home.reviewResultFailed}
              {reviewResult.headers.status === "BLOCKED" && t.home.reviewResultBlocked}
            </p>
          </div>
        )}
      </section>

      <section className="app-layout__actions" aria-label={t.home.actionsAreaLabel}>
        <button type="button" onClick={handleAnalyze} disabled={!selectedFile || isBusy}>
          {t.home.startAnalyze}
        </button>
        <button type="button" onClick={handleRedact} disabled={!analyzeResult || isBusy}>
          {t.home.runRedact}
        </button>
        <button type="button" onClick={handleSubmitReview} disabled={!analyzeResult?.review_token || isBusy}>
          {t.home.submitReview}
        </button>
      </section>
    </main>
  );
}
