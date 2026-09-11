/**
 * Privacy notice (§24). Wording deliberately matches what Phase 8.1's
 * backend actually guarantees (stateless, temp-file processing with
 * cleanup on every exit path — see maskguard/api/service.py) — never
 * claims a guarantee ("100% 不儲存") the architecture doesn't provide.
 */
export function PrivacyNotice() {
  return (
    <p className="privacy-notice">
      圖片會傳送至 MaskGuard 伺服器進行分析。
      本版本採暫存處理，處理完成後會清理暫存檔案，不會永久保存圖片內容。
    </p>
  );
}
