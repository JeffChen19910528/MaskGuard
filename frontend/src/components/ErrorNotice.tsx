interface ErrorNoticeProps {
  message: string;
  requestId?: string | null;
}

/**
 * User-friendly error display (§17). Only ever shown a pre-translated,
 * safe message string — never a raw exception, stack trace, or backend
 * traceback (the API client already strips those out; see api/client.ts).
 */
export function ErrorNotice({ message, requestId }: ErrorNoticeProps) {
  return (
    <div className="error-notice" role="alert">
      <p className="error-notice__message">{message}</p>
      {requestId && (
        <p className="error-notice__request-id">
          請提供以下追蹤編號給系統管理員：
          <br />
          Request ID: <code>{requestId}</code>
        </p>
      )}
    </div>
  );
}
