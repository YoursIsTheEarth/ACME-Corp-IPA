import { ChangeDetectionStrategy, Component, computed, forwardRef, input, signal } from '@angular/core';
import {
  AbstractControl,
  ControlValueAccessor,
  FormControl,
  NG_VALIDATORS,
  NG_VALUE_ACCESSOR,
  ReactiveFormsModule,
  ValidationErrors,
  Validator,
} from '@angular/forms';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';

export const NAME_MAX = 50;
export const NAME_STORAGE_KEY = 'acme-ipa.reviewer-name';

/** Required, 1 to 50 characters after trimming (the backend repeats this check). */
export function reviewerNameValidator(control: AbstractControl): ValidationErrors | null {
  const value = String(control.value ?? '').trim();
  if (!value) return { required: true };
  if (value.length > NAME_MAX) return { maxlength: { requiredLength: NAME_MAX, actualLength: value.length } };
  return null;
}

/** The last name used in this browser; empty when storage is blocked. */
export function loadReviewerName(): string {
  try {
    return localStorage.getItem(NAME_STORAGE_KEY) ?? '';
  } catch {
    return '';
  }
}

/** Remember a name the server accepted. */
export function rememberReviewerName(name: string): void {
  try {
    localStorage.setItem(NAME_STORAGE_KEY, name.trim());
  } catch {
    /* storage blocked: the field simply starts empty next time */
  }
}

/** Shared name field for the review and pay dialogs: trim + 1..50 validation, counter, browser prefill. */
@Component({
  selector: 'app-reviewer-name-field',
  standalone: true,
  imports: [ReactiveFormsModule, MatFormFieldModule, MatInputModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  providers: [
    { provide: NG_VALUE_ACCESSOR, useExisting: forwardRef(() => ReviewerNameFieldComponent), multi: true },
    { provide: NG_VALIDATORS, useExisting: forwardRef(() => ReviewerNameFieldComponent), multi: true },
  ],
  template: `
    <mat-form-field appearance="outline" class="full">
      <mat-label>{{ label() }}</mat-label>
      <input matInput [formControl]="inner" autocomplete="name" (blur)="onTouched()" data-testid="name-input" />
      <mat-hint align="end" data-testid="name-counter">{{ left() }} characters left</mat-hint>
      @if (inner.hasError('required')) {
        <mat-error>Your name is required</mat-error>
      } @else if (inner.hasError('maxlength')) {
        <mat-error data-testid="name-over">Use {{ max }} characters or fewer ({{ -left() }} over)</mat-error>
      }
    </mat-form-field>
  `,
  styles: `.full { width: 100%; }`,
})
export class ReviewerNameFieldComponent implements ControlValueAccessor, Validator {
  readonly label = input('Your name');
  readonly max = NAME_MAX;
  readonly inner = new FormControl('', { nonNullable: true, validators: reviewerNameValidator });
  private readonly length = signal(0);
  readonly left = computed(() => NAME_MAX - this.length());

  private onChange: (value: string) => void = () => {};
  onTouched: () => void = () => {};
  private prefilled: string | null = null;

  constructor() {
    this.inner.valueChanges.subscribe((value) => {
      this.length.set(value.trim().length);
      this.onChange(value);
    });
  }

  writeValue(value: string | null): void {
    let next = value ?? '';
    if (!next.trim()) {
      const stored = loadReviewerName();
      if (stored) {
        next = stored;
        this.prefilled = stored;
      }
    }
    this.inner.setValue(next, { emitEvent: false });
    this.length.set(next.trim().length);
  }

  registerOnChange(fn: (value: string) => void): void {
    this.onChange = fn;
    if (this.prefilled !== null) {
      fn(this.prefilled); // push the remembered name to the parent form
      this.prefilled = null;
    }
  }

  registerOnTouched(fn: () => void): void {
    this.onTouched = () => {
      this.inner.markAsTouched();
      fn();
    };
  }

  setDisabledState(disabled: boolean): void {
    if (disabled) this.inner.disable({ emitEvent: false });
    else this.inner.enable({ emitEvent: false });
  }

  validate(control: AbstractControl): ValidationErrors | null {
    return reviewerNameValidator(control);
  }
}
