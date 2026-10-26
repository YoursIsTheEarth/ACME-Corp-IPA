import { DOCUMENT } from '@angular/common';
import { Injectable, inject } from '@angular/core';
import {
  BehaviorSubject,
  EMPTY,
  Observable,
  Subject,
  catchError,
  combineLatest,
  distinctUntilChanged,
  fromEvent,
  map,
  merge,
  share,
  shareReplay,
  startWith,
  switchMap,
  timer,
} from 'rxjs';

import { ApiClient } from './api-client';
import { AuditFilter, AuditRow, InvoiceListResponse, PaymentsFilter, PaymentsResponse } from './api.models';

export const POLL_MS = 3000;

/** Whether the tab is visible; polling pauses while it is hidden. */
@Injectable({ providedIn: 'root' })
export class PageVisibility {
  private readonly doc = inject(DOCUMENT);
  readonly visible$: Observable<boolean> = fromEvent(this.doc, 'visibilitychange').pipe(
    map(() => !this.doc.hidden),
    startWith(!this.doc.hidden),
    distinctUntilChanged(),
    shareReplay({ bufferSize: 1, refCount: true }),
  );
}

/**
 * The one 3-second tick every store shares. It runs only while the tab is visible and polling is
 * enabled; `EventStreamService` disables polling while the SSE stream is connected.
 */
@Injectable({ providedIn: 'root' })
export class PollTicker {
  readonly polling$ = new BehaviorSubject<boolean>(true);
  readonly tick$: Observable<number> = combineLatest([inject(PageVisibility).visible$, this.polling$]).pipe(
    map(([visible, polling]) => visible && polling),
    distinctUntilChanged(),
    // First start waits one period (stores fetch on subscribe); a resume catches up at once.
    switchMap((on, index) => (on ? timer(index === 0 ? POLL_MS : 0, POLL_MS) : EMPTY)),
    share(),
  );

  setPolling(on: boolean): void {
    if (this.polling$.value !== on) this.polling$.next(on);
  }
}

/**
 * One live resource: `data$` fetches on subscribe, on every poll tick, on `refresh()`, and when the
 * params change. Failed fetches keep the last value. Pages subscribe with the `async` pipe.
 */
export class LiveStore<T, P = void> {
  private readonly refresh$ = new Subject<void>();
  private readonly params$: BehaviorSubject<P>;
  readonly data$: Observable<T>;

  constructor(tick$: Observable<unknown>, fetch: (params: P) => Observable<T>, initialParams: P) {
    this.params$ = new BehaviorSubject<P>(initialParams);
    this.data$ = this.params$.pipe(
      switchMap((params) =>
        merge(tick$, this.refresh$).pipe(
          startWith(null),
          switchMap(() => fetch(params).pipe(catchError(() => EMPTY))),
        ),
      ),
      shareReplay({ bufferSize: 1, refCount: true }),
    );
  }

  get params(): P {
    return this.params$.value;
  }

  setParams(params: P): void {
    this.params$.next(params);
  }

  refresh(): void {
    this.refresh$.next();
  }
}

export type StoreName = 'queue' | 'review' | 'audit' | 'paymentQueue' | 'payments' | 'batches' | 'stats' | 'adminSettings';

/** Every store the app uses, behind the shared tick. */
@Injectable({ providedIn: 'root' })
export class Stores {
  private readonly api = inject(ApiClient);
  private readonly tick$ = inject(PollTicker).tick$;

  readonly queue = new LiveStore(this.tick$, () => this.api.queue(), undefined);
  readonly review = new LiveStore(this.tick$, () => this.api.review(), undefined);
  readonly audit = new LiveStore<InvoiceListResponse<AuditRow>, AuditFilter>(this.tick$, (f) => this.api.audit(f), {});
  readonly paymentQueue = new LiveStore(this.tick$, () => this.api.paymentQueue(), undefined);
  readonly payments = new LiveStore<PaymentsResponse, PaymentsFilter>(this.tick$, (f) => this.api.payments(f), {});
  readonly batches = new LiveStore(this.tick$, () => this.api.batches(), undefined);
  readonly stats = new LiveStore(this.tick$, () => this.api.stats(), undefined);
  /** Payment timing; refreshed by `settings.updated` (another browser or the CLI saved it). */
  readonly adminSettings = new LiveStore(this.tick$, () => this.api.getAdminSettings(), undefined);

  refresh(...names: StoreName[]): void {
    for (const name of names) this[name].refresh();
  }

  refreshAll(): void {
    this.refresh('queue', 'review', 'audit', 'paymentQueue', 'payments', 'batches', 'stats', 'adminSettings');
  }
}
