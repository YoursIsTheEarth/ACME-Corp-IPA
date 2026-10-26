/** Every status the app displays, in one place, so a status looks the same on every page. */
export const STATUSES = [
  'Processing',
  'Retrying extraction',
  'Awaiting review',
  'Queued',
  'Paying',
  'Failed',
  'Paid',
  'Rejected',
  'Duplicate',
  'Superseded',
  'Credit confirmed',
  'Revised',
] as const;

export type Status = (typeof STATUSES)[number];

export interface StatusStyle {
  label: string;
  /** Chip background and text colors. */
  bg: string;
  fg: string;
  icon: string;
}

export const STATUS_STYLE: Record<Status, StatusStyle> = {
  Processing: { label: 'Processing', bg: '#e3f2fd', fg: '#0d47a1', icon: 'autorenew' },
  'Retrying extraction': { label: 'Retrying extraction', bg: '#fff3e0', fg: '#e65100', icon: 'replay' },
  'Awaiting review': { label: 'Awaiting review', bg: '#fff8e1', fg: '#8a5a00', icon: 'pending_actions' },
  Queued: { label: 'Queued', bg: '#ede7f6', fg: '#4527a0', icon: 'schedule' },
  Paying: { label: 'Paying', bg: '#e0f7fa', fg: '#006064', icon: 'sync' },
  Failed: { label: 'Failed', bg: '#ffebee', fg: '#b71c1c', icon: 'error' },
  Paid: { label: 'Paid', bg: '#e8f5e9', fg: '#1b5e20', icon: 'check_circle' },
  Rejected: { label: 'Rejected', bg: '#fce4ec', fg: '#880e4f', icon: 'block' },
  Duplicate: { label: 'Duplicate', bg: '#eceff1', fg: '#37474f', icon: 'content_copy' },
  Superseded: { label: 'Superseded', bg: '#f3e5f5', fg: '#6a1b9a', icon: 'swap_horiz' },
  'Credit confirmed': { label: 'Credit confirmed', bg: '#e0f2f1', fg: '#004d40', icon: 'savings' },
  // A revision of a paid invoice: its delta was paid, or the same total left nothing due.
  Revised: { label: 'Revised', bg: '#fbe9e7', fg: '#bf360c', icon: 'edit_note' },
};

const FALLBACK: StatusStyle = { label: '', bg: '#eeeeee', fg: '#424242', icon: 'help' };
const BY_KEY = new Map(STATUSES.map((s) => [s.toLowerCase(), STATUS_STYLE[s]]));

/** Style for a backend status value; payment-queue values are lower case (`queued`, `paying`, `failed`). */
export function statusStyle(status: string | null | undefined): StatusStyle {
  const value = (status ?? '').trim();
  return BY_KEY.get(value.toLowerCase()) ?? { ...FALLBACK, label: value || 'Unknown' };
}
