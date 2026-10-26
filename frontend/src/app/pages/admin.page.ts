import { HttpErrorResponse } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, DestroyRef, computed, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormControl, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { MatAutocompleteModule } from '@angular/material/autocomplete';
import { MatButtonModule } from '@angular/material/button';
import { MatDialog } from '@angular/material/dialog';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatSlideToggleModule } from '@angular/material/slide-toggle';

import { ApiClient } from '../core/api-client';
import { AdminSettings, PaymentTimingSettings } from '../core/api.models';
import { errorMessage } from '../core/http-errors';
import { Stores } from '../core/live-store';
import { ToastService } from '../core/toast.service';
import { AdminSaveDialog, AdminSaveDialogData, SettingChange } from '../dialogs/admin-save.dialog';
import { FORMAT_PIPES } from '../shared/format';
import { rememberReviewerName } from '../shared/reviewer-name-field.component';

/** Common US zones and UTC, offered first in the timezone picker. */
export const COMMON_ZONES: Record<string, string> = {
  'America/Chicago': 'Central Time',
  'America/New_York': 'Eastern Time',
  'America/Denver': 'Mountain Time',
  'America/Los_Angeles': 'Pacific Time',
  UTC: 'UTC',
};

export const DEFAULT_TIMING: PaymentTimingSettings = {
  delay_payments: true,
  pay_at_end_of_day: false,
  end_of_day_time: '17:00',
  end_of_day_timezone: 'America/Chicago',
  pay_when_queue_empty: true,
};

const FIELDS: Record<keyof PaymentTimingSettings, string> = {
  delay_payments: 'Delay payments',
  pay_at_end_of_day: 'Pay at end of day',
  end_of_day_time: 'End-of-day time',
  end_of_day_timezone: 'Timezone',
  pay_when_queue_empty: 'Pay when the Invoice Queue is empty',
};
const KEYS = Object.keys(FIELDS) as (keyof PaymentTimingSettings)[];
const HH_MM = /^([01]\d|2[0-3]):[0-5]\d$/;

/** Every IANA zone the browser knows, with the common ones first. */
export function timeZones(): string[] {
  const intl = Intl as unknown as { supportedValuesOf?: (key: string) => string[] };
  const all = intl.supportedValuesOf?.('timeZone') ?? [];
  const common = Object.keys(COMMON_ZONES);
  return [...common, ...all.filter((z) => !common.includes(z))];
}

/** `17:00` -> `5:00 PM`. */
export function clock(hhmm: string): string {
  const [h, m] = hhmm.split(':').map(Number);
  if (!HH_MM.test(hhmm)) return hhmm;
  return `${h % 12 || 12}:${String(m).padStart(2, '0')} ${h < 12 ? 'AM' : 'PM'}`;
}

export function zoneLabel(zone: string): string {
  return COMMON_ZONES[zone] ? `${COMMON_ZONES[zone]} (${zone})` : zone;
}

/** What the payment timing does, in one sentence. */
export function modeSentence(s: PaymentTimingSettings): string {
  if (!s.delay_payments) return 'Approved invoices are paid as soon as they are approved.';
  const ways = [
    ...(s.pay_at_end_of_day ? [`at ${clock(s.end_of_day_time)} ${zoneLabel(s.end_of_day_timezone)}`] : []),
    ...(s.pay_when_queue_empty ? ['when the Invoice Queue is empty'] : []),
  ];
  if (!ways.length) return 'Approved invoices wait in the Payment Queue until someone pays them there.';
  return `Approved invoices wait in the Payment Queue and are paid ${ways.join(', or ')}${ways.length > 1 ? ', whichever comes first' : ''}.`;
}

function display(key: keyof PaymentTimingSettings, value: unknown): string {
  if (typeof value === 'boolean') return value ? 'On' : 'Off';
  if (key === 'end_of_day_time') return clock(String(value));
  return String(value);
}

