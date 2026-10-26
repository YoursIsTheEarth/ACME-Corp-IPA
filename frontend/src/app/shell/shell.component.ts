import { BreakpointObserver } from '@angular/cdk/layout';
import { AsyncPipe, NgTemplateOutlet } from '@angular/common';
import { ChangeDetectionStrategy, Component, DestroyRef, OnInit, ViewChild, computed, inject } from '@angular/core';
import { takeUntilDestroyed, toSignal } from '@angular/core/rxjs-interop';
import { MatBadgeModule } from '@angular/material/badge';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatListModule } from '@angular/material/list';
import { MatSidenav, MatSidenavModule } from '@angular/material/sidenav';
import { MatToolbarModule } from '@angular/material/toolbar';
import { MatTooltipModule } from '@angular/material/tooltip';
import { ActivatedRoute, NavigationEnd, Router, RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { filter, map } from 'rxjs';

import { Stats } from '../core/api.models';
import { DetailDrawer } from '../core/drawer';
import { EventStreamService } from '../core/event-stream.service';
import { Stores } from '../core/live-store';
import { NotificationsService } from '../core/notifications.service';
import { InvoiceDrawerComponent } from '../detail/invoice-drawer.component';

/** Below this width the sidebar collapses to icons and opens as an overlay. */
export const NARROW_QUERY = '(max-width: 959.98px)';

export interface NavItem {
  path: string;
  label: string;
  icon: string;
  badge?: keyof Pick<Stats, 'in_queue' | 'awaiting_review' | 'payment_queue'>;
}

export const NAV_ITEMS: NavItem[] = [
  { path: '/', label: 'Home', icon: 'home' },
  { path: '/queue', label: 'Invoice Queue', icon: 'inbox', badge: 'in_queue' },
  { path: '/payment-queue', label: 'Payment Queue', icon: 'request_quote', badge: 'payment_queue' },
  { path: '/review', label: 'Invoice Elevated Review', icon: 'gavel', badge: 'awaiting_review' },
  { path: '/audit', label: 'Invoice Resolution Audit', icon: 'fact_check' },
  { path: '/payments', label: 'Payments', icon: 'payments' },
];

const PROVIDER_LABELS: Record<string, string> = { grok: 'Grok', claude: 'Claude', offline: 'Offline' };

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [
    AsyncPipe,
    NgTemplateOutlet,
    RouterOutlet,
    RouterLink,
    RouterLinkActive,
    MatSidenavModule,
    MatToolbarModule,
    MatListModule,
    MatIconModule,
    MatButtonModule,
    MatBadgeModule,
    MatTooltipModule,
    InvoiceDrawerComponent,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './shell.component.html',
  styleUrl: './shell.component.scss',
})
export class ShellComponent implements OnInit {
  private readonly stores = inject(Stores);
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);
  private readonly destroyRef = inject(DestroyRef);
  private readonly stream = inject(EventStreamService);
  private readonly notifications = inject(NotificationsService);
  readonly drawer = inject(DetailDrawer);

  @ViewChild('nav') nav?: MatSidenav;

  readonly items = NAV_ITEMS;
  readonly narrow = toSignal(
    inject(BreakpointObserver)
      .observe(NARROW_QUERY)
      .pipe(map((state) => state.matches)),
    { initialValue: false },
  );
  readonly stats = toSignal(this.stores.stats.data$);
  readonly live = this.stream.connected;
  readonly invoiceId = toSignal(this.route.queryParamMap.pipe(map((p) => p.get('invoice'))), { initialValue: null });

  readonly provider = computed(() => {
    const llm = this.stats()?.llm;
    return llm ? (PROVIDER_LABELS[llm.provider] ?? llm.provider) : null;
  });
  readonly model = computed(() => this.stats()?.llm?.model ?? null);

  ngOnInit(): void {
    this.notifications.start(this.destroyRef);
    this.stream.connect();
    this.destroyRef.onDestroy(() => this.stream.disconnect());
    this.router.events
      .pipe(
        filter((e) => e instanceof NavigationEnd),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe(() => {
        if (this.narrow()) this.nav?.close();
      });
  }

  badge(item: NavItem): number {
    return item.badge ? (this.stats()?.[item.badge] ?? 0) : 0;
  }

  toggleNav(): void {
    this.nav?.toggle();
  }
}
