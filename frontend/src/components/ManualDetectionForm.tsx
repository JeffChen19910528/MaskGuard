import { useLanguage } from "../i18n/LanguageContext";
import { manualDetectionTypeLabel, manualDetectionTypeOptions } from "../utils/reviewTypes";
import type { PendingManualBox } from "./ManualBoxOverlay";

interface ManualDetectionFormProps {
  drawEnabled: boolean;
  onToggleDraw: () => void;
  selectedType: string;
  onSelectedTypeChange: (type: string) => void;
  pendingBoxes: PendingManualBox[];
  onRemove: (localId: string) => void;
  disabled?: boolean;
}

/**
 * "Add a sensitive region" control (Phase 8.3 §10/§22): lets a reviewer
 * pick a sensitive TYPE from a server-authoritative allowlist (§11 —
 * utils/reviewTypes.ts, re-validated by the backend regardless) and then
 * draw a rectangle on the original image (ImageViewer's draw mode). This
 * component never computes risk/action/confidence and never masks
 * anything — it only collects WHERE and WHAT KIND, exactly like §10
 * requires.
 */
export function ManualDetectionForm({
  drawEnabled, onToggleDraw, selectedType, onSelectedTypeChange, pendingBoxes, onRemove, disabled,
}: ManualDetectionFormProps) {
  const { t } = useLanguage();
  const typeOptions = manualDetectionTypeOptions(t);

  return (
    <div className="manual-detection-form">
      <div className="manual-detection-form__controls">
        <label htmlFor="manual-type-select">{t.manualForm.typeLabel}</label>
        <select
          id="manual-type-select"
          value={selectedType}
          onChange={(event) => onSelectedTypeChange(event.target.value)}
          disabled={disabled}
        >
          {typeOptions.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
        <button type="button" onClick={onToggleDraw} disabled={disabled} aria-pressed={drawEnabled}>
          {drawEnabled ? t.manualForm.toggleDrawOn : t.manualForm.toggleDrawOff}
        </button>
      </div>
      {drawEnabled && <p className="manual-detection-form__hint">{t.manualForm.drawHint}</p>}

      {pendingBoxes.length > 0 && (
        <ul className="manual-detection-form__pending" aria-label={t.manualForm.pendingListLabel}>
          {pendingBoxes.map((box) => {
            const label = manualDetectionTypeLabel(box.type, t);
            return (
              <li key={box.localId}>
                <span>{t.manualForm.pendingSourceLabel(label)}</span>
                <button type="button" onClick={() => onRemove(box.localId)}>
                  {t.manualForm.cancel}
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
