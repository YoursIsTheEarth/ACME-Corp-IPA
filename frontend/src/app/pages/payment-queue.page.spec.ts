import { TestBed, discardPeriodicTasks, fakeAsync, tick } from '@angular/core/testing';
import { provideNoopAnimations } from '@angular/platform-browser/animations';
import { provideRouter } from '@angular/router';
import { BehaviorSubject, of } from 'rxjs';

import { ApiClient } from '../core/api-client';
import { PaymentQueueResponse, PaymentQueueRow } from '../core/api.models';
import { PageVisibility } from '../core/live-store';
import { PaymentQueuePage, paymentMode } from './payment-queue.page';

const FAILED: PaymentQueueRow = {
  id: 1, run_id: 'run-1', file_name: 'invoice_1001.txt', invoice_number: 'INV-1001', revision: 0, vendor: 'Widgets Inc.',
  amount_usd: '5000.00', kind: 'full', approved_by: 'Auto (rules)', queued_at: '2026-10-26T14:00:00+00:00',
  status: 'failed', attempts: 1, last_error: 'PaymentError: bank timeout', batch_id: 'B-0001',
};

function queue(partial: Partial<PaymentQueueResponse>): PaymentQueueResponse {
  return {
    rows: [], count: 0, total_usd: '0.00', delay_payments: true, pay_at_end_of_day: false, next_batch_at: null,
    next_batch_label: null, timezone: 'America/Chicago', pay_when_queue_empty: true, idle_delay_s: 60,
    batch_running: false, server_time: '', ...partial,
  };
}

describe('PaymentQueuePage header', () => {
  let response: PaymentQueueResponse;

  function render() {
    const fixture = TestBed.createComponent(PaymentQueuePage);
    fixture.detectChanges();
    tick();
    fixture.detectChanges();
    const el: HTMLElement = fixture.nativeElement;
    return (testid: string) => el.querySelector(`[data-testid=${testid}]`) as HTMLElement | null;
  }

  beforeEach(() => {
    TestBed.configureTestingModule({
      imports: [PaymentQueuePage],
      providers: [
        provideNoopAnimations(),
        provideRouter([]),
        { provide: PageVisibility, useValue: { visible$: new BehaviorSubject(false) } },
        { provide: ApiClient, useValue: { paymentQueue: () => of(response) } },
      ],
    });
  });

  it('delay on: shows the next end-of-day batch, pay when queue empty, and a link to Admin', fakeAsync(() => {
    response = queue({ pay_at_end_of_day: true, next_batch_at: '2026-10-26T17:00:00-05:00', next_batch_label: 'Today 5:00 PM CT' });
    const q = render();
    expect(q('pq-next')!.textContent).toContain('Today 5:00 PM CT');
    expect(q('pq-idle')!.textContent).toContain('On');
    expect(q('pq-mode')).toBeNull();
    expect(q('pq-admin-link')!.getAttribute('href')).toBe('/admin');
    expect(q('pq-mode-sentence')!.textContent).toContain('at end of day (next: Today 5:00 PM CT) or when the Invoice Queue is empty');
    discardPeriodicTasks();
  }));

  it('delay on with the defaults: no end-of-day batch scheduled', fakeAsync(() => {
    response = queue({});
    const q = render();
    expect(q('pq-next')!.textContent).toContain('No end-of-day batch');
    expect(q('pq-mode-sentence')!.textContent).toBe('Queued invoices are paid when the Invoice Queue is empty.');
    discardPeriodicTasks();
  }));

  it('delay off: says payments are made at approval, no next batch, Pay controls still there', fakeAsync(() => {
    response = queue({ delay_payments: false, rows: [FAILED], count: 1, total_usd: '5000.00' });
    const q = render();
    expect(q('pq-mode')!.textContent).toContain('Paid at approval');
    expect(q('pq-next')).toBeNull();
    expect(q('pq-idle')).toBeNull();
    expect(q('pq-mode-sentence')!.textContent).toBe('Payments are made at approval.');
    expect(q('pq-admin-link')!.getAttribute('href')).toBe('/admin');
    expect((q('pay-all') as HTMLButtonElement).disabled).toBeFalse();
    expect(q('pay-selected')).not.toBeNull();
    expect((q('pay-now') as HTMLButtonElement).disabled).toBeFalse();
    discardPeriodicTasks();
  }));

  it('builds the mode text', () => {
    expect(paymentMode(queue({ pay_when_queue_empty: false }))).toBe('Queued invoices are paid only when someone clicks Pay.');
  });
});
