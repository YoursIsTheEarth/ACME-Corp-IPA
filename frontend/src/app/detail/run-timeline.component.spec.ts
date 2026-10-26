import { TestBed } from '@angular/core/testing';

import { ApiClient } from '../core/api-client';
import { InvoiceDetail, TimelineEntry } from '../core/api.models';
import { RunTimelineComponent, describe as describeEntry } from './run-timeline.component';

const FLAG: TimelineEntry = {
  ts: '2026-10-26T15:04:00+00:00',
  agent: 'disposition',
  event: 'finding.retroactive',
  payload: {
    finding: { code: 'PAYEE_CUMULATIVE_THRESHOLD', severity: 'WARNING', message: 'Payee total $19,250.00 over 2 invoices in 30 days' },
    triggered_by: { run_id: 'run-1019', invoice_number: 'INV-1019' },
    total: '19250.00',
    status: 'Resolved',
  },
};

describe('RunTimelineComponent', () => {
  it('labels a retroactive payee threshold flag "Flagged after resolution"', () => {
    const item = describeEntry(FLAG);
    expect(item.title).toBe('Flagged after resolution');
    expect(item.lines[0]).toBe('Payee cumulative threshold: payee total $19,250.00, raised by INV-1019');
    expect(item.lines[1]).toContain('over 2 invoices in 30 days');
    expect(item.ts).toBe(FLAG.ts);
  });

  it('labels an updated hold and shows its payee total', () => {
    const item = describeEntry({
      ts: '', agent: 'disposition', event: 'review.enqueued',
      payload: { kind: 'payee_threshold', reason: 'Payee cumulative threshold', update: true,
                 details: { payee_threshold: { total: '29000.00', invoices: [{ invoice_number: 'INV-1018' }, { invoice_number: 'INV-1019' }, { invoice_number: 'INV-1020' }] } } },
    });
    expect(item.title).toBe('Hold updated');
    expect(item.lines).toEqual(['Payee cumulative threshold', 'Payee total $29,000.00: INV-1018, INV-1019, INV-1020']);
  });

  it('renders the flag in the timeline of a paid invoice', () => {
    TestBed.configureTestingModule({ imports: [RunTimelineComponent], providers: [{ provide: ApiClient, useValue: {} }] });
    const fixture = TestBed.createComponent(RunTimelineComponent);
    fixture.componentRef.setInput('detail', { timeline: [FLAG], reviews: [], final_status: 'Paid' } as unknown as InvoiceDetail);
    fixture.detectChanges();
    const text = (fixture.nativeElement as HTMLElement).querySelector('[data-testid=timeline]')!.textContent!;
    expect(text).toContain('Flagged after resolution');
    expect(text).toContain('raised by INV-1019');
    expect(text).toContain('$19,250.00');
  });
});
