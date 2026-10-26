import { TestBed, discardPeriodicTasks, fakeAsync, tick } from '@angular/core/testing';
import { provideNoopAnimations } from '@angular/platform-browser/animations';
import { provideRouter } from '@angular/router';
import { BehaviorSubject, of } from 'rxjs';

import { ApiClient } from '../core/api-client';
import { PayeeThreshold, ReviewRow } from '../core/api.models';
import { PageVisibility } from '../core/live-store';
import { ReviewPage } from './review.page';

const SPLIT: PayeeThreshold = {
  total_usd: '29000.00', threshold_usd: '10000.00', window_days: 30, window_start: '2026-02-02', window_end: '2026-03-03',
  payees: ['Northwind Fabrication LLC'], message: 'Payee total $29,000.00 over 3 invoices in 30 days', triggered_by: 'run-1020',
  invoices: [
    { run_id: 'run-1018', invoice_number: 'INV-1018', invoice_date: '2026-02-02', vendor: 'Northwind Fabrication LLC', amount_usd: '9750.00', status: 'Awaiting review' },
    { run_id: 'run-1019', invoice_number: 'INV-1019', invoice_date: '2026-02-09', vendor: 'Northwind Fabrication LLC', amount_usd: '9500.00', status: 'Awaiting review' },
    { run_id: 'run-1020', invoice_number: 'INV-1020', invoice_date: '2026-02-16', vendor: 'Northwind Fabrication, LLC', amount_usd: '9750.00', status: 'Awaiting review' },
  ],
};

function row(number: string, partial: Partial<ReviewRow>): ReviewRow {
  return {
    id: `run-${number.slice(4)}`, file_name: `invoice_${number.slice(4)}.txt`, format: 'txt', invoice_number: number,
    vendor: 'Northwind Fabrication LLC', amount_usd: '9750.00', stage: 'Awaiting review', status: 'Awaiting review',
    final_status: null, decided_by: null, uploaded_at: '2026-10-26T14:00:00+00:00', completed_at: null,
    stage_entered_at: null, time_in_stage_s: 5, processing_s: null, hold_kind: 'warning', reason: 'held', detail: null,
    last_error: null, attempts: null,
    findings: [{ code: 'PAYEE_CUMULATIVE_THRESHOLD', severity: 'WARNING', message: SPLIT.message }],
    ai_recommendation: 'NEEDS_REVIEW', ai_rationale: 'Confirm the split with procurement.', overpaid_usd: null,
    paid_amount_usd: null, payee_threshold: SPLIT, pulled: false, waiting_since: null, waiting_s: 5, ...partial,
  };
}

describe('ReviewPage payee threshold holds', () => {
  beforeEach(() => {
    const rows = [
      row('INV-1018', { hold_kind: 'payee_threshold', reason: 'Payee cumulative threshold', pulled: true }),
      row('INV-1019', { amount_usd: '9500.00' }),
      row('INV-1020', {}),
      row('INV-1010', { payee_threshold: null, vendor: 'Consolidated Materials Group',
                        findings: [{ code: 'PRICE_VARIANCE', severity: 'WARNING', message: '+20%' }] }),
    ];
    TestBed.configureTestingModule({
      imports: [ReviewPage],
      providers: [
        provideNoopAnimations(),
        provideRouter([]),
        { provide: PageVisibility, useValue: { visible$: new BehaviorSubject(false) } },
        { provide: ApiClient, useValue: { review: () => of({ view: 'review', rows, count: rows.length, server_time: '' }) } },
      ],
    });
  });

  it('shows the payee total, window, and contributing invoices, and marks the pulled invoice', fakeAsync(() => {
    const fixture = TestBed.createComponent(ReviewPage);
    fixture.detectChanges();
    tick();
    fixture.detectChanges();
    const el: HTMLElement = fixture.nativeElement;
    const rows = Array.from(el.querySelectorAll('tr')).filter((tr) => tr.querySelector('b'));
    const byNumber = (n: string) => rows.find((tr) => tr.querySelector('b')!.textContent!.trim() === n)!;

    for (const number of ['INV-1018', 'INV-1019', 'INV-1020']) {
      const tr = byNumber(number);
      expect(tr.querySelector('[data-testid=payee-total]')!.textContent).toContain('Payee total $29,000.00 in 30 days');
      expect(tr.querySelector('[data-testid=payee-invoices]')!.textContent!.trim()).toBe('INV-1018, INV-1019, INV-1020');
    }
    const pulled = rows.filter((tr) => tr.querySelector('[data-testid=pulled]'));
    expect(pulled.length).toBe(1);
    expect(pulled[0]).toBe(byNumber('INV-1018'));
    expect(pulled[0].querySelector('[data-testid=pulled]')!.textContent!.trim()).toBe('Pulled from Payment Queue');
    expect(byNumber('INV-1010').querySelector('[data-testid=payee-total]')).toBeNull();
    discardPeriodicTasks();
  }));
});
