import { ChangeDetectionStrategy, Component, ElementRef, ViewChild, output, signal } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';

import { ACCEPTED_EXTENSIONS } from '../../core/upload.service';

/** Drag-and-drop target plus a Browse button; emits the chosen files. Highlights while files hover. */
@Component({
  selector: 'app-drop-zone',
  standalone: true,
  imports: [MatButtonModule, MatIconModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div
      class="zone"
      [class.hover]="hover()"
      (dragenter)="onDragOver($event)"
      (dragover)="onDragOver($event)"
      (dragleave)="onDragLeave($event)"
      (drop)="onDrop($event)"
      data-testid="drop-zone"
    >
      <mat-icon class="big">cloud_upload</mat-icon>
      <div class="title">Drop invoice files here</div>
      <div class="muted">One or many · {{ accept.split(',').join(' ') }} · up to 10 MB each</div>
      <button mat-flat-button type="button" (click)="input.click()" data-testid="browse">
        <mat-icon>folder_open</mat-icon> Browse
      </button>
      <input #input type="file" multiple [accept]="accept" hidden (change)="onPick(input)" data-testid="file-input" />
    </div>
  `,
  styles: `
    .zone {
      display: flex; flex-direction: column; align-items: center; gap: 8px;
      padding: 40px 24px; border: 2px dashed #b6c3d9; border-radius: 16px;
      background: var(--ipa-surface); text-align: center; transition: background .15s, border-color .15s;
    }
    .zone.hover { border-color: var(--ipa-accent); background: #e8f1fd; }
    .big { font-size: 48px; width: 48px; height: 48px; color: var(--ipa-accent); }
    .title { font-size: 18px; font-weight: 600; }
    button { margin-top: 8px; }
  `,
})
export class DropZoneComponent {
  readonly files = output<File[]>();
  readonly hover = signal(false);
  readonly accept = ACCEPTED_EXTENSIONS.join(',');
  @ViewChild('input') inputRef?: ElementRef<HTMLInputElement>;

  onDragOver(event: DragEvent): void {
    event.preventDefault();
    if (event.dataTransfer) event.dataTransfer.dropEffect = 'copy';
    this.hover.set(true);
  }

  onDragLeave(event: DragEvent): void {
    const zone = event.currentTarget as HTMLElement;
    if (!event.relatedTarget || !zone.contains(event.relatedTarget as Node)) this.hover.set(false);
  }

  onDrop(event: DragEvent): void {
    event.preventDefault();
    this.hover.set(false);
    const files = Array.from(event.dataTransfer?.files ?? []);
    if (files.length) this.files.emit(files);
  }

  onPick(input: HTMLInputElement): void {
    const files = Array.from(input.files ?? []);
    input.value = '';
    if (files.length) this.files.emit(files);
  }
}
