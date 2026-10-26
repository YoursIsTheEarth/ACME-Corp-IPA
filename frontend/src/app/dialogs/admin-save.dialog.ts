import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { FormControl, ReactiveFormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MAT_DIALOG_DATA, MatDialogModule, MatDialogRef } from '@angular/material/dialog';

import { ReviewerNameFieldComponent } from '../shared/reviewer-name-field.component';

export interface SettingChange {
  field: string;
  label: string;
  from: string;
  to: string;
}

export interface AdminSaveDialogData {
  changes: SettingChange[];
  /** Delay is being turned off: saving pays everything queued. */
  paysQueue: boolean;
}

/** F41: the change summary and the saver's name. Closes with the trimmed name; the page sends the PUT. */
@Component({
  selector: 'app-admin-save-dialog',
  standalone: true,
  imports: [ReactiveFormsModule, MatDialogModule, MatButtonModule, ReviewerNameFieldComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <h2 mat-dialog-title>Save payment settings</h2>
    <mat-dialog-content>
      <ul class="changes" data-testid="change-summary">
        @for (c of data.changes; track c.field) {
          <li><b>{{ c.label }}</b>: {{ c.from }} → {{ c.to }}</li>
        }
      </ul>
      @if (data.paysQueue) {
        <div class="banner warn" data-testid="dialog-pays-queue">Saving pays everything currently in the Payment Queue right away.</div>
      }
      <app-reviewer-name-field [formControl]="name" label="Saved by (your name)" />
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      <button mat-button type="button" mat-dialog-close>Cancel</button>
      <button mat-flat-button type="button" (click)="confirm()" [disabled]="name.invalid" data-testid="confirm">Save</button>
    </mat-dialog-actions>
  `,
  styles: `
    .changes { padding-left: 18px; margin: 0 0 12px; line-height: 1.7; }
    .banner { padding: 8px 12px; border-radius: 8px; margin-bottom: 12px; }
    .banner.warn { background: #fff4e0; color: #8a5a00; }
  `,
})
export class AdminSaveDialog {
  private readonly ref = inject(MatDialogRef<AdminSaveDialog, string>);
  readonly data = inject<AdminSaveDialogData>(MAT_DIALOG_DATA);
  readonly name = new FormControl('', { nonNullable: true });

  confirm(): void {
    if (this.name.invalid) return;
    this.ref.close(this.name.value.trim());
  }
}
