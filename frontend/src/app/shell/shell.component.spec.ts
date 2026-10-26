import { BreakpointObserver, BreakpointState } from '@angular/cdk/layout';
import { Component, signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideNoopAnimations } from '@angular/platform-browser/animations';
import { Router, provideRouter } from '@angular/router';
import { BehaviorSubject, NEVER, Subject } from 'rxjs';

import { Stats } from '../core/api.models';
import { EventStreamService } from '../core/event-stream.service';
import { Stores } from '../core/live-store';
import { NotificationsService } from '../core/notifications.service';
import { NAV_ITEMS, ShellComponent } from './shell.component';

@Component({ standalone: true, template: '<p class="page-marker">page</p>' })
class DummyPage {}

function stats(partial: Partial<Stats> = {}): Stats {
  return {
    in_queue: 0,
    processing: 0,
    awaiting_review: 0,
    payment_queue: 0,
    paid_today: 0,
    rejected_today: 0,
    llm: { provider: 'claude', model: 'claude-sonnet-5-5', configured: true, missing_key: null },
    server_time: '',
    ...partial,
  };
}

describe('ShellComponent', () => {
  let fixture: ComponentFixture<ShellComponent>;
  let el: HTMLElement;
  let stats$: Subject<Stats>;
  let breakpoint$: BehaviorSubject<BreakpointState>;

  async function render(): Promise<void> {
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();
  }

  beforeEach(async () => {
    stats$ = new Subject<Stats>();
    breakpoint$ = new BehaviorSubject<BreakpointState>({ matches: false, breakpoints: {} });
    TestBed.configureTestingModule({
      imports: [ShellComponent],
      providers: [
        provideNoopAnimations(),
        provideRouter(['', 'queue', 'audit', 'review', 'payment-queue', 'payments'].map((path) => ({ path, component: DummyPage }))),
        { provide: Stores, useValue: { stats: { data$: stats$ } } },
        { provide: NotificationsService, useValue: { start: () => {} } },
        {
          provide: EventStreamService,
          useValue: { connected: signal(false), connect: () => {}, disconnect: () => {}, events$: NEVER },
        },
        { provide: BreakpointObserver, useValue: { observe: () => breakpoint$ } },
      ],
    });
    fixture = TestBed.createComponent(ShellComponent);
    el = fixture.nativeElement;
    await render();
  });

  it('shows the name, tagline, and six items in order', () => {
    expect(el.querySelector('.brand')!.textContent).toContain('ACME Corp IPA');
    expect(el.querySelector('.brand')!.textContent).toContain('Invoice Processing Automation');
    const labels = Array.from(el.querySelectorAll('.sidebar .nav a [matListItemTitle]')).map((a) => a.textContent!.trim());
    expect(labels).toEqual([
      'Home',
      'Invoice Queue',
      'Payment Queue',
      'Invoice Elevated Review',
      'Invoice Resolution Audit',
      'Payments',
    ]);
  });

  it('highlights the item for each route loaded by URL', async () => {
    const router = TestBed.inject(Router);
    for (const item of NAV_ITEMS) {
      await router.navigateByUrl(item.path);
      await render();
      const active = Array.from(el.querySelectorAll('.sidebar .nav a.active'));
      expect(active.length).withContext(item.path).toBe(1);
      expect(active[0].querySelector('[matListItemTitle]')!.textContent!.trim()).toBe(item.label);
      expect(el.querySelectorAll('.page-marker').length).toBe(1);
    }
  });

  it('shows badge counts and hides them at zero', async () => {
    stats$.next(stats({ in_queue: 4, awaiting_review: 2, payment_queue: 0 }));
    await render();
    expect(el.querySelector('[data-testid="badge-/queue"]')!.textContent!.trim()).toBe('4');
    expect(el.querySelector('[data-testid="badge-/review"]')!.textContent!.trim()).toBe('2');
    expect(el.querySelector('[data-testid="badge-/payment-queue"]')).toBeNull();

    stats$.next(stats({ in_queue: 4, awaiting_review: 1, payment_queue: 3 }));
    await render();
    expect(el.querySelector('[data-testid="badge-/review"]')!.textContent!.trim()).toBe('1');
    expect(el.querySelector('[data-testid="badge-/payment-queue"]')!.textContent!.trim()).toBe('3');
  });

  it('reads the provider and model for the footer from stats', async () => {
    expect(el.querySelector('[data-testid=llm-footer]')!.textContent).toContain('Connecting');
    stats$.next(stats());
    await render();
    expect(el.querySelector('[data-testid=llm-provider]')!.textContent).toBe('Claude');
    expect(el.querySelector('[data-testid=llm-model]')!.textContent).toBe('claude-sonnet-5-5');
  });

  it('shows the missing-key banner while stats report no key, and hides it once a key is set', async () => {
    expect(el.querySelector('[data-testid=llm-banner]')).toBeNull(); // no stats yet
    stats$.next(stats({ llm: { provider: 'grok', model: 'grok-4', configured: false, missing_key: 'XAI_API_KEY' } }));
    await render();
    const banner = el.querySelector('[data-testid=llm-banner]')!;
    expect(banner.getAttribute('role')).toBe('alert');
    expect(banner.textContent).toContain('No LLM token provided — the app cannot process invoices without it');
    expect(banner.textContent).toContain('Set XAI_API_KEY in .env and restart the backend.');
    expect(el.querySelector('[data-testid=llm-provider]')!.textContent).toBe('Grok');

    stats$.next(stats());
    await render();
    expect(el.querySelector('[data-testid=llm-banner]')).toBeNull();
  });

  it('is a persistent side nav at 1200 px and an icon rail with overlay at 800 px', async () => {
    const shell = fixture.componentInstance;
    // 1200 px: query does not match.
    expect(shell.nav!.mode).toBe('side');
    expect(shell.nav!.opened).toBeTrue();
    expect(el.querySelector('[data-testid=rail]')).toBeNull();

    // 800 px: query matches.
    breakpoint$.next({ matches: true, breakpoints: {} });
    await render();
    expect(shell.nav!.mode).toBe('over');
    expect(shell.nav!.opened).toBeFalse();
    const rail = el.querySelector('[data-testid=rail]')!;
    expect(rail).not.toBeNull();
    expect(rail.querySelectorAll('.nav a').length).toBe(6);
    const railPaths = Array.from(rail.querySelectorAll('.nav a')).map((a) => a.getAttribute('data-testid'));
    expect(railPaths).toEqual(['nav-/', 'nav-/queue', 'nav-/payment-queue', 'nav-/review', 'nav-/audit', 'nav-/payments']);
    expect(rail.querySelector('[matListItemTitle]')).toBeNull(); // icons only

    (el.querySelector('[data-testid=menu-toggle]') as HTMLElement).click();
    await render();
    expect(shell.nav!.opened).toBeTrue();

    await TestBed.inject(Router).navigateByUrl('/payments');
    await render();
    expect(shell.nav!.opened).toBeFalse(); // overlay closes after navigation

    breakpoint$.next({ matches: false, breakpoints: {} });
    await render();
    expect(shell.nav!.mode).toBe('side');
    expect(shell.nav!.opened).toBeTrue();
  });
});
