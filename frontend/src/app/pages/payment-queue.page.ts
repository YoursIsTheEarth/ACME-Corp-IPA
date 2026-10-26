import { ChangeDetectionStrategy, Component, ViewChild, computed, inject, signal } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { MatButtonModule } from '@angular/material/button';
import { MatDialog } from '@angular/material/dialog';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressBarModule } from '@angular/material/progress-bar';

import { PaymentKind, PaymentQueueRow } from '../core/api.models';
import { DetailDrawer } from '../core/drawer';
import { Stores } from '../core/live-store';
import { PayConfirmDialog, PayDialogData, PayScope } from '../dialogs/pay-confirm.dialog';
import { FORMAT_PIPES } from '../shared/format';
import { CellDefDirective, InvoiceTableComponent, TableColumn } from '../shared/invoice-table/invoice-table.component';
import { StatusChipComponent } from '../shared/status-chip.component';

export const KIND_LABELS: Record<PaymentKind, string> = {
  full: 'Full invoice',
  replacement: 'Revision replacing original',
  delta: 'Revision delta',
};

/** F40: approved invoices waiting to be paid, and the controls that release them. */
@Component({
  selector: 'app-payment-queue-page',
  standalone: true,
  imports: [
    MatButtonModule,
    MatIconModule,
    MatProgressBarModule,
    InvoiceTableComponent,
    CellDefDirective,
    StatusChipComponent,
    ...FORMAT_PIPES,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="page">
      <header class="page-header">
        <div>
          <h1>Payment Queue</h1>
          <p>Approved invoices wait here until a batch pays them. Every release records who clicked Pay.</p>
        </div>
      </header>

      <section class="cards" data-testid="pq-header">
        <div class="card"><span class="l">Queued</span><span class="n" data-testid="pq-count">{{ data()?.count ?? '—' }}</span></div>
        <div class="card"><span class="l">Total</span><span class="n" data-testid="pq-total">{{ data()?.total_usd | usd }}</span></div>
        <div class="card"><span class="l">Next scheduled batch</span><span class="n sm" data-testid="pq-next">{{ data()?.next_batch_label ?? '—' }}</span></div>
        <div class="card">
          <span class="l">Auto-pay on idle</span>
          <span class="n sm" data-testid="pq-idle">
            @if (data(); as d) {
              {{ d.auto_idle ? 'On' : 'Off' }}
              @if (d.auto_idle) { <span class="muted small">after {{ d.idle_delay_s }}s idle</span> }
            } @else { — }
          </span>
        </div>
      </section>

      @if (running()) {
        <div class="running" data-testid="batch-running">
          <mat-progress-bar mode="indeterminate" />
          <span>A payment batch is running. Pay controls are disabled until it finishes.</span>
        </div>
      }

      <app-invoice-table
        #table
        [columns]="columns"
        [rows]="data()?.rows"
        [selectable]="true"
        [canSelect]="canPay"
        noun="payments"
        emptyMessage="Nothing is waiting to be paid."
        (selectionChange)="selection.set($event)"
        (rowClick)="drawer.open($event.run_id)"
      >
        <ng-container tableActions>
          <button mat-stroked-button type="button" [disabled]="!selection().length || running()" (click)="pay('selected', selection())" data-testid="pay-selected">
            Pay selected{{ selection().length ? ' (' + selection().length + ')' : '' }}
          </button>
          <button mat-flat-button type="button" [disabled]="!payable().length || running()" (click)="pay('all', payable())" data-testid="pay-all">
            <mat-icon>payments</mat-icon> Pay all
          </button>
        </ng-container>
        <ng-template appCell="invoice" let-row>
          <div class="stack">
            <a class="link" (click)="drawer.open(row.run_id)">{{ row.invoice_number }}{{ row.revision ? ' R' + row.revision : '' }}</a>
            <span class="muted small">{{ row.vendor }}</span>
          </div>
        </ng-template>
        <ng-template appCell="amount" let-row><span class="nowrap">{{ row.amount_usd | usd }}</span></ng-template>
        <ng-template appCell="kind" let-row>{{ kindLabel(row.kind) }}</ng-template>
        <ng-template appCell="queued_at" let-row><span class="nowrap">{{ row.queued_at | when }}</span></ng-template>
        <ng-template appCell="status" let-row>
          <div class="stack">
            <app-status-chip [status]="row.status" />
            @if (row.status === 'failed' && row.last_error) {
              <span class="small fail" data-testid="row-error">{{ row.last_error }} · retried next batch</span>
            }
          </div>
        </ng-template>
        <ng-template appCell="action" let-row>
          <button mat-stroked-button type="button" [disabled]="!canPay(row) || running()" (click)="pay('one', [row])" data-testid="pay-now">Pay now</button>
        </ng-template>
      </app-invoice-table>
    </div>
  `,
  styles: `
    .cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; margin-bottom: 16px; }
    .card { display: flex; flex-direction: column; gap: 4px; padding: 14px 18px; border-radius: 12px; background: var(--ipa-surface); border: 1px solid var(--ipa-border); }
    .l { color: var(--ipa-muted); font-size: 13px; }
    .n { font-size: 24px; font-weight: 700; }
    .n.sm { font-size: 17px; }
    .running { display: flex; flex-direction: column; gap: 6px; margin-bottom: 12px; padding: 10px 14px; border-radius: 8px; background: #e0f7fa; }
    .fail { color: #b71c1c; }
    .link { cursor: pointer; font-weight: 600; }
  `,
})
export class PaymentQueuePage {
  private readonly dialog = inject(MatDialog);
  readonly drawer = inject(DetailDrawer);
  readonly data = toSignal(inject(Stores).paymentQueue.data$);
  readonly selection = signal<PaymentQueueRow[]>([]);
  readonly running = computed(() => !!this.data()?.batch_running || !!this.data()?.rows.some((r) => r.status === 'paying'));
  readonly payable = computed(() => (this.data()?.rows ?? []).filter((r) => this.canPay(r)));
  @ViewChild('table') table?: InvoiceTableComponent<PaymentQueueRow>;

  readonly canPay = (row: PaymentQueueRow) => row.status !== 'paying';
  readonly kindLabel = (kind: PaymentKind) => KIND_LABELS[kind] ?? kind;

  readonly columns: TableColumn<PaymentQueueRow>[] = [
    { key: 'invoice', header: 'Invoice # / Vendor', sortable: true, sortValue: (r) => r.invoice_number, searchText: (r) => `${r.invoice_number} ${r.vendor}` },
    { key: 'amount', header: 'Amount (USD)', sortable: true, sortValue: (r) => Number(r.amount_usd), searchText: (r) => r.amount_usd },
    { key: 'kind', header: 'Type', sortable: true, searchText: (r) => KIND_LABELS[r.kind] },
    { key: 'approved_by', header: 'Approved by', sortable: true },
    { key: 'queued_at', header: 'Queued at', sortable: true, searchText: () => '' },
    { key: 'status', header: 'Status', sortable: true, searchText: (r) => `${r.status} ${r.last_error ?? ''}` },
    { key: 'action', header: 'Action', searchText: () => '' },
  ];

  pay(scope: PayScope, rows: PaymentQueueRow[]): void {
    if (!rows.length) return;
    this.dialog
      .open<PayConfirmDialog, PayDialogData>(PayConfirmDialog, { data: { scope, rows }, width: '480px' })
      .afterClosed()
      .subscribe((res) => res && this.table?.clearSelection());
  }
}
