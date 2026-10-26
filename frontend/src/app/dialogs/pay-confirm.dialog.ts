import { HttpErrorResponse } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { FormControl, ReactiveFormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MAT_DIALOG_DATA, MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';

import { ApiClient } from '../core/api-client';
import { ExecuteRequest, ExecuteResponse, PaymentQueueRow } from '../core/api.models';
import { errorMessage } from '../core/http-errors';
import { Stores } from '../core/live-store';
import { ToastService } from '../core/toast.service';
import { sumMoney, usd } from '../shared/format';
import { ReviewerNameFieldComponent, rememberReviewerName } from '../shared/reviewer-name-field.component';

export type PayScope = 'all' | 'selected' | 'one';

export interface PayDialogData {
  scope: PayScope;
  rows: PaymentQueueRow[];
}

const TITLES: Record<PayScope, string> = { all: 'Pay all', selected: 'Pay selected', one: 'Pay now' };

/** F40: row count, total, and the releaser's name; sends `POST /api/payment-queue/execute`. */
@Component({
  selector: 'app-pay-confirm-dialog',
  standalone: true,
  imports: [ReactiveFormsModule, MatDialogModule, MatButtonModule, MatProgressSpinnerModule, ReviewerNameFieldComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <h2 mat-dialog-title>{{ title }}</h2>
    <mat-dialog-content>
      <p class="lead" data-testid="pay-summary">
        Release <b>{{ rows.length }} payment{{ rows.length === 1 ? '' : 's' }}</b> totalling <b>{{ total }}</b>?
      </p>
      @if (data.scope === 'one') {
        <p class="muted">{{ rows[0].invoice_number }} · {{ rows[0].vendor }}</p>
      }
      <app-reviewer-name-field [formControl]="name" label="Released by (your name)" />
      @if (conflict()) {
        <div class="banner warn" data-testid="conflict">A batch is already running. Wait for it to finish, then try again.</div>
      } @else if (error()) {
        <div class="banner error" data-testid="error">{{ error() }}</div>
      }
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      <button mat-button type="button" mat-dialog-close>{{ conflict() ? 'Close' : 'Cancel' }}</button>
      @if (!conflict()) {
        <button mat-flat-button type="button" (click)="confirm()" [disabled]="name.invalid || busy()" data-testid="confirm">
          @if (busy()) { <mat-spinner diameter="18" /> }
          Pay {{ total }}
        </button>
      }
    </mat-dialog-actions>
  `,
  styles: `
    .lead { font-size: 15px; }
    .banner { padding: 8px 12px; border-radius: 8px; }
    .banner.warn { background: #fff4e0; color: #8a5a00; }
    .banner.error { background: #fdecea; color: #a61b1b; }
    mat-spinner { display: inline-block; margin-right: 6px; vertical-align: middle; }
  `,
})
export class PayConfirmDialog {
  private readonly api = inject(ApiClient);
  private readonly stores = inject(Stores);
  private readonly toast = inject(ToastService);
  private readonly ref = inject(MatDialogRef<PayConfirmDialog, ExecuteResponse>);
  readonly data = inject<PayDialogData>(MAT_DIALOG_DATA);

  readonly rows = this.data.rows;
  readonly title = TITLES[this.data.scope];
  readonly total = usd(sumMoney(this.rows.map((r) => r.amount_usd)));
  readonly name = new FormControl('', { nonNullable: true });
  readonly busy = signal(false);
  readonly error = signal<string | null>(null);
  readonly conflict = signal(false);

  request(): ExecuteRequest {
    const released_by = this.name.value.trim();
    // Pay all omits ids (the backend rejects an empty list).
    return this.data.scope === 'all' ? { released_by } : { ids: this.rows.map((r) => r.id), released_by };
  }

  confirm(): void {
    if (this.name.invalid || this.busy()) return;
    const body = this.request();
    this.busy.set(true);
    this.error.set(null);
    this.api.executeBatch(body).subscribe({
      next: (res) => {
        rememberReviewerName(body.released_by);
        this.stores.refresh('paymentQueue', 'batches', 'stats');
        this.toast.show(`Batch ${res.batch_id} started by ${res.released_by}: paying ${this.rows.length} row(s).`);
        this.ref.close(res);
      },
      error: (err: unknown) => {
        this.busy.set(false);
        if (err instanceof HttpErrorResponse && err.status === 409) {
          this.conflict.set(true);
          this.stores.refresh('paymentQueue');
        } else {
          this.error.set(errorMessage(err));
        }
      },
    });
  }
}
