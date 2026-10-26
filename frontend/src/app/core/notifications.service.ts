import { DestroyRef, Injectable, inject } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';

import { BatchFinishedEvent, BatchRow, PaymentQueueRow, PaymentQueuedEvent } from './api.models';
import { EventStreamService } from './event-stream.service';
import { Stores } from './live-store';
import { ToastService } from './toast.service';
import { usd } from '../shared/format';

export const SWAP_FALLBACK_MS = 1500;

/** "$37,620" for whole dollars, "$37,620.50" otherwise (the batch toast format in the spec). */
export function shortUsd(value: string | number): string {
  const n = Number(value);
  return Number.isInteger(n) ? `$${n.toLocaleString('en-US')}` : usd(value);
}

export function batchMessage(b: { batch_id: string; count: number; total_usd: string; failed_count: number }): string {
  return `Batch ${b.batch_id}: ${b.count} paid, ${shortUsd(b.total_usd)}, ${b.failed_count} failed`;
}

export function swapMessage(r: { invoice_number: string; revision?: number | null; amount_usd: string }): string {
  const label = r.revision ? `${r.invoice_number} R${r.revision}` : `${r.invoice_number} revision`;
  return `${label} replaced the queued original ${r.invoice_number}; it will pay ${usd(r.amount_usd)}.`;
}

/**
 * App-wide toasts that are not tied to a page: batch summaries and revision swaps in the Payment
 * Queue. Each fires from the SSE event when the stream is up, else from diffs of the polled lists;
 * ids are remembered so a toast never fires twice.
 */
@Injectable({ providedIn: 'root' })
export class NotificationsService {
  private readonly stores = inject(Stores);
  private readonly toast = inject(ToastService);
  private readonly stream = inject(EventStreamService);

  private readonly toastedBatches = new Set<string>();
  private readonly toastedSwaps = new Set<number>();
  private batchesSeeded = false;
  private previousQueue: PaymentQueueRow[] | null = null;

  start(destroyRef: DestroyRef): void {
    this.stream.events$.pipe(takeUntilDestroyed(destroyRef)).subscribe(({ name, data }) => {
      if (name === 'batch.finished') this.onBatchFinished(data as BatchFinishedEvent);
      if (name === 'payment.queued' && (data as PaymentQueuedEvent).kind === 'replacement') {
        // The event triggers an immediate Payment Queue refresh, whose diff toasts with the revision
        // number; this fallback covers a refresh that never saw the original row.
        const e = data as PaymentQueuedEvent;
        setTimeout(() => this.onSwap(e.row_id, { invoice_number: e.invoice_number, amount_usd: e.amount_usd }), SWAP_FALLBACK_MS);
      }
    });
    this.stores.batches.data$
      .pipe(takeUntilDestroyed(destroyRef))
      .subscribe((res) => this.onBatches(res.rows));
    this.stores.paymentQueue.data$
      .pipe(takeUntilDestroyed(destroyRef))
      .subscribe((res) => this.onQueue(res.rows));
  }

  onBatches(rows: BatchRow[]): void {
    const finished = rows.filter((b) => b.finished_at);
    if (!this.batchesSeeded) {
      // Batches that finished before the app opened are history, not news.
      this.batchesSeeded = true;
      finished.forEach((b) => this.toastedBatches.add(b.batch_id));
      return;
    }
    for (const b of finished) this.onBatchFinished(b);
  }

  onBatchFinished(b: BatchFinishedEvent | BatchRow): void {
    if (this.toastedBatches.has(b.batch_id)) return;
    this.toastedBatches.add(b.batch_id);
    this.toast.show(batchMessage(b), 'Dismiss', 8000);
  }

  onQueue(rows: PaymentQueueRow[]): void {
    const previous = this.previousQueue;
    this.previousQueue = rows;
    if (!previous) return;
    const before = new Set(previous.map((r) => r.id));
    const now = new Set(rows.map((r) => r.id));
    const removed = previous.filter((r) => !now.has(r.id));
    for (const row of rows) {
      if (before.has(row.id) || row.kind !== 'replacement') continue;
      if (removed.some((r) => r.invoice_number === row.invoice_number && r.revision < row.revision)) {
        this.onSwap(row.id, row);
      }
    }
  }

  private onSwap(rowId: number, r: { invoice_number: string; revision?: number | null; amount_usd: string }): void {
    if (this.toastedSwaps.has(rowId)) return;
    this.toastedSwaps.add(rowId);
    this.toast.show(swapMessage(r), 'Dismiss', 8000);
  }
}