export function settingChanges(before: PaymentTimingSettings, after: PaymentTimingSettings): SettingChange[] {
  return KEYS.filter((k) => before[k] !== after[k]).map((k) => ({
    field: k,
    label: FIELDS[k],
    from: display(k, before[k]),
    to: display(k, after[k]),
  }));
}

function timing(s: PaymentTimingSettings): PaymentTimingSettings {
  return Object.fromEntries(KEYS.map((k) => [k, s[k]])) as unknown as PaymentTimingSettings;
}

/** F41: payment timing. Delay payments, end-of-day batch time and timezone, and pay when the queue empties. */
@Component({
  selector: 'app-admin-page',
  standalone: true,
  imports: [
    ReactiveFormsModule,
    MatAutocompleteModule,
    MatButtonModule,
    MatFormFieldModule,
    MatIconModule,
    MatInputModule,
    MatSlideToggleModule,
    ...FORMAT_PIPES,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="page">
      <header class="page-header">
        <div>
          <h1>Admin</h1>
          <p>When approved invoices are paid. Changes apply at once, with no restart, and are recorded in the audit log.</p>
        </div>
      </header>

      @if (changedElsewhere(); as other) {
        <div class="banner warn" role="alert" data-testid="changed-elsewhere">
          <mat-icon>sync_problem</mat-icon>
          <span>The settings were changed elsewhere{{ other.updated_by ? ' by ' + other.updated_by : '' }} while you were editing.</span>
          <button mat-stroked-button type="button" (click)="reload()" data-testid="reload">Reload settings</button>
        </div>
      }

      <section class="card" [formGroup]="form" data-testid="payment-timing">
        <h2>Payment timing</h2>
        <p class="mode" data-testid="mode">{{ mode() }}</p>

        <div class="setting">
          <mat-slide-toggle formControlName="delay_payments" data-testid="delay-toggle">Delay payments</mat-slide-toggle>
          <span class="muted small">On: approved invoices wait in the Payment Queue for a batch. Off: each one is paid as soon as it is approved.</span>
        </div>

        @if (value().delay_payments) {
          <div class="options" data-testid="batch-options">
            <div class="setting">
              <mat-slide-toggle formControlName="pay_at_end_of_day" data-testid="eod-toggle">Pay at end of day</mat-slide-toggle>
              <div class="row">
                <mat-form-field appearance="outline">
                  <mat-label>Time</mat-label>
                  <input matInput type="time" formControlName="end_of_day_time" data-testid="eod-time" />
                  <mat-hint data-testid="eod-time-hint">{{ clock(value().end_of_day_time) }}</mat-hint>
                  @if (form.controls.end_of_day_time.hasError('server')) {
                    <mat-error data-testid="eod-time-error">{{ form.controls.end_of_day_time.getError('server') }}</mat-error>
                  } @else {
                    <mat-error>Enter a time</mat-error>
                  }
                </mat-form-field>
                <mat-form-field appearance="outline" class="zone">
                  <mat-label>Timezone</mat-label>
                  <input matInput formControlName="end_of_day_timezone" [matAutocomplete]="zones" data-testid="eod-timezone" />
                  <mat-autocomplete #zones="matAutocomplete">
                    @for (z of zoneOptions(); track z) {
                      <mat-option [value]="z">{{ zoneLabel(z) }}</mat-option>
                    }
                  </mat-autocomplete>
                  <mat-hint data-testid="eod-timezone-hint">{{ zoneLabel(value().end_of_day_timezone) }}</mat-hint>
                  @if (form.controls.end_of_day_timezone.hasError('server')) {
                    <mat-error data-testid="eod-timezone-error">{{ form.controls.end_of_day_timezone.getError('server') }}</mat-error>
                  } @else {
                    <mat-error>Choose a timezone</mat-error>
                  }
                </mat-form-field>
              </div>
            </div>
            <div class="setting">
              <mat-slide-toggle formControlName="pay_when_queue_empty" data-testid="queue-empty-toggle">Pay when the Invoice Queue is empty</mat-slide-toggle>
              <span class="muted small">Pays everything queued once no invoice has been processing for a minute.</span>
            </div>
          </div>
        } @else if (paysQueue()) {
          <div class="banner warn" data-testid="pays-queue-warning">
            <mat-icon>warning</mat-icon>
            <span>Saving will pay everything currently queued in the Payment Queue right away.</span>
          </div>
        }

        <div class="actions">
          <span class="muted small" data-testid="last-saved">
            @if (loaded()?.updated_by) {
              Last saved by <b>{{ loaded()!.updated_by }}</b> · {{ loaded()!.updated_at | when }}
            } @else if (loaded()) {
              Never saved: these are the defaults.
            }
          </span>
          <span class="spacer"></span>
          <button mat-button type="button" [disabled]="!changes().length || saving()" (click)="discard()" data-testid="discard">Discard changes</button>
          <button mat-flat-button type="button" [disabled]="!canSave()" (click)="save()" data-testid="save">Save</button>
        </div>
      </section>
    </div>
  `,
  styles: `
    .card { max-width: 760px; padding: 20px 24px; border-radius: 12px; background: var(--ipa-surface); border: 1px solid var(--ipa-border); }
    h2 { margin: 0 0 4px; font-size: 18px; }
    .mode { margin: 0 0 16px; color: var(--ipa-muted); }
    .setting { display: flex; flex-direction: column; gap: 6px; margin-bottom: 16px; }
    .options { margin-left: 16px; padding-left: 16px; border-left: 3px solid var(--ipa-border); }
    .row { display: flex; flex-wrap: wrap; gap: 12px; margin-top: 8px; }
    .zone { min-width: 300px; }
    .banner { display: flex; align-items: center; gap: 10px; padding: 10px 14px; border-radius: 8px; margin-bottom: 16px; }
    .banner.warn { background: #fff4e0; color: #8a5a00; }
    .actions { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-top: 8px; }
    .spacer { flex: 1; }
  `,
})
export class AdminPage {
  private readonly api = inject(ApiClient);
  private readonly stores = inject(Stores);
  private readonly dialog = inject(MatDialog);
  private readonly toast = inject(ToastService);

  readonly clock = clock;
  readonly zoneLabel = zoneLabel;
  private readonly zones = timeZones();

  readonly form = new FormGroup({
    delay_payments: new FormControl(DEFAULT_TIMING.delay_payments, { nonNullable: true }),
    pay_at_end_of_day: new FormControl(DEFAULT_TIMING.pay_at_end_of_day, { nonNullable: true }),
    end_of_day_time: new FormControl(
      { value: DEFAULT_TIMING.end_of_day_time, disabled: true },
      { nonNullable: true, validators: [Validators.required, Validators.pattern(HH_MM)] },
    ),
    end_of_day_timezone: new FormControl(
      { value: DEFAULT_TIMING.end_of_day_timezone, disabled: true },
      { nonNullable: true, validators: [Validators.required] },
    ),
    pay_when_queue_empty: new FormControl(DEFAULT_TIMING.pay_when_queue_empty, { nonNullable: true }),
  });

  /** The settings as last loaded or saved; the form's changes are measured against them. */
  readonly loaded = signal<AdminSettings | null>(null);
  readonly value = signal<PaymentTimingSettings>(this.form.getRawValue());
  private readonly valid = signal(true);
  readonly saving = signal(false);
  /** Settings saved in another browser (or the CLI) while this form had unsaved edits. */
  readonly changedElsewhere = signal<AdminSettings | null>(null);

  readonly changes = computed(() => settingChanges(timing(this.loaded() ?? { ...DEFAULT_TIMING, updated_by: null, updated_at: null }), this.value()));
  readonly canSave = computed(() => !!this.loaded() && this.changes().length > 0 && this.valid() && !this.saving());
  readonly mode = computed(() => modeSentence(this.value()));
  readonly paysQueue = computed(() => !!this.loaded()?.delay_payments && !this.value().delay_payments);
  readonly zoneOptions = computed(() => {
    const q = this.value().end_of_day_timezone.trim().toLowerCase();
    const matches = this.zones.filter((z) => z.toLowerCase().includes(q) || zoneLabel(z).toLowerCase().includes(q));
    return matches.length && !this.zones.some((z) => z.toLowerCase() === q) ? matches : this.zones;
  });

  constructor() {
    const destroyRef = inject(DestroyRef);
    this.form.controls.pay_at_end_of_day.valueChanges
      .pipe(takeUntilDestroyed(destroyRef))
      .subscribe((on) => this.syncEnabled(on));
    this.form.valueChanges.pipe(takeUntilDestroyed(destroyRef)).subscribe(() => this.track());
    this.form.statusChanges.pipe(takeUntilDestroyed(destroyRef)).subscribe(() => this.track());
    this.stores.adminSettings.data$.pipe(takeUntilDestroyed(destroyRef)).subscribe((s) => this.onSettings(s));
  }

  /** Time and timezone are editable only while Pay at end of day is on; they keep their values when off. */
  private syncEnabled(on: boolean): void {
    for (const c of [this.form.controls.end_of_day_time, this.form.controls.end_of_day_timezone]) {
      if (on) c.enable({ emitEvent: false });
      else c.disable({ emitEvent: false });
    }
    this.track();
  }

  private track(): void {
    this.value.set(this.form.getRawValue());
    this.valid.set(this.form.valid || this.form.disabled);
  }

  private apply(s: AdminSettings): void {
    this.loaded.set(s);
    this.changedElsewhere.set(null);
    this.form.reset(timing(s), { emitEvent: false });
    this.syncEnabled(s.pay_at_end_of_day);
  }

  private onSettings(s: AdminSettings): void {
    const current = this.loaded();
    if (current && current.updated_at === s.updated_at && !settingChanges(timing(current), timing(s)).length) return;
    if (current && this.changes().length) this.changedElsewhere.set(s);
    else this.apply(s);
  }

  reload(): void {
    const other = this.changedElsewhere();
    if (other) this.apply(other);
  }

  discard(): void {
    const current = this.loaded();
    if (current) this.apply(current);
  }

  save(): void {
    if (!this.canSave()) return;
    this.dialog
      .open<AdminSaveDialog, AdminSaveDialogData, string>(AdminSaveDialog, {
        data: { changes: this.changes(), paysQueue: this.paysQueue() },
        width: '480px',
      })
      .afterClosed()
      .subscribe((name) => name && this.submit(name));
  }

  private submit(updated_by: string): void {
    this.saving.set(true);
    this.api.saveAdminSettings({ ...this.form.getRawValue(), updated_by }).subscribe({
      next: (saved) => {
        this.saving.set(false);
        rememberReviewerName(updated_by);
        this.apply(saved);
        this.stores.refresh('adminSettings', 'paymentQueue');
        this.toast.show(`Payment settings saved by ${saved.updated_by}.`);
      },
      error: (err: unknown) => {
        this.saving.set(false);
        if (!this.showFieldErrors(err)) this.toast.error(errorMessage(err));
      },
    });
  }

  /** A 422 names its field (`loc: ["body", field]`): show the message on that field. */
  private showFieldErrors(err: unknown): boolean {
    if (!(err instanceof HttpErrorResponse) || err.status !== 422 || !Array.isArray(err.error?.detail)) return false;
    let shown = false;
    for (const d of err.error.detail as { loc?: unknown[]; msg?: string }[]) {
      const control = this.form.get(String(d.loc?.[1] ?? ''));
      if (!control) continue;
      control.setErrors({ server: String(d.msg ?? 'Invalid value').replace(/^Value error, /, '') });
      control.markAsTouched();
      shown = true;
    }
    this.track();
    return shown;
  }
}
