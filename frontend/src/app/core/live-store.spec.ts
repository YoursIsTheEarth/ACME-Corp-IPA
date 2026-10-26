import { TestBed, discardPeriodicTasks, fakeAsync, tick } from '@angular/core/testing';
import { BehaviorSubject, of } from 'rxjs';

import { ApiClient } from './api-client';
import { AdminSettings } from './api.models';
import { LiveStore, POLL_MS, PageVisibility, PollTicker, Stores } from './live-store';

describe('LiveStore + PollTicker', () => {
  let visible: BehaviorSubject<boolean>;
  let ticker: PollTicker;
  let calls: number;
  let store: LiveStore<number, string>;
  let lastParam: string;

  beforeEach(() => {
    visible = new BehaviorSubject(true);
    TestBed.configureTestingModule({ providers: [{ provide: PageVisibility, useValue: { visible$: visible } }] });
    ticker = TestBed.inject(PollTicker);
    calls = 0;
    store = new LiveStore(
      ticker.tick$,
      (param) => {
        lastParam = param;
        return of(++calls);
      },
      'a',
    );
  });

  it('fetches on subscribe and then every 3 seconds', fakeAsync(() => {
    const seen: number[] = [];
    const sub = store.data$.subscribe((v) => seen.push(v));
    expect(calls).toBe(1);
    tick(POLL_MS - 1);
    expect(calls).toBe(1);
    tick(1);
    expect(calls).toBe(2);
    tick(POLL_MS * 2);
    expect(calls).toBe(4);
    expect(seen).toEqual([1, 2, 3, 4]);
    sub.unsubscribe();
  }));

  it('stops while the tab is hidden and catches up when visible again', fakeAsync(() => {
    const sub = store.data$.subscribe();
    tick(POLL_MS);
    expect(calls).toBe(2);
    visible.next(false);
    tick(POLL_MS * 5);
    expect(calls).toBe(2);
    visible.next(true);
    tick(0);
    expect(calls).toBe(3);
    tick(POLL_MS);
    expect(calls).toBe(4);
    sub.unsubscribe();
    discardPeriodicTasks();
  }));

  it('stops polling while disabled (SSE connected) but still refreshes on demand', fakeAsync(() => {
    const sub = store.data$.subscribe();
    ticker.setPolling(false);
    tick(POLL_MS * 3);
    expect(calls).toBe(1);
    store.refresh();
    expect(calls).toBe(2);
    ticker.setPolling(true);
    tick(0);
    expect(calls).toBe(3);
    sub.unsubscribe();
    discardPeriodicTasks();
  }));

  it('refetches with new params and shares one fetch between subscribers', fakeAsync(() => {
    const a = store.data$.subscribe();
    const b = store.data$.subscribe();
    expect(calls).toBe(1);
    store.setParams('b');
    expect(calls).toBe(2);
    expect(lastParam).toBe('b');
    a.unsubscribe();
    b.unsubscribe();
    discardPeriodicTasks();
  }));
});

describe('Stores.adminSettings', () => {
  const settings: AdminSettings = {
    delay_payments: true,
    pay_at_end_of_day: false,
    end_of_day_time: '17:00',
    end_of_day_timezone: 'America/Chicago',
    pay_when_queue_empty: true,
    updated_by: null,
    updated_at: null,
  };

  it('loads the admin settings and reloads them when settings.updated refreshes the store', fakeAsync(() => {
    let calls = 0;
    TestBed.configureTestingModule({
      providers: [
        { provide: PageVisibility, useValue: { visible$: new BehaviorSubject(true) } },
        { provide: ApiClient, useValue: { getAdminSettings: () => of({ ...settings, delay_payments: ++calls === 1 }) } },
      ],
    });
    const stores = TestBed.inject(Stores);
    const seen: boolean[] = [];
    const sub = stores.adminSettings.data$.subscribe((s) => seen.push(s.delay_payments));
    expect(seen).toEqual([true]);
    stores.refresh('adminSettings'); // what EventStreamService does on settings.updated
    expect(seen).toEqual([true, false]);
    sub.unsubscribe();
    discardPeriodicTasks();
  }));
});
