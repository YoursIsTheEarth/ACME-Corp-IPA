import { HttpErrorResponse } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { AbstractControl, FormControl, FormGroup, ReactiveFormsModule, ValidationErrors } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MAT_DIALOG_DATA, MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';

import { ApiClient } from '../core/api-client';
import { ReviewDecision, ReviewRow } from '../core/api.models';
import { errorMessage } from '../core/http-errors';
import { StoreName, Stores } from '../core/live-store';
import { ToastService } from '../core/toast.service';
import { FORMAT_PIPES, usd } from '../shared/format';
import { ReviewerNameFieldComponent, rememberReviewerName } from '../shared/reviewer-name-field.component';

export const RATIONALE_MIN = 15;

export function rationaleValidator(control: AbstractControl): ValidationErrors | null {
  const length = String(control.value ?? '').trim().length;
  return length >= RATIONALE_MIN ? null : { minlength: { requiredLength: RATIONALE_MIN, actualLength: length } };
}

export interface ReviewDialogData {
  row: ReviewRow;
  decision: ReviewDecision;
}

export type ReviewDialogResult = { ok: true } | { ok: false; conflict: true } | undefined;

/** The four action labels: credit holds read Credit confirmed / Reject revision. */
export function decisionLabel(row: Pick<ReviewRow, 'hold_kind'>, decision: ReviewDecision): string {
  if (row.hold_kind === 'credit') return decision === 'approve' ? 'Credit confirmed' : 'Reject revision';
  return decision === 'approve' ? 'Approve' : 'Reject';
}

