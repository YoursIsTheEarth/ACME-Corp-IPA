import { TestBed, fakeAsync, tick } from '@angular/core/testing';
import { NEVER, Subject } from 'rxjs';

import { BatchRow, PaymentQueueRow } from './api.models';
import { EventStreamService, ServerEvent } from './event-stream.service';
import { Stores } from './live-store';
import { NotificationsService, SWAP_FALLBACK_MS, batchMessage } from './notifications.service';
import { ToastService } from './toast.service';
import { DestroyRef } from '@angular/core';

function batch(id: string, finished: boolean): BatchRow {
  return {
    batch_id: id, trigger: 'pay_all', trigger_label: 'Pay all', released_by: 'Dana', started_at: '',
    finished_at: finished ? 'x' : null, running: !finished, count: 7, total_usd: '37620.00', failed_count: 0,
  };
}

function row(id: number, invoice: string, revision: number, kind: PaymentQueueRow['kind'], amount: string): PaymentQueueRow {
  return {
    id, run_id: `r${id}`, file_name: null, invoice_number: invoice, revision, vendor: 'V', amount_usd: amount, kind,
    approved_by: null, queued_at: '', status: 'queued', attempts: 0, last_error: null, batch_id: null,
  };
}

describe('NotificationsService', () => {
  let toasts: string[];
  let events: Subject<ServerEvent>;
  let service: NotificationsService;

  beforeEach(() => {
    toasts = [];
    events = new Subject();
    TestBed.configureTestingModule({
      providers: [
        { provide: ToastService, useValue: { show: (m: string) => toasts.push(m) } },
        { provide: EventStreamService, useValue: { events$: events } },
        { provide: Stores, useValue: { batches: { data$: NEVER }, paymentQueue: { data$: NEVER } } },
      ],
    });
    service = TestBed.inject(NotificationsService);
    service.start(TestBed.inject(DestroyRef));
  });

  it('formats the batch summary', () => {
    expect(batchMessage({ batch_id: 'B-0142', count: 7, total_usd: '37620.00', failed_count: 0 })).toBe(
      'Batch B-0142: 7 paid, $37,620, 0 failed',
    );
  });

  it('toasts a newly finished batch once, from polling or the event, and never for old batches', () => {
    service.onBatches([batch('B-0001', true)]);
    expect(toasts).toEqual([]);
    service.onBatches([batch('B-0002', false), batch('B-0001', true)]);
    expect(toasts).toEqual([]);
    events.next({ name: 'batch.finished', data: { batch_id: 'B-0002', count: 7, total_usd: '37620.00', failed_count: 0 } });
    service.onBatches([batch('B-0002', true), batch('B-0001', true)]);
    expect(toasts).toEqual(['Batch B-0002: 7 paid, $37,620, 0 failed']);
  });

  it('toasts a revision swap when the replacement appears and the original leaves', fakeAsync(() => {
    service.onQueue([row(2, 'INV-1004', 0, 'full', '1890.00'), row(1, 'INV-1001', 0, 'full', '5000.00')]);
    service.onQueue([row(1, 'INV-1001', 0, 'full', '5000.00'), row(3, 'INV-1004', 1, 'replacement', '5940.00')]);
    expect(toasts.length).toBe(1);
    expect(toasts[0]).toContain('INV-1004 R1 replaced the queued original INV-1004');
    expect(toasts[0]).toContain('$5,940.00');
    events.next({ name: 'payment.queued', data: { row_id: 3, kind: 'replacement', invoice_number: 'INV-1004', amount_usd: '5940.00' } });
    tick(SWAP_FALLBACK_MS);
    expect(toasts.length).toBe(1);
  }));

  it('falls back to the event when the list diff missed the swap', fakeAsync(() => {
    events.next({ name: 'payment.queued', data: { row_id: 9, kind: 'replacement', invoice_number: 'INV-1004', amount_usd: '5940.00' } });
    tick(SWAP_FALLBACK_MS);
    expect(toasts).toEqual(['INV-1004 revision replaced the queued original INV-1004; it will pay $5,940.00.']);
  }));
});
