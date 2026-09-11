import { useId, useRef, useState, type ChangeEvent, type DragEvent } from "react";
import { useLanguage } from "../i18n/LanguageContext";
import { validateSelectedFile } from "../utils/validation";

interface ImageUploaderProps {
  onFileSelected: (file: File) => void;
  disabled?: boolean;
}

/**
 * Click-to-upload + drag-and-drop file picker. Only ever hands the raw
 * `File` object up to the caller (Home.tsx) — it never reads, decodes, or
 * inspects the image content itself, and never performs OCR/detection.
 * Client-side checks here are UX convenience only (Phase 8.2 §7) — the
 * backend re-validates authoritatively.
 */
export function ImageUploader({ onFileSelected, disabled }: ImageUploaderProps) {
  const { t } = useLanguage();
  const [isDragActive, setIsDragActive] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const inputId = useId();

  function handleFile(file: File | undefined | null) {
    if (!file) return;
    const result = validateSelectedFile(file, t);
    if (!result.ok) {
      setLocalError(result.message ?? t.uploader.errorGeneric);
      return;
    }
    setLocalError(null);
    onFileSelected(file);
  }

  function handleInputChange(event: ChangeEvent<HTMLInputElement>) {
    handleFile(event.target.files?.[0]);
    // Allow re-selecting the exact same file again later.
    event.target.value = "";
  }

  function handleDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setIsDragActive(false);
    handleFile(event.dataTransfer.files?.[0]);
  }

  return (
    <div>
      <div
        className={`uploader-dropzone${isDragActive ? " uploader-dropzone--active" : ""}`}
        onDragOver={(event) => {
          event.preventDefault();
          if (!disabled) setIsDragActive(true);
        }}
        onDragLeave={() => setIsDragActive(false)}
        onDrop={disabled ? undefined : handleDrop}
        role="button"
        tabIndex={disabled ? -1 : 0}
        aria-disabled={disabled}
        aria-describedby={`${inputId}-hint`}
        onClick={() => !disabled && inputRef.current?.click()}
        onKeyDown={(event) => {
          if (!disabled && (event.key === "Enter" || event.key === " ")) {
            event.preventDefault();
            inputRef.current?.click();
          }
        }}
      >
        <label htmlFor={inputId}>{t.uploader.dropzoneLabel}</label>
        <input
          ref={inputRef}
          id={inputId}
          type="file"
          accept="image/png,image/jpeg,image/webp,image/bmp,image/tiff"
          onChange={handleInputChange}
          disabled={disabled}
        />
        <p id={`${inputId}-hint`} className="uploader-hint">
          {t.uploader.hint}
        </p>
      </div>
      {localError && (
        <p role="alert" className="uploader-error">
          {localError}
        </p>
      )}
    </div>
  );
}
