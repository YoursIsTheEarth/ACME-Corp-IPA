import { Injectable, inject } from '@angular/core';
import { Router } from '@angular/router';

/** The detail drawer lives in the `?invoice=<id>` query param, so it deep-links and Back closes it. */
@Injectable({ providedIn: 'root' })
export class DetailDrawer {
  private readonly router = inject(Router);

  open(id: string | null | undefined): void {
    if (id) this.router.navigate([], { queryParams: { invoice: id }, queryParamsHandling: 'merge' });
  }

  close(): void {
    this.router.navigate([], { queryParams: { invoice: null }, queryParamsHandling: 'merge' });
  }
}
