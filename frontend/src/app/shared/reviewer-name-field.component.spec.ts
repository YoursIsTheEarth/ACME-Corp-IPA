import { Component } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { FormControl, ReactiveFormsModule } from '@angular/forms';
import { provideNoopAnimations } from '@angular/platform-browser/animations';

import {
  NAME_STORAGE_KEY,
  ReviewerNameFieldComponent,
  loadReviewerName,
  rememberReviewerName,
} from './reviewer-name-field.component';

@Component({
  standalone: true,
  imports: [ReactiveFormsModule, ReviewerNameFieldComponent],
  template: `<app-reviewer-name-field [formControl]="name" />`,
})
class HostComponent {
  name = new FormControl('', { nonNullable: true });
}

describe('ReviewerNameFieldComponent', () => {
  let fixture: ComponentFixture<HostComponent>;
  let host: HostComponent;

  function create(): void {
    fixture = TestBed.createComponent(HostComponent);
    host = fixture.componentInstance;
    fixture.detectChanges();
  }

  function type(value: string): void {
    const input = fixture.nativeElement.querySelector('input') as HTMLInputElement;
    input.value = value;
    input.dispatchEvent(new Event('input'));
    input.dispatchEvent(new Event('blur'));
    fixture.detectChanges();
  }

  beforeEach(() => {
    localStorage.removeItem(NAME_STORAGE_KEY);
    TestBed.configureTestingModule({ imports: [HostComponent], providers: [provideNoopAnimations()] });
  });

  afterEach(() => localStorage.removeItem(NAME_STORAGE_KEY));

  it('rejects a name of only spaces as required', () => {
    create();
    type('    ');
    expect(host.name.invalid).toBeTrue();
    expect(host.name.hasError('required')).toBeTrue();
    expect(fixture.nativeElement.textContent).toContain('Your name is required');
  });

  it('rejects 51 characters', () => {
    create();
    type('x'.repeat(51));
    expect(host.name.hasError('maxlength')).toBeTrue();
    expect(fixture.nativeElement.textContent).toContain('Use 50 characters or fewer');
    expect(fixture.nativeElement.querySelector('[data-testid=name-over]').textContent).toContain('(1 over)');
  });

  it('accepts 50 characters padded with spaces and counts the trimmed length', () => {
    create();
    type('  ' + 'y'.repeat(50) + '  ');
    expect(host.name.valid).toBeTrue();
    expect(fixture.nativeElement.querySelector('[data-testid=name-counter]').textContent).toContain('0 characters left');
  });

  it('prefills the last name used in this browser', () => {
    rememberReviewerName('  Dana Reyes ');
    create();
    expect(host.name.value).toBe('Dana Reyes');
    expect(host.name.valid).toBeTrue();
    expect((fixture.nativeElement.querySelector('input') as HTMLInputElement).value).toBe('Dana Reyes');
  });

  it('starts empty when storage throws', () => {
    spyOn(Storage.prototype, 'getItem').and.throwError('blocked');
    spyOn(Storage.prototype, 'setItem').and.throwError('blocked');
    expect(loadReviewerName()).toBe('');
    expect(() => rememberReviewerName('Dana')).not.toThrow();
    create();
    expect(host.name.value).toBe('');
    expect(host.name.hasError('required')).toBeTrue();
  });
});
