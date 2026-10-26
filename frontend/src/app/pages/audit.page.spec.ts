import { provideHttpClient } from '@angular/common/http';
import { TestBed, discardPeriodicTasks, fakeAsync, flush, tick } from '@angular/core/testing';
import { provideNoopAnimations } from '@angular/platform-browser/animations';
import { provideRouter } from '@angular/router';
import { BehaviorSubject, of } from 'rxjs';

import { ApiClient } from '../core/api-client';
import { AuditFilter, AuditRow } from '../core/api.models';
import { PageVisibility } from '../core/live-store';
import { STATUS_STYLE } from '../shared/status';
import { AuditPage, FINAL_STATUSES } from './audit.page';

function row(id: string, final_status: string): AuditRow {
  return {
    id, file_name: `${id}.json`, format: 'json', invoice_number: id, vendor: 'Precision Parts Ltd.', amount_usd: '5940.00',
    stage: 'Resolved', status: 'Resolved', final_status, decided_by: 'Auto (rules)', uploaded_at: '2026-10-25T20:00:00+00:00',
    completed_at: '2026-10-25T20:01:00+00:00', stage_entered_at: null, time_in_stage_s: null, processing_s: 60,
    key_findings: [{ code: 'REVISION', severity: 'INFO', message: 'Revision 1' }], findings_count: 1,
  };
}

describe('AuditPage', () => {
  let requested: AuditFilter[];

  beforeEach(() => {
    requested = [];
    TestBed.configureTestingModule({
      imports: [AuditPage],
      providers: [
        provideNoopAnimations(),
        provideHttpClient(),
        provideRouter([]),
        { provide: PageVisibility, useValue: { visible$: new BehaviorSubject(false) } },
        {
          provide: ApiClient,
          useValue: {
            audit: (f: AuditFilter) => {
              requested.push(f);
              const rows = [row('INV-1004', 'Paid'), row('INV-1004 R1', 'Revised')].filter((r) => !f.status || r.final_status === f.status);
              return of({ view: 'audit', rows, count: rows.length, server_time: '' });
            },
          },
        },
      ],
    });
  });

  it('keeps a paid invoice flagged after resolution Paid and lists the flag in its key findings', fakeAsync(() => {
    const flagged: AuditRow = {
      ...row('INV-1018', 'Paid'),
      key_findings: [
        { code: 'PAYEE_CUMULATIVE_THRESHOLD', severity: 'WARNING', message: 'Payee total $19,250.00' },
        { code: 'NEAR_THRESHOLD', severity: 'INFO', message: 'Just under the VP threshold' },
      ],
      findings_count: 2,
    };
    TestBed.overrideProvider(ApiClient, { useValue: { audit: () => of({ view: 'audit', rows: [flagged], count: 1, server_time: '' }) } });
    const fixture = TestBed.createComponent(AuditPage);
    fixture.detectChanges();
    tick();
    fixture.detectChanges();
    const el: HTMLElement = fixture.nativeElement;
    expect(Array.from(el.querySelectorAll('.chip')).map((c) => c.getAttribute('data-status'))).toEqual(['Paid']);
    expect(Array.from(el.querySelectorAll('.finding-chip')).map((c) => c.textContent!.trim())).toContain('Payee cumulative threshold');
    flush();
    discardPeriodicTasks();
  }));

  it('offers Revised in the status filter, filters by it, and gives it its own chip', fakeAsync(() => {
    expect(FINAL_STATUSES).toEqual(['Paid', 'Revised', 'Rejected', 'Duplicate', 'Superseded', 'Credit confirmed']);
    const fixture = TestBed.createComponent(AuditPage);
    const el: HTMLElement = fixture.nativeElement;
    const render = () => {
      fixture.detectChanges();
      tick();
      fixture.detectChanges();
    };
    render();
    (el.querySelector('[data-testid=status-filter] .mat-mdc-select-trigger') as HTMLElement).click();
    render();
    const options = Array.from(document.querySelectorAll('mat-option')).map((o) => o.textContent!.trim());
    expect(options).toContain('Revised');
    (Array.from(document.querySelectorAll('mat-option')).find((o) => o.textContent!.trim() === 'Revised') as HTMLElement).click();
    render();
    expect(requested.at(-1)).toEqual({ status: 'Revised' });
    const chips = Array.from(el.querySelectorAll('.chip')) as HTMLElement[];
    expect(chips.map((c) => c.getAttribute('data-status'))).toEqual(['Revised']);
    expect(STATUS_STYLE.Revised.bg).not.toBe(STATUS_STYLE.Paid.bg);
    discardPeriodicTasks();
  }));
});
