import { ChangeDetectionStrategy, Component, computed, inject, input } from '@angular/core';
import { toObservable, toSignal } from '@angular/core/rxjs-interop';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { catchError, filter, of, switchMap } from 'rxjs';

import { ApiClient } from '../core/api-client';
import { InvoiceDetail, TimelineEntry } from '../core/api.models';
import { findingLabel, usd, when } from '../shared/format';

export interface TimelineItem {
  ts: string;
  stage: string;
  icon: string;
  title: string;
  lines: string[];
  model: string | null;
}

const STAGES: Record<string, { label: string; icon: string }> = {
  ingestion: { label: 'Extraction', icon: 'document_scanner' },
  normalizer: { label: 'Normalization', icon: 'tune' },
  validation: { label: 'Validation', icon: 'rule' },
  approval: { label: 'Approval', icon: 'gavel' },
  critic: { label: 'Critic', icon: 'rate_review' },
  review: { label: 'Reviewer', icon: 'person' },
  disposition: { label: 'Disposition', icon: 'flag' },
  payments: { label: 'Payment', icon: 'payments' },
  payment: { label: 'Payment', icon: 'payments' },
};

function text(value: unknown): string {
  if (value === null || value === undefined) return '';
  return typeof value === 'string' ? value : JSON.stringify(value);
}

function evidence(e: Record<string, unknown> | undefined): string {
  if (!e || !Object.keys(e).length) return '';
  return ' (' + Object.entries(e).map(([k, v]) => `${k}: ${text(v)}`).join(', ') + ')';
}

/** Turns one audit-ledger entry into a readable line; unknown events fall back to their payload. */
export function describe(entry: TimelineEntry): TimelineItem {
  const p = entry.payload ?? {};
  const stage = STAGES[entry.agent ?? ''] ?? { label: entry.agent ?? 'System', icon: 'radio_button_checked' };
  const model = p['provider'] ? `${p['provider']} · ${p['model'] ?? ''}` : null;
  const item: TimelineItem = { ts: entry.ts, stage: stage.label, icon: stage.icon, title: entry.event, lines: [], model };
  switch (entry.event) {
    case 'extraction_attempt':
      item.title = `Extraction attempt ${p['attempt']}: ${p['outcome']}`;
      if (p['errors']?.length) item.lines = p['errors'].map(text);
      if (p['error']) item.lines.push(text(p['error']));
      break;
    case 'ingestion.result':
      item.title = `Extracted from ${String(p['format'] ?? '').toUpperCase()} in ${p['attempts']} attempt(s)`;
      if (p['retries']) item.lines.push(`${p['retries']} retr${p['retries'] === 1 ? 'y' : 'ies'}`);
      for (const e of p['errors'] ?? []) item.lines.push(text(e));
      break;
    case 'normalized': {
      item.title = 'Fields normalized';
      for (const m of p['sku_matches'] ?? []) {
        if (m.method !== 'exact') item.lines.push(`“${m.raw_name}” matched ${m.sku ?? 'nothing'} (${m.method})`);
      }
      break;
    }
    case 'validation.tool_calls':
      item.title = `Validation round ${p['round']}`;
      item.lines = [`Tools: ${(p['tools'] ?? []).join(', ')}`];
      break;
    case 'validation.summary':
      item.title = 'Validation summary';
      item.lines = [text(p['summary'])];
      break;
    case 'validation.findings':
    case 'validation.fallback': {
      const findings = p['findings'] ?? [];
      item.title = findings.length ? `${findings.length} finding(s)` : 'No findings';
      item.lines = findings.map(
        (f: any) => `${f.severity ?? ''} ${findingLabel(f.code)}: ${f.message ?? ''}${evidence(f.evidence)}`.trim(),
      );
      break;
    }
    case 'approval.policy':
      item.title = `Rules fired: ${(p['rules'] ?? []).join(', ') || 'none'}`;
      item.lines = [`Policy floor ${p['floor']}${p['vp_scrutiny'] ? ' · VP scrutiny (over threshold)' : ''}${p['fraud'] ? ' · fraud' : ''}`];
      break;
    case 'approval.draft':
      item.title = `AI VP draft (round ${p['round'] ?? 0}): ${p['draft']?.outcome ?? ''}`;
      item.lines = [text(p['draft']?.rationale)];
      break;
    case 'approval.critique': {
      const c = p['critique'] ?? {};
      item.stage = 'Critic';
      item.icon = 'rate_review';
      item.title = `Critic response (round ${p['round'] ?? 0}): ${c.verdict ?? c.outcome ?? (c.approved ? 'accepted' : 'revise')}`;
      item.lines = [c.feedback, c.rationale, c.critique, ...(c.issues ?? [])].filter(Boolean).map(text);
      if (!item.lines.length) item.lines = [text(c)];
      break;
    }
    case 'approval.decision':
      item.title = `Decision: ${p['decision']?.outcome ?? ''}`;
      item.lines = [text(p['decision']?.rationale)];
      break;
    case 'review.enqueued': {
      const payee = p['details']?.['payee_threshold'];
      item.title = p['update'] ? 'Hold updated' : 'Held for a person';
      item.lines = [text(p['reason'])];
      if (payee) item.lines.push(`Payee total ${usd(payee['total'])}: ${(payee['invoices'] ?? []).map((i: any) => i.invoice_number).join(', ')}`);
      break;
    }
    case 'finding.retroactive': {
      const trigger = p['triggered_by'] ?? {};
      item.title = 'Flagged after resolution';
      item.lines = [
        `${findingLabel(p['finding']?.code)}: payee total ${usd(p['total'])}, raised by ${trigger['invoice_number'] ?? trigger['run_id'] ?? 'a later invoice'}`,
        text(p['finding']?.message),
      ];
      break;
    }
    case 'disposition.outcome':
      item.title = `Outcome: ${p['final_status'] ?? p['status'] ?? p['outcome']}`;
      item.lines = [`Decided by ${p['decided_by'] ?? '—'}`];
      break;
    case 'rejection.recorded':
      item.title = `Rejection logged: ${p['final_status'] ?? 'Rejected'}`;
      item.lines = [text(p['rationale'])];
      break;
    case 'invoice.superseded':
      item.title = 'Superseded by revision';
      item.lines = [text(p['finding']?.message)];
      break;
    case 'payment.queued':
      item.title = `Queued for payment: ${usd(p['amount_usd'])} (${p['kind']})`;
      break;
    case 'payment.created':
    case 'payment.paid':
      item.title = `Paid ${usd(p['amount_usd'])}${p['batch_id'] ? ' in ' + p['batch_id'] : ''}`;
      item.lines = [p['payment_id'] ? `Payment ${p['payment_id']}` : '', p['idempotency_key'] ? `Key ${p['idempotency_key']}` : ''].filter(Boolean);
      break;
    default: {
      if (entry.event.startsWith('review')) {
        item.stage = 'Reviewer';
        item.icon = 'person';
        item.title = `${p['reviewer'] ?? 'Reviewer'}: ${p['decision'] ?? entry.event}`;
        item.lines = [text(p['rationale'])].filter(Boolean);
      } else {
        item.title = entry.event.replace(/[._]/g, ' ');
        const rest = Object.entries(p).filter(([k]) => k !== 'provider' && k !== 'model');
        item.lines = rest.length ? [rest.map(([k, v]) => `${k}: ${text(v)}`).join(' · ')] : [];
      }
    }
  }
  item.lines = item.lines.filter(Boolean);
  return item;
}

