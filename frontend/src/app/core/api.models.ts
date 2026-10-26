// Typed DTOs mirroring the `backend-api` responses (backend/src/acme/api/queries.py and routers/).
// Money is a 2-decimal string; timestamps are ISO 8601.

export type Money = string;

export interface ListResponse<T> {
  rows: T[];
  count: number;
  server_time: string;
}

export interface FindingRef {
  code: string;
  severity: 'CRITICAL' | 'WARNING' | 'INFO' | string | null;
  message: string | null;
}

export interface Finding extends FindingRef {
  evidence: Record<string, unknown>;
}

/** Fields every invoice-run row carries (queue, audit, review, detail). */
export interface RunRow {
  id: string;
  file_name: string;
  format: string;
  invoice_number: string | null;
  vendor: string | null;
  amount_usd: Money | null;
  stage: string | null;
  status: string;
  final_status: string | null;
  decided_by: string | null;
  uploaded_at: string;
  completed_at: string | null;
  stage_entered_at: string | null;
  time_in_stage_s: number | null;
  processing_s: number | null;
}

/** `view=queue`: `status` is Processing, Retrying extraction, or Awaiting review. */
export interface QueueRow extends RunRow {
  run_status: string;
}

export interface AuditRow extends RunRow {
  key_findings: FindingRef[];
  findings_count: number;
}

export type HoldKind = 'warning' | 'credit' | 'payment_failure' | 'payee_threshold';

/** One invoice counted in a payee total; `status` is its current run status. */
export interface PayeeInvoice {
  run_id: string | null;
  invoice_number: string;
  invoice_date: string;
  vendor: string | null;
  amount_usd: Money | null;
  status: string | null;
}

/** Why a payee threshold hold exists: the rolling payee total and the invoices in it. */
export interface PayeeThreshold {
  total_usd: Money | null;
  threshold_usd: Money | null;
  window_days: number | null;
  window_start: string | null;
  window_end: string | null;
  payees: string[];
  message: string | null;
  triggered_by: string | null;
  invoices: PayeeInvoice[];
}

export interface ReviewRow extends RunRow {
  hold_kind: HoldKind | null;
  reason: string | null;
  detail: string | null;
  last_error: string | null;
  attempts: number | null;
  findings: FindingRef[];
  ai_recommendation: string | null;
  ai_rationale: string | null;
  overpaid_usd: Money | null;
  paid_amount_usd: Money | null;
  /** Set when the cumulative payee threshold is (one of) the reasons for the hold. */
  payee_threshold: PayeeThreshold | null;
  /** An approved payment pulled from the Payment Queue into review. */
  pulled: boolean;
  waiting_since: string | null;
  waiting_s: number | null;
}

export interface InvoiceListResponse<T> extends ListResponse<T> {
  view: 'queue' | 'audit' | 'review';
}

export interface AuditFilter {
  status?: string;
  date_from?: string;
  date_to?: string;
  search?: string;
}

export interface LineItem {
  sku: string | null;
  raw_name: string | null;
  quantity: number | null;
  unit_price: string | null;
  amount: string | null;
  note: string | null;
}

export interface InvoiceFields {
  invoice_number: string | null;
  revision: number | null;
  vendor_name: string | null;
  vendor_address: string | null;
  invoice_date: string | null;
  due_date: string | null;
  currency: string | null;
  original_currency: string | null;
  original_total: string | null;
  line_items: LineItem[];
  subtotal?: string | null;
  tax?: string | null;
  total?: string | null;
  [key: string]: unknown;
}

export interface DecisionDto {
  outcome: string;
  rationale: string;
  rules_applied: string[];
  confidence: number | null;
  decided_by: string | null;
}

export interface LlmEntry {
  round: number | null;
  provider: string | null;
  model: string | null;
  ts: string;
  draft?: DecisionDto;
  critique?: Record<string, unknown>;
}

export interface TimelineEntry {
  ts: string;
  agent: string | null;
  event: string;
  payload: Record<string, any>;
}

export interface InvoiceDetail extends RunRow {
  invoice: InvoiceFields | null;
  extracted: InvoiceFields | null;
  findings: Finding[];
  decision: DecisionDto | null;
  drafts: LlmEntry[];
  critiques: LlmEntry[];
  reviews: { reviewer: string; decision: string; rationale: string; decided_at: string }[];
  hold: { kind: HoldKind; reason: string; details: Record<string, unknown> } | null;
  payment_queue: Record<string, unknown>[];
  payments: Record<string, unknown>[];
  rejection: Record<string, unknown> | null;
  timeline: TimelineEntry[];
}

export interface UploadFileResult {
  id: string | null;
  file_name: string;
  status: 'Uploaded' | 'rejected';
  size: number | null;
  error: string | null;
}

export interface UploadResponse {
  files: UploadFileResult[];
  accepted: number;
  rejected: number;
  server_time: string;
}