/** F25: summary, findings, AI recommendation, name, and rationale; sends `POST /api/invoices/{id}/review`. */
@Component({
  selector: 'app-review-decision-dialog',
  standalone: true,
  imports: [
    ReactiveFormsModule,
    MatDialogModule,
    MatButtonModule,
    MatFormFieldModule,
    MatInputModule,
    MatIconModule,
    MatProgressSpinnerModule,
    ReviewerNameFieldComponent,
    ...FORMAT_PIPES,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <h2 mat-dialog-title>{{ label }} {{ row.invoice_number ?? row.file_name }}</h2>
    <mat-dialog-content>
      <div class="summary">
        <span class="muted">Vendor</span><span>{{ row.vendor ?? '—' }}</span>
        <span class="muted">Amount</span><span>{{ row.amount_usd | usd }}</span>
        @if (credit) {
          <span class="muted">Overpaid</span><b class="overpaid">{{ row.overpaid_usd | usd }} overpaid</b>
        }
        <span class="muted">Why held</span><span>{{ row.reason }}</span>
        @if (row.last_error) {
          <span class="muted">Last error</span><span>{{ row.last_error }}</span>
        }
      </div>
      @if (row.findings.length) {
        <div class="findings">
          @for (f of row.findings; track $index) {
            <div><span class="finding-chip" [class]="'finding-chip ' + (f.severity ?? '').toLowerCase()">{{ f.code | finding }}</span> {{ f.message }}</div>
          }
        </div>
      }
      @if (row.ai_recommendation) {
        <div class="ai"><mat-icon inline>smart_toy</mat-icon> <b>AI recommends {{ row.ai_recommendation }}</b>: {{ row.ai_rationale }}</div>
      }

      <form [formGroup]="form" (ngSubmit)="submit()" id="review-form">
        <app-reviewer-name-field formControlName="reviewer" label="Your name" />
        <mat-form-field appearance="outline" class="full">
          <mat-label>Rationale</mat-label>
          <textarea matInput formControlName="rationale" rows="3" data-testid="rationale"></textarea>
          <mat-hint>{{ hint }}</mat-hint>
          @if (form.controls.rationale.hasError('minlength')) {
            <mat-error>Write at least {{ min }} characters ({{ form.controls.rationale.value.trim().length }} so far)</mat-error>
          }
        </mat-form-field>
      </form>

      @if (conflict()) {
        <div class="banner warn" data-testid="conflict">Already decided by someone else. The list has been refreshed.</div>
      } @else if (error()) {
        <div class="banner error" data-testid="error">{{ error() }}</div>
      }
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      <button mat-button type="button" [mat-dialog-close]="conflict() ? { ok: false, conflict: true } : undefined">
        {{ conflict() ? 'Close' : 'Cancel' }}
      </button>
      @if (!conflict()) {
        <button
          mat-flat-button
          type="submit"
          form="review-form"
          [class.danger]="decision === 'reject'"
          [disabled]="form.invalid || busy()"
          data-testid="confirm"
        >
          @if (busy()) { <mat-spinner diameter="18" /> }
          {{ label }}
        </button>
      }
    </mat-dialog-actions>
  `,
  styles: `
    .full { width: 100%; }
    .findings { margin-bottom: 12px; font-size: 13px; }
    .ai { margin-bottom: 16px; padding: 8px 12px; border-radius: 8px; background: #eef4fd; font-size: 13px; }
    .overpaid { color: #b71c1c; }
    .banner { padding: 8px 12px; border-radius: 8px; margin-top: 4px; }
    .banner.warn { background: #fff4e0; color: #8a5a00; }
    .banner.error { background: #fdecea; color: #a61b1b; }
    .danger { --mdc-filled-button-container-color: #c62828; }
    mat-spinner { display: inline-block; margin-right: 6px; vertical-align: middle; }
    mat-dialog-content { max-width: 560px; }
  `,
})
export class ReviewDecisionDialog {
  private readonly api = inject(ApiClient);
  private readonly stores = inject(Stores);
  private readonly toast = inject(ToastService);
  private readonly ref = inject(MatDialogRef<ReviewDecisionDialog, ReviewDialogResult>);
  private readonly data = inject<ReviewDialogData>(MAT_DIALOG_DATA);

  readonly row = this.data.row;
  readonly decision = this.data.decision;
  readonly credit = this.row.hold_kind === 'credit';
  readonly label = decisionLabel(this.row, this.decision);
  readonly min = RATIONALE_MIN;
  readonly hint = this.credit
    ? `Record the credit note or refund the vendor agreed to and its amount (e.g. "Credit note CN-88 for ${usd(this.row.overpaid_usd)}").`
    : `At least ${RATIONALE_MIN} characters; this goes in the audit trail.`;

  readonly form = new FormGroup({
    reviewer: new FormControl('', { nonNullable: true }),
    rationale: new FormControl('', { nonNullable: true, validators: rationaleValidator }),
  });
  readonly busy = signal(false);
  readonly error = signal<string | null>(null);
  readonly conflict = signal(false);

  submit(): void {
    if (this.form.invalid || this.busy()) return;
    const reviewer = this.form.controls.reviewer.value.trim();
    const rationale = this.form.controls.rationale.value.trim();
    this.busy.set(true);
    this.error.set(null);
    this.api.submitReview(this.row.id, { decision: this.decision, reviewer, rationale }).subscribe({
      next: () => {
        rememberReviewerName(reviewer);
        // A credit decision pays nothing, so the payment queue is not refreshed for it.
        const affected: StoreName[] = this.credit
          ? ['review', 'queue', 'audit', 'stats']
          : ['review', 'queue', 'paymentQueue', 'audit', 'stats'];
        this.stores.refresh(...affected);
        this.toast.show(this.successMessage(reviewer));
        this.ref.close({ ok: true });
      },
      error: (err: unknown) => {
        this.busy.set(false);
        if (err instanceof HttpErrorResponse && err.status === 409) {
          this.conflict.set(true);
          this.stores.refresh('review', 'queue', 'stats');
        } else {
          this.error.set(errorMessage(err));
        }
      },
    });
  }

  private successMessage(reviewer: string): string {
    const name = this.row.invoice_number ?? this.row.file_name;
    if (this.credit) {
      return this.decision === 'approve'
        ? `${name}: credit confirmed by ${reviewer}. Nothing will be paid.`
        : `${name}: revision rejected by ${reviewer}. Nothing will be paid.`;
    }
    if (this.row.hold_kind === 'payment_failure' && this.decision === 'approve') {
      return `${name} requeued for payment by ${reviewer}.`;
    }
    return this.decision === 'approve'
      ? `${name} approved by ${reviewer}; it is now in the Payment Queue.`
      : `${name} rejected by ${reviewer}.`;
  }
}
