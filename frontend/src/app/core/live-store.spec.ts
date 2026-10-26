import { TestBed, discardPeriodicTasks, fakeAsync, tick } from '@angular/core/testing';
import { BehaviorSubject, of } from 'rxjs';

import { LiveStore, POLL_MS, PageVisibility, PollTicker } from './live-store';

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
