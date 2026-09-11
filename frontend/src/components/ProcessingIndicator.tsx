interface ProcessingIndicatorProps {
  label: string;
}

/** aria-live region announcing an in-progress backend call (§23/§30). */
export function ProcessingIndicator({ label }: ProcessingIndicatorProps) {
  return (
    <div className="processing-indicator" role="status" aria-live="polite">
      <span className="processing-indicator__spinner" aria-hidden="true" />
      <span>{label}</span>
    </div>
  );
}
