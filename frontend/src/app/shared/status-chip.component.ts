import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';
import { MatIconModule } from '@angular/material/icon';

import { statusStyle } from './status';

@Component({
  selector: 'app-status-chip',
  standalone: true,
  imports: [MatIconModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <span class="chip" [style.background]="style().bg" [style.color]="style().fg" [attr.data-status]="style().label">
      <mat-icon inline>{{ style().icon }}</mat-icon>{{ style().label }}
    </span>
  `,
  styles: `
    .chip {
      display: inline-flex;
      align-items: center;
      gap: 4px;
      padding: 2px 10px 2px 8px;
      border-radius: 12px;
      font-size: 12px;
      font-weight: 500;
      line-height: 20px;
      white-space: nowrap;
    }
  `,
})
export class StatusChipComponent {
  readonly status = input<string | null>();
  readonly style = computed(() => statusStyle(this.status()));
}
