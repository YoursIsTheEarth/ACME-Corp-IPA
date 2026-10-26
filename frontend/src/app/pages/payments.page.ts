import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { RouterLink } from '@angular/router';
import { Subject, debounceTime } from 'rxjs';

import { csvUrl } from '../core/api-client';
import { PaymentRow, PaymentsFilter } from '../core/api.models';
import { DetailDrawer } from '../core/drawer';
import { Stores } from '../core/live-store';
import { FORMAT_PIPES, foreign, sumMoney, usd } from '../shared/format';
import { CellDefDirective, InvoiceTableComponent, TableColumn } from '../shared/invoice-table/invoice-table.component';

/** F26: every payment made, with batch, trigger, who released it, and the filtered total. */
@Component({
  selector: 'app-payments-page',
  standalone: true,
  imports: [
    FormsModule,
    RouterLink,
    MatButtonModule,
    MatFormFieldModule,
    MatIconModule,
    MatInputModule,
    InvoiceTableComponent,
    CellDefDirective,
    ...FORMAT_PIPES,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="page">
      <header class="page-header">
        <div>
          <h1>Payments</h1>
          <p>Every payment sent, the batch that sent it, and the idempotency key that keeps it from being sent twice.</p>
        </div>
      </header>

      <div class="filters">
        <mat-form-field appearance="outline" subscriptSizing="dynamic">
          <mat-label>Vendor</mat-label>
          <input matInput [ngModel]="filter().vendor ?? ''" (ngModelChange)="vendor$.next($event)" data-testid="vendor-filter" />
        </mat-form-field>
        <mat-form-field appearance="outline" subscriptSizing="dynamic">
          <mat-label>Paid from</mat-label>
          <input matInput type="date" [ngModel]="filter().date_from ?? ''" (ngModelChange)="patch({ date_from: $event })" />
        </mat-form-field>
        <mat-form-field appearance="outline" subscriptSizing="dynamic">
          <mat-label>Paid to</mat-label>
          <input matInput type="date" [ngModel]="filter().date_to ?? ''" (ngModelChange)="patch({ date_to: $event })" />
        </mat-form-field>
      </div>

      <app-invoice-table
        [columns]="columns"
        [rows]="data()?.rows"
        noun="payments"
        emptyMessage="No payments match these filters."
        (filteredRowsChange)="visible.set($event)"
        (rowClick)="drawer.open($event.run_id)"
      >
        <a tableActions mat-stroked-button [href]="exportUrl()" download="payments.csv" data-testid="export-csv">
          <mat-icon>download</mat-icon> Export CSV
        </a>
        <ng-template appCell="invoice" let-row>
          <div class="stack">
            <a [routerLink]="['/audit']" [queryParams]="{ search: row.invoice_number }" data-testid="audit-link">
              {{ row.invoice_number }}{{ row.revision ? ' R' + row.revision : '' }}
            </a>
            <span class="muted small">{{ row.vendor }}</span>
          </div>
        </ng-template>
        <ng-template appCell="amount" let-row>
          <div class="stack nowrap" data-testid="amount-cell">
            <b>{{ row.amount_usd | usd }}</b>
            @if (row.original_currency && row.original_currency !== 'USD') {
              <span class="muted small" data-testid="original">{{ original(row) }}</span>
            }
            @if (row.delta_label) {
              <span class="small delta">{{ row.delta_label }} · revised total {{ row.invoice_total_usd | usd }}</span>
            }
          </div>
        </ng-template>
        <ng-template appCell="paid_at" let-row><span class="nowrap">{{ row.paid_at | when }}</span></ng-template>
        <ng-template appCell="idempotency_key" let-row><span class="mono">{{ row.idempotency_key }}</span></ng-template>
        <ng-template appCell="batch" let-row>
          <div class="stack nowrap"><span class="mono">{{ row.batch_id ?? '—' }}</span><span class="muted small">{{ row.batch_trigger_label }}</span></div>
        </ng-template>
        <ng-template appCell="payment_id" let-row><span class="mono">{{ row.payment_id }}</span></ng-template>

        <div tableFooter class="total" data-testid="payments-total">
          Total paid ({{ visible().length }} payment{{ visible().length === 1 ? '' : 's' }}): <b>{{ total() }}</b>
        </div>
      </app-invoice-table>
    </div>
  `,
  styles: `
    .total { font-size: 14px; padding: 8px 0; }
    .delta { color: #6a1b9a; }
  `,
})
export class PaymentsPage {
  private readonly store = inject(Stores).payments;
  readonly drawer = inject(DetailDrawer);
  readonly data = toSignal(this.store.data$);
  readonly filter = signal<PaymentsFilter>(this.store.params);
  readonly visible = signal<PaymentRow[]>([]);
  readonly total = computed(() => usd(sumMoney(this.visible().map((r) => r.amount_usd))));
  readonly exportUrl = computed(() => csvUrl('payments.csv', this.filter()));
  readonly vendor$ = new Subject<string>();

  readonly columns: TableColumn<PaymentRow>[] = [
    { key: 'payment_id', header: 'Payment ID', sortable: true },
    { key: 'invoice', header: 'Invoice # / Vendor', sortable: true, sortValue: (r) => r.invoice_number, searchText: (r) => `${r.invoice_number} ${r.vendor}` },
    {
      key: 'amount',
      header: 'Amount paid (USD)',
      sortable: true,
      sortValue: (r) => Number(r.amount_usd),
      searchText: (r) => `${r.amount_usd} ${r.original_currency ?? ''} ${r.delta_label ?? ''}`,
    },
    { key: 'approved_by', header: 'Approved by', sortable: true },
    { key: 'paid_at', header: 'Paid at', sortable: true, searchText: () => '' },
    { key: 'idempotency_key', header: 'Idempotency key' },
    { key: 'batch', header: 'Batch', sortable: true, sortValue: (r) => r.batch_id, searchText: (r) => `${r.batch_id} ${r.batch_trigger_label}` },
    { key: 'released_by', header: 'Released by', sortable: true },
  ];

  constructor() {
    this.vendor$.pipe(debounceTime(300)).subscribe((vendor) => this.patch({ vendor }));
  }

  original(row: PaymentRow): string {
    return foreign(row.original_amount, row.original_currency);
  }

  patch(change: Partial<PaymentsFilter>): void {
    const next = Object.fromEntries(Object.entries({ ...this.filter(), ...change }).filter(([, v]) => !!v)) as PaymentsFilter;
    this.filter.set(next);
    this.store.setParams(next);
  }
}
