/**
 * Client-side upload checks — UX convenience ONLY (Phase 8.2 §7). The
 * backend re-validates everything authoritatively (actual Pillow decode,
 * size/dimension limits); nothing here is a security boundary, and this
 * file must never be treated as one.
 */
import type { Translations } from "../i18n/translations";

const ACCEPTED_MIME_TYPES = ["image/png", "image/jpeg", "image/webp", "image/bmp", "image/tiff"];
// UX-only ceiling, intentionally generous — the backend's own configured
// limit (MASKGUARD_MAX_UPLOAD_SIZE_BYTES) is the real boundary.
const MAX_CLIENT_SIDE_HINT_BYTES = 25 * 1024 * 1024;

export interface ClientValidationResult {
  ok: boolean;
  message?: string;
}

export function validateSelectedFile(file: File, t: Translations): ClientValidationResult {
  if (!ACCEPTED_MIME_TYPES.includes(file.type)) {
    return { ok: false, message: t.uploader.errorInvalidType };
  }
  if (file.size === 0) {
    return { ok: false, message: t.uploader.errorEmptyFile };
  }
  if (file.size > MAX_CLIENT_SIDE_HINT_BYTES) {
    return { ok: false, message: t.uploader.errorTooLarge };
  }
  return { ok: true };
}
