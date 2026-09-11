import { MANUAL_DETECTION_TYPES } from "../utils/reviewTypes";
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
 * "新增敏感區域" control (Phase 8.3 §10/§22): lets a reviewer pick a
 * sensitive TYPE from a server-authoritative allowlist (§11 —
 * utils/reviewTypes.ts, re-validated by the backend regardless) and then
 * draw a rectangle on the original image (ImageViewer's draw mode). This
 * component never computes risk/action/confidence and never masks
 * anything — it only collects WHERE and WHAT KIND, exactly like §10
 * requires.
 */
export function ManualDetectionForm({
  drawEnabled, onToggleDraw, selectedType, onSelectedTypeChange, pendingBoxes, onRemove, disabled,
}: ManualDetectionFormProps) {
  return (
    <div className="manual-detection-form">
      <div className="manual-detection-form__controls">
        <label htmlFor="manual-type-select">敏感資料類型</label>
        <select
          id="manual-type-select"
          value={selectedType}
          onChange={(event) => onSelectedTypeChange(event.target.value)}
          disabled={disabled}
        >
          {MANUAL_DETECTION_TYPES.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
        <button type="button" onClick={onToggleDraw} disabled={disabled} aria-pressed={drawEnabled}>
          {drawEnabled ? "取消新增敏感區域" : "新增敏感區域"}
        </button>
      </div>
      {drawEnabled && <p className="manual-detection-form__hint">請在原始圖片上拖曳滑鼠繪製矩形區域</p>}

      {pendingBoxes.length > 0 && (
        <ul className="manual-detection-form__pending" aria-label="待送出的人工新增區域">
          {pendingBoxes.map((box) => {
            const label = MANUAL_DETECTION_TYPES.find((option) => option.value === box.type)?.label ?? box.type;
            return (
              <li key={box.localId}>
                <span>來源：人工新增 — {label}</span>
                <button type="button" onClick={() => onRemove(box.localId)}>
                  取消
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
