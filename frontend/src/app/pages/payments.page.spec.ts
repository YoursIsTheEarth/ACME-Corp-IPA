import { provideHttpClient } from '@angular/common/http';
import { TestBed, discardPeriodicTasks, fakeAsync, tick } from '@angular/core/testing';
import { provideNoopAnimations } from '@angular/platform-browser/animations';
import { provideRouter } from '@angular/router';
import { BehaviorSubject, of } from 'rxjs';

import { ApiClient } from '../core/api-client';
import { PaymentRow, PaymentsFilter } from '../core/api.models';
import { PageVisibility } from '../core/live-store';
import { PaymentsPage } from './payments.page';

function payment(id: string, vendor: string, amount: string, extra: Partial<PaymentRow> = {}): PaymentRow {
  return {
    payment_id: id, run_id: `run-${id}`, file_name: null, invoice_number: `INV-${id}`, revision: 0, vendor,
    amount_usd: amount, original_amount: null, original_currency: null, kind: 'full', delta_label: null,
    invoice_total_usd: amount, approved_by: 'Auto (rules)', paid_at: '2026-10-25T20:00:00+00:00',
    idempotency_key: `key-${id}`, batch_id: 'B-0001', batch_trigger: 'pay_all', batch_trigger_label: 'Pay all',
    released_by: 'Dana', ...extra,
  };
}

describe('PaymentsPage', () => {
  const all = [
    payment('1001', 'Widgets Inc.', '5000.00'),
    payment('1006', 'Acme Industrial Supplies', '2750.00'),
    payment('1014', 'TechParts International', '4455.00', { original_amount: '4125.00', original_currency: 'EUR' }),
    payment('1016', 'Widgets Inc.', '1200.50'),
  ];
  let requested: PaymentsFilter[];

  beforeEach(() => {
    requested = [];
    TestBed.configureTestingModule({
      imports: [PaymentsPage],
      providers: [
        provideNoopAnimations(),
        provideHttpClient(),
        provideRouter([]),
        { provide: PageVisibility, useValue: { visible$: new BehaviorSubject(false) } },
        {
          provide: ApiClient,
          useValue: {
            payments: (f: PaymentsFilter) => {
              requested.push(f);
              const rows = all.filter((r) => !f.vendor || r.vendor.toLowerCase().includes(f.vendor.toLowerCase()));
              return of({ rows, count: rows.length, total_usd: '0', server_time: '' });
            },
          },
        },
      ],
    });
  });

  it('sums only the filtered rows in the footer and shows the original currency', fakeAsync(() => {
    const fixture = TestBed.createComponent(PaymentsPage);
    const el: HTMLElement = fixture.nativeElement;
    const render = () => {
      fixture.detectChanges();
      tick();
      fixture.detectChanges();
    };
    render();
    expect(el.querySelector('[data-testid=payments-total]')!.textContent).toContain('4 payments');
    expect(el.querySelector('[data-testid=payments-total]')!.textContent).toContain('$13,405.50');
    expect(el.textContent).toContain('EUR 4,125.00');

    const vendor = el.querySelector('[data-testid=vendor-filter]') as HTMLInputElement;
    vendor.value = 'widgets';
    vendor.dispatchEvent(new Event('input'));
    tick(300);
    render();
    expect(requested.at(-1)).toEqual({ vendor: 'widgets' });
    expect(el.querySelector('[data-testid=payments-total]')!.textContent).toContain('2 payments');
    expect(el.querySelector('[data-testid=payments-total]')!.textContent).toContain('$6,200.50');
    expect((el.querySelector('[data-testid=export-csv]') as HTMLAnchorElement).getAttribute('href')).toBe('/api/payments.csv?vendor=widgets');

    const search = el.querySelector('[data-testid=table-search]') as HTMLInputElement;
    search.value = '1016';
    search.dispatchEvent(new Event('input'));
    render();
    expect(el.querySelector('[data-testid=payments-total]')!.textContent).toContain('$1,200.50');
    discardPeriodicTasks();
  }));
});
