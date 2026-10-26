import { Injectable, InjectionToken, NgZone, OnDestroy, inject, signal } from '@angular/core';
import { Subject } from 'rxjs';

import { API } from './api-client';
import { EVENT_NAMES, EventName } from './api.models';
import { PollTicker, StoreName, Stores } from './live-store';

/** Which stores each server event invalidates. */
export const INVALIDATES: Record<EventName, StoreName[]> = {
  'invoice.created': ['queue', 'stats'],
  'invoice.stage_changed': ['queue', 'review', 'stats'],
  'invoice.resolved': ['queue', 'review', 'audit', 'stats'],
  'payment.queued': ['queue', 'paymentQueue', 'stats'],
  'payment.cancelled': ['paymentQueue', 'audit', 'stats'],
  'batch.started': ['paymentQueue', 'batches'],
  'payment.created': ['paymentQueue', 'payments', 'stats'],
  'batch.finished': ['paymentQueue', 'payments', 'batches', 'audit', 'stats'],
  'settings.updated': ['adminSettings', 'paymentQueue'],
};

export interface ServerEvent {
  name: EventName;
  data: any;
}

export const EVENT_SOURCE_FACTORY = new InjectionToken<(url: string) => EventSource>('EVENT_SOURCE_FACTORY', {
  providedIn: 'root',
  factory: () => (url: string) => new EventSource(url),
});

const BACKOFF_MS = [1000, 2000, 5000, 10000, 30000];
const FLUSH_MS = 100;

/**
 * One `EventSource` on `/api/events` (F29). While it is open, polling stops and each event refreshes
 * the stores it affects. On error the app falls back to 3-second polling and reconnects with backoff.
 */
@Injectable({ providedIn: 'root' })
export class EventStreamService implements OnDestroy {
  private readonly stores = inject(Stores);
  private readonly ticker = inject(PollTicker);
  private readonly create = inject(EVENT_SOURCE_FACTORY);
  private readonly zone = inject(NgZone);

  readonly connected = signal(false);
  readonly events$ = new Subject<ServerEvent>();

  private source: EventSource | null = null;
  private attempt = 0;
  private retryTimer: ReturnType<typeof setTimeout> | null = null;
  private flushTimer: ReturnType<typeof setTimeout> | null = null;
  private pending = new Set<StoreName>();
  private stopped = false;

  connect(): void {
    this.stopped = false;
    this.open();
  }

  private open(): void {
    this.source?.close();
    let source: EventSource;
    try {
      source = this.create(`${API}/events`);
    } catch {
      this.onError();
      return;
    }
    this.source = source;
    source.addEventListener('ready', () => this.zone.run(() => this.onOpen()));
    for (const name of EVENT_NAMES) {
      source.addEventListener(name, (e: Event) => this.zone.run(() => this.onEvent(name, e as MessageEvent)));
    }
    source.onerror = () => this.zone.run(() => this.onError());
  }

  private onOpen(): void {
    this.attempt = 0;
    this.connected.set(true);
    this.ticker.setPolling(false);
    this.stores.refreshAll(); // events are not replayed: catch up on anything missed
  }

  private onEvent(name: EventName, event: MessageEvent): void {
    let data: unknown = {};
    try {
      data = JSON.parse(event.data);
    } catch {
      /* keep {} */
    }
    this.events$.next({ name, data });
    for (const store of INVALIDATES[name]) this.pending.add(store);
    this.flushTimer ??= setTimeout(() => this.flush(), FLUSH_MS);
  }

  private flush(): void {
    this.flushTimer = null;
    const names = [...this.pending];
    this.pending.clear();
    this.stores.refresh(...names);
  }

  private onError(): void {
    this.source?.close();
    this.source = null;
    this.connected.set(false);
    this.ticker.setPolling(true);
    if (this.stopped || this.retryTimer) return;
    const delay = BACKOFF_MS[Math.min(this.attempt, BACKOFF_MS.length - 1)];
    this.attempt++;
    this.retryTimer = setTimeout(() => {
      this.retryTimer = null;
      if (!this.stopped) this.open();
    }, delay);
  }

  disconnect(): void {
    this.stopped = true;
    if (this.retryTimer) clearTimeout(this.retryTimer);
    if (this.flushTimer) clearTimeout(this.flushTimer);
    this.retryTimer = this.flushTimer = null;
    this.source?.close();
    this.source = null;
    this.connected.set(false);
    this.ticker.setPolling(true);
  }

  ngOnDestroy(): void {
    this.disconnect();
  }
}
