import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';
import { MatTooltipModule } from '@angular/material/tooltip';

export const STAGES = ['Uploaded', 'Extracting', 'Validating', 'Deciding', 'Awaiting review'] as const;

/** The Invoice Queue's 5-step progress strip. Steps before the current one are done. */
@Component({
  selector: 'app-stage-strip',
  standalone: true,
  imports: [MatTooltipModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="strip" [attr.aria-label]="'Stage: ' + (stage() ?? 'unknown')" role="img">
      @for (s of stages; track s; let i = $index) {
        <span
          class="step"
          [class.done]="i < current()"
          [class.current]="i === current()"
          [class.hold]="i === current() && s === 'Awaiting review'"
          [matTooltip]="s"
          [attr.data-stage]="s"
        ></span>
      }
    </div>
    <div class="label">{{ stage() }}</div>
  `,
  styles: `
    :host { display: inline-block; min-width: 140px; }
    .strip { display: flex; gap: 3px; }
    .step { flex: 1; height: 6px; border-radius: 3px; background: #e0e5ee; }
    .step.done { background: #64b5f6; }
    .step.current { background: #1565c0; animation: pulse 1.6s ease-in-out infinite; }
    .step.hold { background: #f9a825; animation: none; }
    .label { font-size: 12px; color: var(--ipa-muted); margin-top: 4px; }
    @keyframes pulse { 50% { opacity: .55; } }
  `,
})
export class StageStripComponent {
  readonly stage = input<string | null>();
  readonly stages = STAGES;
  readonly current = computed(() => STAGES.indexOf((this.stage() ?? 'Uploaded') as (typeof STAGES)[number]));
}
