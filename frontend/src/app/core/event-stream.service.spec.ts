import { TestBed, fakeAsync, tick } from '@angular/core/testing';
import { BehaviorSubject } from 'rxjs';

import { EVENT_SOURCE_FACTORY, EventStreamService } from './event-stream.service';
import { PageVisibility, PollTicker, Stores } from './live-store';

class FakeEventSource {
  static instances: FakeEventSource[] = [];
  listeners = new Map<string, ((e: MessageEvent) => void)[]>();
  onerror: (() => void) | null = null;
  closed = false;
  constructor(public url: string) {
    FakeEventSource.instances.push(this);
  }
  addEventListener(name: string, fn: (e: MessageEvent) => void) {
    this.listeners.set(name, [...(this.listeners.get(name) ?? []), fn]);
  }
  emit(name: string, data: unknown = {}) {
    for (const fn of this.listeners.get(name) ?? []) fn(new MessageEvent(name, { data: JSON.stringify(data) }));
  }
  close() {
    this.closed = true;
  }
}

describe('EventStreamService', () => {
  let service: EventStreamService;
  let ticker: PollTicker;
  let refreshed: string[][];

  beforeEach(() => {
    FakeEventSource.instances = [];
    refreshed = [];
    TestBed.configureTestingModule({
      providers: [
        { provide: PageVisibility, useValue: { visible$: new BehaviorSubject(true) } },
        { provide: EVENT_SOURCE_FACTORY, useValue: (url: string) => new FakeEventSource(url) },
        {
          provide: Stores,
          useValue: { refresh: (...n: string[]) => refreshed.push(n), refreshAll: () => refreshed.push(['all']) },
        },
      ],
    });
    service = TestBed.inject(EventStreamService);
    ticker = TestBed.inject(PollTicker);
  });

  afterEach(() => service.disconnect());

  it('connects, stops polling, and refreshes the stores an event affects', fakeAsync(() => {
    service.connect();
    const es = FakeEventSource.instances[0];
    expect(es.url).toBe('/api/events');
    es.emit('ready');
    expect(service.connected()).toBeTrue();
    expect(ticker.polling$.value).toBeFalse();
    expect(refreshed).toEqual([['all']]);

    const seen: string[] = [];
    service.events$.subscribe((e) => seen.push(e.name));
    es.emit('invoice.stage_changed', { run_id: 'r1', stage: 'Deciding' });
    es.emit('batch.finished', { batch_id: 'B-1', count: 7, total_usd: '37620.00', failed_count: 0 });
    expect(seen).toEqual(['invoice.stage_changed', 'batch.finished']);
    tick(100); // invalidations are coalesced
    expect(refreshed[1]).toEqual(jasmine.arrayContaining(['queue', 'review', 'stats', 'paymentQueue', 'payments', 'batches']));
  }));

  it('falls back to polling on error and reconnects with backoff', fakeAsync(() => {
    service.connect();
    FakeEventSource.instances[0].emit('ready');
    FakeEventSource.instances[0].onerror!();
    expect(FakeEventSource.instances[0].closed).toBeTrue();
    expect(service.connected()).toBeFalse();
    expect(ticker.polling$.value).toBeTrue();

    tick(999);
    expect(FakeEventSource.instances.length).toBe(1);
    tick(1);
    expect(FakeEventSource.instances.length).toBe(2);

    FakeEventSource.instances[1].onerror!(); // second failure waits longer
    tick(1999);
    expect(FakeEventSource.instances.length).toBe(2);
    tick(1);
    expect(FakeEventSource.instances.length).toBe(3);

    FakeEventSource.instances[2].emit('ready');
    expect(service.connected()).toBeTrue();
    expect(ticker.polling$.value).toBeFalse();
  }));
});
