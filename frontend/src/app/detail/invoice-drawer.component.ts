import { ChangeDetectionStrategy, Component, DestroyRef, OnChanges, computed, inject, input, output, signal } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatTabsModule } from '@angular/material/tabs';
import { DomSanitizer, SafeResourceUrl } from '@angular/platform-browser';
import { EMPTY, Subscription, from, switchMap } from 'rxjs';

import { ApiClient } from '../core/api-client';
import { InvoiceDetail } from '../core/api.models';
import { LiveStore, PollTicker } from '../core/live-store';
import { FORMAT_PIPES } from '../shared/format';
import { StatusChipComponent } from '../shared/status-chip.component';
import { RunTimelineComponent } from './run-timeline.component';

const TEXT_FORMATS = new Set(['txt', 'csv', 'json', 'xml', 'eml']);

/** F30: original file beside the extracted fields, findings, and the full stage timeline. */
@Component({
  selector: 'app-invoice-drawer',
  standalone: true,
  imports: [
    MatButtonModule,
    MatIconModule,
    MatProgressBarModule,
    MatTabsModule,
    StatusChipComponent,
    RunTimelineComponent,
    ...FORMAT_PIPES,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './invoice-drawer.component.html',
  styleUrl: './invoice-drawer.component.scss',
})
export class InvoiceDrawerComponent implements OnChanges {
  private readonly api = inject(ApiClient);
  private readonly sanitizer = inject(DomSanitizer);
  private readonly store = new LiveStore<InvoiceDetail, string>(inject(PollTicker).tick$, (id) => (id ? this.api.invoice(id) : EMPTY), '');

  readonly invoiceId = input.required<string>();
  readonly closed = output<void>();

  readonly detail = toSignal(this.store.data$);
  readonly current = computed(() => {
    const d = this.detail();
    return d && d.id === this.invoiceId() ? d : null;
  });
  readonly preview = signal<{ kind: 'text'; text: string } | { kind: 'pdf'; url: SafeResourceUrl } | { kind: 'none' } | null>(
    null,
  );
  readonly status = computed(() => {
    const d = this.current();
    return d ? (d.final_status ?? d.status) : null;
  });

  private previewSub?: Subscription;
  private objectUrl?: string;

  constructor() {
    inject(DestroyRef).onDestroy(() => this.revoke());
  }

  ngOnChanges(): void {
    const id = this.invoiceId();
    this.store.setParams(id);
    this.loadPreview(id);
  }

  fileUrl(): string {
    return this.api.fileUrl(this.invoiceId());
  }

  private loadPreview(id: string): void {
    this.previewSub?.unsubscribe();
    this.revoke();
    this.preview.set(null);
    this.previewSub = this.api
      .file(id)
      .pipe(switchMap((blob) => from(this.toPreview(blob))))
      .subscribe({ next: (p) => this.preview.set(p), error: () => this.preview.set({ kind: 'none' }) });
  }

  private async toPreview(blob: Blob) {
    const ext = this.current()?.format ?? '';
    const type = blob.type || '';
    if (type.includes('pdf') || ext === 'pdf') {
      this.objectUrl = URL.createObjectURL(new Blob([blob], { type: 'application/pdf' }));
      return { kind: 'pdf' as const, url: this.sanitizer.bypassSecurityTrustResourceUrl(this.objectUrl) };
    }
    if (type.startsWith('text/') || /json|xml|rfc822/.test(type) || TEXT_FORMATS.has(ext)) {
      return { kind: 'text' as const, text: await blob.text() };
    }
    return { kind: 'none' as const };
  }

  private revoke(): void {
    if (this.objectUrl) URL.revokeObjectURL(this.objectUrl);
    this.objectUrl = undefined;
  }

  lineItems() {
    return this.current()?.invoice?.line_items ?? [];
  }
}