export type ReviewDecision = 'approve' | 'reject';

export interface ReviewRequest {
  decision: ReviewDecision;
  reviewer: string;
  rationale: string;
}

export interface ReviewResponse {
  id: string;
  decision: ReviewDecision;
  reviewer: string;
  status: string;
}

export type PaymentKind = 'full' | 'replacement' | 'delta';

export interface PaymentQueueRow {
  id: number;
  run_id: string;
  file_name: string | null;
  invoice_number: string;
  revision: number;
  vendor: string;
  amount_usd: Money;
  kind: PaymentKind;
  approved_by: string | null;
  queued_at: string;
  status: 'queued' | 'paying' | 'failed';
  attempts: number;
  last_error: string | null;
  batch_id: string | null;
}

export interface PaymentQueueResponse extends ListResponse<PaymentQueueRow> {
  total_usd: Money;
  /** Payment mode from the admin settings. */
  delay_payments: boolean;
  pay_at_end_of_day: boolean;
  /** Null when no end-of-day batch is scheduled (delay off, or pay at end of day off). */
  next_batch_at: string | null;
  next_batch_label: string | null;
  timezone: string;
  pay_when_queue_empty: boolean;
  idle_delay_s: number;
  batch_running: boolean;
}

/** `GET /api/admin/settings`: payment timing (F41). Unsaved values are the defaults. */
export interface PaymentTimingSettings {
  delay_payments: boolean;
  pay_at_end_of_day: boolean;
  /** 24-hour `HH:MM`, default `17:00`. */
  end_of_day_time: string;
  /** IANA name, default `America/Chicago`. */
  end_of_day_timezone: string;
  pay_when_queue_empty: boolean;
}

export interface AdminSettings extends PaymentTimingSettings {
  updated_by: string | null;
  updated_at: string | null;
}

/** `PUT /api/admin/settings`: all five settings and who saves them (1 to 50 characters after trimming). */
export interface AdminSettingsRequest extends PaymentTimingSettings {
  updated_by: string;
}

export interface ExecuteRequest {
  ids?: number[];
  released_by: string;
}

export interface ExecuteResponse {
  batch_id: string;
  trigger: BatchTrigger;
  released_by: string;
}

export type BatchTrigger = 'end_of_day' | 'idle' | 'immediate' | 'pay_all' | 'pay_selected' | 'pay_now';

export interface PaymentRow {
  payment_id: string | null;
  run_id: string | null;
  file_name: string | null;
  invoice_number: string | null;
  revision: number | null;
  vendor: string;
  amount_usd: Money;
  original_amount: Money | null;
  original_currency: string | null;
  kind: PaymentKind | null;
  delta_label: string | null;
  invoice_total_usd: Money | null;
  approved_by: string | null;
  paid_at: string;
  idempotency_key: string;
  batch_id: string | null;
  batch_trigger: BatchTrigger | null;
  batch_trigger_label: string | null;
  released_by: string | null;
}

export interface PaymentsResponse extends ListResponse<PaymentRow> {
  total_usd: Money;
}

export interface PaymentsFilter {
  date_from?: string;
  date_to?: string;
  vendor?: string;
}

export interface BatchRow {
  batch_id: string;
  trigger: BatchTrigger;
  trigger_label: string | null;
  released_by: string;
  started_at: string;
  finished_at: string | null;
  running: boolean;
  count: number;
  total_usd: Money;
  failed_count: number;
}

export interface LlmModel {
  provider: string;
  model: string;
}

export interface Stats {
  in_queue: number;
  processing: number;
  awaiting_review: number;
  payment_queue: number;
  paid_today: number;
  rejected_today: number;
  dollars_queued?: Money;
  dollars_paid?: Money;
  dollars_blocked?: Money;
  duplicates_caught?: number;
  /** `configured` is false while the API key for a provider in use is missing (`missing_key` names it). */
  llm: LlmModel & { roles?: Record<string, LlmModel>; configured: boolean; missing_key: string | null };
  server_time: string;
}

/** SSE event names sent by `GET /api/events` (plus `ready` on connect). */
export const EVENT_NAMES = [
  'invoice.created',
  'invoice.stage_changed',
  'invoice.resolved',
  'payment.queued',
  'payment.cancelled',
  'batch.started',
  'batch.finished',
  'payment.created',
  'settings.updated',
] as const;
export type EventName = (typeof EVENT_NAMES)[number];

export interface BatchFinishedEvent {
  batch_id: string;
  trigger: BatchTrigger;
  released_by: string;
  count: number;
  total_usd: Money;
  failed_count: number;
}

export interface PaymentQueuedEvent {
  row_id: number;
  run_id: string;
  invoice_number: string;
  kind: PaymentKind;
  amount_usd: Money;
  vendor: string;
}

export interface PaymentCancelledEvent {
  row_id: number;
  run_id: string;
  reason: string;
}
