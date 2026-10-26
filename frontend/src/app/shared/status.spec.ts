import { TestBed } from '@angular/core/testing';

import { STATUSES, STATUS_STYLE, statusStyle } from './status';
import { StatusChipComponent } from './status-chip.component';

describe('STATUS_STYLE', () => {
  it('has exactly one style per status in the spec, each distinct', () => {
    expect(Object.keys(STATUS_STYLE).sort()).toEqual([...STATUSES].sort());
    const colors = STATUSES.map((s) => STATUS_STYLE[s].bg);
    expect(new Set(colors).size).toBe(STATUSES.length);
    for (const s of STATUSES) expect(STATUS_STYLE[s].label).toBe(s);
  });

  it('maps lower-case payment statuses to the same style', () => {
    expect(statusStyle('queued')).toBe(STATUS_STYLE.Queued);
    expect(statusStyle('paying')).toBe(STATUS_STYLE.Paying);
    expect(statusStyle('failed')).toBe(STATUS_STYLE.Failed);
    expect(statusStyle('Something new').label).toBe('Something new');
  });

  it('renders the same chip for the same status', () => {
    const a = TestBed.createComponent(StatusChipComponent);
    a.componentRef.setInput('status', 'Awaiting review');
    a.detectChanges();
    const chip = a.nativeElement.querySelector('.chip') as HTMLElement;
    expect(chip.textContent).toContain('Awaiting review');
    expect(chip.style.background).toBeTruthy();
  });
});
