import { ChangeDetectionStrategy, Component, OnInit, computed, inject, signal } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
import { ActivatedRoute } from '@angular/router';

import { csvUrl } from '../core/api-client';
import { AuditFilter, AuditRow } from '../core/api.models';
import { DetailDrawer } from '../core/drawer';
import { Stores } from '../core/live-store';
import { RunTimelineComponent } from '../detail/run-timeline.component';
import { FORMAT_PIPES } from '../shared/format';
import {
  CellDefDirective,
  ExpandedRowDirective,
  InvoiceTableComponent,
  TableColumn,
} from '../shared/invoice-table/invoice-table.component';
import { StatusChipComponent } from '../shared/status-chip.component';

export const FINAL_STATUSES = ['Paid', 'Revised', 'Rejected', 'Duplicate', 'Superseded', 'Credit confirmed'];

/** F24: every resolved invoice, the reasoning behind it, and the rationale timeline per row. */
@Component({
  selector: 'app-audit-page',
  standalone: true,
  imports: [
    FormsModule,
    MatButtonModule,
    MatFormFieldModule,
    MatIconModule,
    MatInputModule,
    MatSelectModule,
    InvoiceTableComponent,
    CellDefDirective,
    ExpandedRowDirective,
    StatusChipComponent,
    RunTimelineComponent,
    ...FORMAT_PIPES,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="page">
      <header class="page-header">
        <div>
          <h1>Invoice Resolution Audit</h1>
          <p>Every finished invoice, who decided it, and why. Expand a row for the full rationale timeline.</p>
        </div>
      </header>

      <div class="filters">
        <mat-form-field appearance="outline" subscriptSizing="dynamic">
          <mat-label>Final status</mat-label>
          <mat-select [ngModel]="filter().status ?? ''" (ngModelChange)="patch({ status: $event })" data-testid="status-filter">
            <mat-option value="">All statuses</mat-option>
            @for (s of statuses; track s) {
              <mat-option [value]="s">{{ s }}</mat-option>
            }
          </mat-select>
        </mat-form-field>
        <mat-form-field appearance="outline" subscriptSizing="dynamic">
          <mat-label>Completed from</mat-label>
          <input matInput type="date" [ngModel]="filter().date_from ?? ''" (ngModelChange)="patch({ date_from: $event })" />
        </mat-form-field>
        <mat-form-field appearance="outline" subscriptSizing="dynamic">
          <mat-label>Completed to</mat-label>
          <input matInput type="date" [ngModel]="filter().date_to ?? ''" (ngModelChange)="patch({ date_to: $event })" />
        </mat-form-field>
        @if (filter().search) {
          <button mat-stroked-button type="button" (click)="patch({ search: '' })">
            Showing {{ filter().search }} <mat-icon iconPositionEnd>close</mat-icon>
          </button>
        }
        @if (hasFilter()) {
          <button mat-button type="button" (click)="reset()">Clear filters</button>
        }
      </div>

      <app-invoice-table
        [columns]="columns"
        [rows]="data()?.rows"
        noun="invoices"
        emptyMessage="No resolved invoices match these filters."
        (rowClick)="drawer.open($event.id)"
      >
        <a tableActions mat-stroked-button [href]="exportUrl()" download="invoices.csv" data-testid="export-csv">
          <mat-icon>download</mat-icon> Export CSV
        </a>
        <ng-template appCell="invoice" let-row>
          <div class="stack">
            <b>{{ row.invoice_number ?? row.file_name }}</b>
            <span class="muted small">{{ row.vendor ?? '—' }}</span>
            <span class="small">{{ row.amount_usd | usd }}</span>
          </div>
        </ng-template>
        <ng-template appCell="final_status" let-row><app-status-chip [status]="row.final_status" /></ng-template>
        <ng-template appCell="findings" let-row>
          @for (f of row.key_findings; track $index) {
            <span class="finding-chip" [class]="'finding-chip ' + (f.severity ?? '').toLowerCase()" [title]="f.message">{{ f.code | finding }}</span>
          }
          @if (row.findings_count > row.key_findings.length) {
            <span class="finding-chip more" data-testid="more-findings">+{{ row.findings_count - row.key_findings.length }}</span>
          }
          @if (!row.findings_count) {
            <span class="muted small">None</span>
          }
        </ng-template>
        <ng-template appCell="completed" let-row>
          <div class="stack nowrap"><span>{{ row.completed_at | when }}</span><span class="muted small">{{ row.processing_s | duration }} total</span></div>
        </ng-template>
        <ng-template appExpandedRow let-row>
          <app-run-timeline [invoiceId]="row.id" />
        </ng-template>
      </app-invoice-table>
    </div>
  `,
})
export class AuditPage implements OnInit {
  private readonly store = inject(Stores).audit;
  private readonly route = inject(ActivatedRoute);
  readonly drawer = inject(DetailDrawer);
  readonly statuses = FINAL_STATUSES;
  readonly data = toSignal(this.store.data$);
  readonly filter = signal<AuditFilter>(this.store.params);
  readonly exportUrl = computed(() => csvUrl('invoices.csv', this.filter()));
  readonly hasFilter = computed(() => Object.values(this.filter()).some((v) => !!v));

  readonly columns: TableColumn<AuditRow>[] = [
    {
      key: 'invoice',
      header: 'Invoice # / Vendor / Amount (USD)',
      sortable: true,
      sortValue: (r) => r.invoice_number ?? r.file_name,
      searchText: (r) => `${r.invoice_number ?? ''} ${r.vendor ?? ''} ${r.amount_usd ?? ''} ${r.file_name}`,
    },
    { key: 'final_status', header: 'Final status', sortable: true },
    { key: 'decided_by', header: 'Decided by', sortable: true },
    {
      key: 'findings',
      header: 'Key findings',
      sortable: true,
      sortValue: (r) => r.findings_count,
      searchText: (r) => r.key_findings.map((f) => `${f.code} ${f.code.replace(/_/g, ' ')}`).join(' '),
    },
    { key: 'completed', header: 'Completed', sortable: true, sortValue: (r) => r.completed_at, searchText: () => '' },
  ];

  ngOnInit(): void {
    const q = this.route.snapshot.queryParamMap;
    const fromUrl: AuditFilter = {};
    for (const key of ['status', 'date_from', 'date_to', 'search'] as const) {
      const v = q.get(key);
      if (v) fromUrl[key] = v;
    }
    if (Object.keys(fromUrl).length) this.apply(fromUrl);
  }

  patch(change: Partial<AuditFilter>): void {
    this.apply({ ...this.filter(), ...change });
  }

  reset(): void {
    this.apply({});
  }

  private apply(filter: AuditFilter): void {
    const clean = Object.fromEntries(Object.entries(filter).filter(([, v]) => !!v)) as AuditFilter;
    this.filter.set(clean);
    this.store.setParams(clean);
  }
}
