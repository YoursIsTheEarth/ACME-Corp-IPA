import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { MatIconModule } from '@angular/material/icon';

import { QueueRow } from '../core/api.models';
import { DetailDrawer } from '../core/drawer';
import { Stores } from '../core/live-store';
import { FORMAT_PIPES } from '../shared/format';
import { CellDefDirective, InvoiceTableComponent, TableColumn } from '../shared/invoice-table/invoice-table.component';
import { STAGES, StageStripComponent } from '../shared/stage-strip.component';
import { StatusChipComponent } from '../shared/status-chip.component';

/** F23: every invoice not yet resolved, with live stage updates. */
@Component({
  selector: 'app-queue-page',
  standalone: true,
  imports: [MatIconModule, InvoiceTableComponent, CellDefDirective, StageStripComponent, StatusChipComponent, ...FORMAT_PIPES],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="page">
      <header class="page-header">
        <div>
          <h1>Invoice Queue</h1>
          <p>Invoices moving through extraction, validation, and the approval decision. Resolved ones leave this list.</p>
        </div>
      </header>
      <app-invoice-table
        [columns]="columns"
        [rows]="data()?.rows"
        noun="invoices"
        emptyMessage="The queue is empty. Upload invoices on the Home page."
        (rowClick)="drawer.open($event.id)"
      >
        <ng-template appCell="file" let-row>
          <span class="file"><mat-icon>{{ row.format | fileIcon }}</mat-icon>{{ row.file_name }}</span>
        </ng-template>
        <ng-template appCell="invoice" let-row>
          @if (row.invoice_number || row.vendor) {
            <div class="stack"><b>{{ row.invoice_number ?? '—' }}</b><span class="muted small">{{ row.vendor ?? '—' }}</span></div>
          } @else {
            <span class="muted" data-testid="extracting">Extracting...</span>
          }
        </ng-template>
        <ng-template appCell="amount" let-row><span class="nowrap">{{ row.amount_usd | usd }}</span></ng-template>
        <ng-template appCell="stage" let-row><app-stage-strip [stage]="row.stage" /></ng-template>
        <ng-template appCell="status" let-row><app-status-chip [status]="row.status" /></ng-template>
        <ng-template appCell="uploaded" let-row>
          <div class="stack nowrap"><span>{{ row.uploaded_at | when }}</span><span class="muted small">{{ row.time_in_stage_s | duration }} in stage</span></div>
        </ng-template>
      </app-invoice-table>
    </div>
  `,
  styles: `.file { display: inline-flex; align-items: center; gap: 6px; } .file mat-icon { color: var(--ipa-muted); }`,
})
export class QueuePage {
  readonly drawer = inject(DetailDrawer);
  readonly data = toSignal(inject(Stores).queue.data$);
  readonly columns: TableColumn<QueueRow>[] = [
    { key: 'file', header: 'File', sortable: true, sortValue: (r) => r.file_name },
    {
      key: 'invoice',
      header: 'Invoice # / Vendor',
      sortable: true,
      sortValue: (r) => r.invoice_number,
      searchText: (r) => `${r.invoice_number ?? ''} ${r.vendor ?? ''}`,
    },
    { key: 'amount', header: 'Amount (USD)', sortable: true, sortValue: (r) => Number(r.amount_usd ?? -1), searchText: (r) => r.amount_usd },
    { key: 'stage', header: 'Stage', sortable: true, sortValue: (r) => STAGES.indexOf(r.stage as never), searchText: (r) => r.stage },
    { key: 'status', header: 'Status', sortable: true, sortValue: (r) => r.status },
    { key: 'uploaded', header: 'Uploaded / Time in stage', sortable: true, sortValue: (r) => r.uploaded_at, searchText: () => '' },
  ];
}
