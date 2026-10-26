import { HttpErrorResponse } from '@angular/common/http';
import { ComponentFixture, TestBed, discardPeriodicTasks, fakeAsync, flush, tick } from '@angular/core/testing';
import { provideNoopAnimations } from '@angular/platform-browser/animations';
import { provideRouter } from '@angular/router';
import { BehaviorSubject, Observable, of, throwError } from 'rxjs';

import { ApiClient } from '../core/api-client';
import { AdminSettings, AdminSettingsRequest } from '../core/api.models';
import { PageVisibility, Stores } from '../core/live-store';
import { ToastService } from '../core/toast.service';
import { NAME_STORAGE_KEY } from '../shared/reviewer-name-field.component';
import { AdminPage, clock, modeSentence } from './admin.page';

const DEFAULTS: AdminSettings = {
  delay_payments: true,
  pay_at_end_of_day: false,
  end_of_day_time: '17:00',
  end_of_day_timezone: 'America/Chicago',
  pay_when_queue_empty: true,
  updated_by: null,
  updated_at: null,
};

describe('AdminPage', () => {
  let stored: AdminSettings;
  let saved: AdminSettingsRequest[];
  let saveResult: () => Observable<AdminSettings>;
  let toasts: string[];
  let fixture: ComponentFixture<AdminPage>;
  let el: HTMLElement;

  const q = (testid: string) => el.querySelector(`[data-testid=${testid}]`) as HTMLElement | null;
  const input = (testid: string) => q(testid) as HTMLInputElement;
  const toggle = (testid: string) => q(testid)!.querySelector('button[role=switch]') as HTMLButtonElement;
  const checked = (testid: string) => toggle(testid).getAttribute('aria-checked') === 'true';

  function render(): void {
    fixture.detectChanges();
    tick();
    fixture.detectChanges();
  }

  function type(testid: string, value: string): void {
    const field = input(testid);
    field.value = value;
    field.dispatchEvent(new Event('input'));
    render();
  }

  function open(initial: AdminSettings = DEFAULTS): void {
    stored = initial;
    fixture = TestBed.createComponent(AdminPage);
    el = fixture.nativeElement;
    render();
  }

  beforeEach(() => {
    localStorage.removeItem(NAME_STORAGE_KEY);
    saved = [];
    toasts = [];
    saveResult = () => {
      const body = saved.at(-1)!;
      const { updated_by, ...timing } = body;
      stored = { ...timing, updated_by, updated_at: '2026-10-26T15:00:00+00:00' };
      return of(stored);
    };
    TestBed.configureTestingModule({
      imports: [AdminPage],
      providers: [
        provideNoopAnimations(),
        provideRouter([]),
        { provide: PageVisibility, useValue: { visible$: new BehaviorSubject(false) } },
        {
          provide: ApiClient,
          useValue: {
            getAdminSettings: () => of(stored),
            paymentQueue: () => of({ rows: [], count: 0 }),
            saveAdminSettings: (body: AdminSettingsRequest) => {
              saved.push(body);
              return saveResult();
            },
          },
        },
        {
          provide: ToastService,
          useValue: { show: (m: string) => toasts.push(m), error: (m: string) => toasts.push(`error: ${m}`) },
        },
      ],
    });
  });

  afterEach(() => localStorage.removeItem(NAME_STORAGE_KEY));

  it('shows the defaults on a new database', fakeAsync(() => {
    open();
    expect(checked('delay-toggle')).toBeTrue();
    expect(checked('eod-toggle')).toBeFalse();
    expect(checked('queue-empty-toggle')).toBeTrue();
    expect(q('mode')!.textContent).toContain(
      'Approved invoices wait in the Payment Queue and are paid when the Invoice Queue is empty.',
    );
    expect(q('last-saved')!.textContent).toContain('Never saved');
    expect(input('eod-time').disabled).toBeTrue();
    expect(input('eod-timezone').disabled).toBeTrue();
    expect((q('save') as HTMLButtonElement).disabled).toBeTrue(); // nothing changed yet
    flush();
    discardPeriodicTasks();
  }));

  it('shows who saved the settings last and when', fakeAsync(() => {
    open({ ...DEFAULTS, updated_by: 'Dana', updated_at: '2026-10-26T14:00:00+00:00' });
    expect(q('last-saved')!.textContent).toContain('Last saved by Dana');
    expect(q('last-saved')!.textContent).toMatch(/\d/);
    flush();
    discardPeriodicTasks();
  }));

  it('turning end of day on enables 5:00 PM Central Time; turning it off keeps the values', fakeAsync(() => {
    open();
    toggle('eod-toggle').click();
    render();
    expect(input('eod-time').disabled).toBeFalse();
    expect(input('eod-time').value).toBe('17:00');
    expect(q('eod-time-hint')!.textContent).toContain('5:00 PM');
    expect(input('eod-timezone').disabled).toBeFalse();
    expect(input('eod-timezone').value).toBe('America/Chicago');
    expect(q('eod-timezone-hint')!.textContent).toContain('Central Time (America/Chicago)');
    expect(q('mode')!.textContent).toContain('5:00 PM Central Time (America/Chicago)');

    type('eod-time', '15:00');
    toggle('eod-toggle').click();
    render();
    expect(input('eod-time').disabled).toBeTrue();
    expect(input('eod-time').value).toBe('15:00');
    expect(input('eod-timezone').disabled).toBeTrue();
    expect(input('eod-timezone').value).toBe('America/Chicago');
    flush();
    discardPeriodicTasks();
  }));

  it('turning delay off hides the batch options and warns that saving pays the queue', fakeAsync(() => {
    open();
    expect(q('batch-options')).not.toBeNull();
    expect(q('pays-queue-warning')).toBeNull();
    toggle('delay-toggle').click();
    render();
    expect(q('batch-options')).toBeNull();
    expect(q('pays-queue-warning')!.textContent).toContain('pay everything currently queued');
    expect(q('mode')!.textContent).toContain('paid as soon as they are approved');
    expect((q('save') as HTMLButtonElement).disabled).toBeFalse();
    flush();
    discardPeriodicTasks();
  }));

  it('saves with a name from the confirm dialog, toasts, and shows the new last saved by', fakeAsync(() => {
    open({ ...DEFAULTS, pay_at_end_of_day: true });
    type('eod-time', '15:00');
    (q('save') as HTMLButtonElement).click();
    render();
    const dialog = document.querySelector('mat-dialog-container') as HTMLElement;
    expect(dialog.querySelector('[data-testid=change-summary]')!.textContent).toContain('End-of-day time: 5:00 PM → 3:00 PM');
    const confirm = dialog.querySelector('[data-testid=confirm]') as HTMLButtonElement;
    expect(confirm.disabled).toBeTrue(); // the name is required
    const name = dialog.querySelector('[data-testid=name-input]') as HTMLInputElement;
    name.value = 'Sam Ortiz';
    name.dispatchEvent(new Event('input'));
    render();
    confirm.click();
    render();
    flush();
    render();
    expect(saved).toEqual([
      {
        delay_payments: true,
        pay_at_end_of_day: true,
        end_of_day_time: '15:00',
        end_of_day_timezone: 'America/Chicago',
        pay_when_queue_empty: true,
        updated_by: 'Sam Ortiz',
      },
    ]);
    expect(toasts).toEqual(['Payment settings saved by Sam Ortiz.']);
    expect(q('last-saved')!.textContent).toContain('Last saved by Sam Ortiz');
    expect((q('save') as HTMLButtonElement).disabled).toBeTrue(); // saved values are the new baseline
    expect(localStorage.getItem(NAME_STORAGE_KEY)).toBe('Sam Ortiz');
    flush();
    discardPeriodicTasks();
  }));

  it('shows a 422 on the timezone field and changes nothing else', fakeAsync(() => {
    open({ ...DEFAULTS, pay_at_end_of_day: true });
    localStorage.setItem(NAME_STORAGE_KEY, 'Dana');
    saveResult = () =>
      throwError(
        () =>
          new HttpErrorResponse({
            status: 422,
            error: { detail: [{ loc: ['body', 'end_of_day_timezone'], msg: "Value error, unknown timezone 'Mars/Olympus'" }] },
          }),
      );
    type('eod-timezone', 'Mars/Olympus');
    (q('save') as HTMLButtonElement).click();
    render();
    (document.querySelector('mat-dialog-container [data-testid=confirm]') as HTMLButtonElement).click();
    render();
    flush();
    render();
    expect(saved.length).toBe(1);
    expect(q('eod-timezone-error')!.textContent).toContain("unknown timezone 'Mars/Olympus'");
    expect(q('eod-time-error')).toBeNull();
    expect(input('eod-time').value).toBe('17:00');
    expect(q('last-saved')!.textContent).toContain('Never saved');
    expect(toasts).toEqual([]);
    flush();
    discardPeriodicTasks();
  }));

  it('refreshes an unchanged form, or warns about unsaved edits, when settings change elsewhere', fakeAsync(() => {
    open();
    const stores = TestBed.inject(Stores);
    stored = { ...DEFAULTS, pay_when_queue_empty: false, updated_by: 'Lee', updated_at: '2026-10-26T15:00:00+00:00' };
    stores.refresh('adminSettings'); // settings.updated
    render();
    expect(checked('queue-empty-toggle')).toBeFalse();
    expect(q('changed-elsewhere')).toBeNull();

    toggle('eod-toggle').click(); // an unsaved edit
    render();
    stored = { ...stored, delay_payments: false, updated_by: 'Kim', updated_at: '2026-10-26T15:05:00+00:00' };
    stores.refresh('adminSettings');
    render();
    expect(q('changed-elsewhere')!.textContent).toContain('changed elsewhere by Kim');
    expect(checked('eod-toggle')).toBeTrue(); // the edit is kept until the user reloads
    (q('reload') as HTMLButtonElement).click();
    render();
    expect(q('changed-elsewhere')).toBeNull();
    expect(checked('delay-toggle')).toBeFalse();
    expect(q('last-saved')!.textContent).toContain('Last saved by Kim');
    flush();
    discardPeriodicTasks();
  }));

  it('describes each mode in one sentence', () => {
    expect(clock('17:00')).toBe('5:00 PM');
    expect(clock('08:30')).toBe('8:30 AM');
    const base = { ...DEFAULTS };
    expect(modeSentence({ ...base, delay_payments: false })).toBe('Approved invoices are paid as soon as they are approved.');
    expect(modeSentence({ ...base, pay_at_end_of_day: true })).toContain('at 5:00 PM Central Time (America/Chicago), or when');
    expect(modeSentence({ ...base, pay_when_queue_empty: false })).toContain('until someone pays them');
  });
});
