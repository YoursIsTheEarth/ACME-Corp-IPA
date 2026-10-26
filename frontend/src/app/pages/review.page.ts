import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { MatButtonModule } from '@angular/material/button';
import { MatDialog } from '@angular/material/dialog';
import { MatIconModule } from '@angular/material/icon';
import { MatTooltipModule } from '@angular/material/tooltip';

import { ReviewDecision, ReviewRow } from '../core/api.models';
import { DetailDrawer } from '../core/drawer';
import { Stores } from '../core/live-store';
import { ReviewDecisionDialog, ReviewDialogData, decisionLabel } from '../dialogs/review-decision.dialog';
import { FORMAT_PIPES } from '../shared/format';
import { CellDefDirective, InvoiceTableComponent, TableColumn } from '../shared/invoice-table/invoice-table.component';

/** F25: invoices held for a person, with why and what the AI VP recommends. */
@Component({
  selector: 'app-review-page',
  standalone: true,
  imports: [MatButtonModule, MatIconModule, MatTooltipModule, InvoiceTableComponent, CellDefDirective, ...FORMAT_PIPES],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="page">
      <header class="page-header">
        <div>
          <h1>Invoice Elevated Review</h1>
          <p>The agents held these for a person. Your decision resumes the same workflow run.</p>
        </div>
      </header>
      <app-invoice-table
        [columns]="columns"
        [rows]="data()?.rows"
        noun="held invoices"
        emptyMessage="Nothing is waiting for review."
        (rowClick)="drawer.open($event.id)"
      >
        <ng-template appCell="invoice" let-row>
          <div class="stack">
            <b>{{ row.invoice_number ?? row.file_name }}</b>
            <span class="muted small">{{ row.vendor ?? '—' }}</span>
            <span class="small">{{ row.amount_usd | usd }}</span>
            @if (row.hold_kind === 'credit') {
              <span class="overpaid small" data-testid="overpaid">{{ row.overpaid_usd | usd }} overpaid</span>
            }
          </div>
        </ng-template>
        <ng-template appCell="why" let-row>
          @if (row.hold_kind === 'payment_failure') {
            <div class="stack"><b class="fail">Payment failed</b><span class="small">{{ row.last_error }}</span></div>
          } @else if (row.hold_kind === 'credit') {
            <div class="stack"><b>Revision lowers a paid total</b><span class="small muted">{{ row.reason }}</span></div>
          } @else {
            @for (f of row.findings; track $index) {
              <div><span class="finding-chip" [class]="'finding-chip ' + (f.severity ?? '').toLowerCase()">{{ f.code | finding }}</span>
              <span class="small">{{ f.message }}</span></div>
            } @empty {
              <span class="small">{{ row.reason }}</span>
            }
          }
        </ng-template>
        <ng-template appCell="ai" let-row>
          @if (row.ai_recommendation) {
            <div class="stack ai"><b>{{ row.ai_recommendation }}</b><span class="small clamp" [matTooltip]="row.ai_rationale">{{ row.ai_rationale }}</span></div>
          } @else {
            <span class="muted">—</span>
          }
        </ng-template>
        <ng-template appCell="waiting" let-row>
          <div class="stack nowrap"><span>{{ row.waiting_since | when }}</span><span class="muted small">{{ row.waiting_s | duration }}</span></div>
        </ng-template>
        <ng-template appCell="actions" let-row>
          <div class="actions">
            <button mat-flat-button type="button" (click)="decide(row, 'approve')" data-testid="approve">{{ label(row, 'approve') }}</button>
            <button mat-stroked-button type="button" class="reject" (click)="decide(row, 'reject')" data-testid="reject">{{ label(row, 'reject') }}</button>
            <button mat-button type="button" (click)="drawer.open(row.id)">View details</button>
          </div>
        </ng-template>
      </app-invoice-table>
    </div>
  `,
  styles: `
    .actions { display: flex; gap: 6px; flex-wrap: wrap; align-items: center; min-width: 260px; }
    .reject { color: #c62828; }
    .fail, .overpaid { color: #b71c1c; font-weight: 600; }
    .ai { max-width: 340px; }
    .clamp { display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
  `,
})
export class ReviewPage {
  private readonly dialog = inject(MatDialog);
  readonly drawer = inject(DetailDrawer);
  readonly data = toSignal(inject(Stores).review.data$);
  readonly label = decisionLabel;

  readonly columns: TableColumn<ReviewRow>[] = [
    {
      key: 'invoice',
      header: 'Invoice # / Vendor / Amount (USD)',
      sortable: true,
      sortValue: (r) => r.invoice_number,
      searchText: (r) => `${r.invoice_number ?? ''} ${r.vendor ?? ''} ${r.amount_usd ?? ''}`,
    },
    { key: 'why', header: "Why it's held", searchText: (r) => `${r.reason ?? ''} ${r.findings.map((f) => f.code).join(' ')}` },
    { key: 'ai', header: 'AI recommendation', sortable: true, sortValue: (r) => r.ai_recommendation, searchText: (r) => `${r.ai_recommendation} ${r.ai_rationale}` },
    { key: 'waiting', header: 'Waiting since', sortable: true, sortValue: (r) => r.waiting_since, searchText: () => '' },
    { key: 'actions', header: 'Actions', searchText: () => '' },
  ];

  decide(row: ReviewRow, decision: ReviewDecision): void {
    this.dialog.open<ReviewDecisionDialog, ReviewDialogData>(ReviewDecisionDialog, { data: { row, decision }, width: '600px' });
  }
}
