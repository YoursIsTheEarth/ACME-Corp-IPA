import { DecimalPipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { Router, RouterLink } from '@angular/router';

import { Stores } from '../../core/live-store';
import { ToastService } from '../../core/toast.service';
import { UploadService } from '../../core/upload.service';
import { DropZoneComponent } from './drop-zone.component';

@Component({
  selector: 'app-home-page',
  standalone: true,
  imports: [DecimalPipe, RouterLink, MatButtonModule, MatIconModule, MatProgressBarModule, DropZoneComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './home.page.html',
  styleUrl: './home.page.scss',
})
export class HomePage {
  private readonly uploads = inject(UploadService);
  private readonly toast = inject(ToastService);
  private readonly router = inject(Router);

  readonly items = this.uploads.items;
  readonly stats = toSignal(inject(Stores).stats.data$);
  readonly lastAccepted = signal<number | null>(null);

  onFiles(files: File[]): void {
    this.uploads.add(files).subscribe(({ accepted }) => {
      this.lastAccepted.set(accepted);
      const message = `${accepted} file${accepted === 1 ? ' was' : 's were'} accepted`;
      const ref = this.toast.show(message, accepted ? 'View in Invoice Queue' : 'Dismiss');
      if (accepted) ref.onAction().subscribe(() => this.router.navigate(['/queue']));
    });
  }

  clear(): void {
    this.uploads.clear();
    this.lastAccepted.set(null);
  }

  size(bytes: number): string {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  }
}
