import { HttpErrorResponse } from '@angular/common/http';

/** A readable message from a FastAPI error body (`{detail: string | {message} | [{msg}]}`). */
export function errorMessage(err: unknown, fallback = 'Something went wrong. Try again.'): string {
  if (!(err instanceof HttpErrorResponse)) return fallback;
  if (err.status === 0) return 'Cannot reach the server. Is the backend running?';
  const detail = err.error?.detail;
  if (typeof detail === 'string') return detail;
  if (detail && typeof detail === 'object' && 'message' in detail) return String(detail.message);
  if (Array.isArray(detail) && detail.length) return detail.map((d) => d?.msg ?? String(d)).join('; ');
  return err.message || fallback;
}