/** The rationale timeline: one entry per stage from the audit ledger (Audit rows and the drawer). */
@Component({
  selector: 'app-run-timeline',
  standalone: true,
  imports: [MatIconModule, MatProgressBarModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (!source()) {
      <mat-progress-bar mode="indeterminate" />
    } @else {
      @if (reviews().length) {
        @for (r of reviews(); track r.decided_at) {
          <div class="review-note" data-testid="review-note">
            <mat-icon inline>person</mat-icon>
            <b>{{ r.reviewer }}</b> chose <b>{{ r.decision }}</b>: “{{ r.rationale }}”
          </div>
        }
      }
      <ol class="timeline" data-testid="timeline">
        @for (item of items(); track $index) {
          <li>
            <mat-icon class="icon">{{ item.icon }}</mat-icon>
            <div class="body">
              <div class="head">
                <span class="stage">{{ item.stage }}</span>
                <span class="title">{{ item.title }}</span>
                <span class="ts">{{ fmt(item.ts) }}</span>
              </div>
              @for (line of item.lines; track $index) {
                <div class="line">{{ line }}</div>
              }
              @if (item.model) {
                <div class="model">{{ item.model }}</div>
              }
            </div>
          </li>
        } @empty {
          <li class="muted">No audit entries yet.</li>
        }
      </ol>
    }
  `,
  styles: `
    .timeline { list-style: none; margin: 8px 0 0; padding: 0; }
    li { display: flex; gap: 12px; padding: 8px 0; border-left: 2px solid var(--ipa-border); margin-left: 11px; padding-left: 16px; position: relative; }
    .icon { position: absolute; left: -13px; top: 8px; background: var(--ipa-subtle); color: var(--ipa-accent); font-size: 20px; width: 24px; height: 24px; text-align: center; }
    .body { flex: 1; min-width: 0; }
    .head { display: flex; flex-wrap: wrap; gap: 8px; align-items: baseline; }
    .stage { font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: .5px; color: var(--ipa-muted); }
    .title { font-weight: 600; }
    .ts { margin-left: auto; font-size: 12px; color: var(--ipa-muted); }
    .line { font-size: 13px; margin-top: 2px; overflow-wrap: anywhere; }
    .model { display: inline-block; margin-top: 4px; font-size: 11px; padding: 0 6px; border-radius: 4px; background: #eef1f6; color: #455a64; font-family: ui-monospace, monospace; }
    .review-note { margin: 8px 0; padding: 8px 12px; border-radius: 8px; background: #fff8e1; }
  `,
})
export class RunTimelineComponent {
  private readonly api = inject(ApiClient);
  /** Pass the loaded detail, or just the id to fetch it. */
  readonly detail = input<InvoiceDetail | null>(null);
  readonly invoiceId = input<string | null>(null);

  private readonly fetched = toSignal(
    toObservable(this.invoiceId).pipe(
      filter((id): id is string => !!id),
      switchMap((id) => this.api.invoice(id).pipe(catchError(() => of(null)))),
    ),
    { initialValue: null },
  );
  readonly source = computed(() => this.detail() ?? this.fetched());
  readonly items = computed(() => (this.source()?.timeline ?? []).map(describe));
  readonly reviews = computed(() => this.source()?.reviews ?? []);
  readonly fmt = when;
}
