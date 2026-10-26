import { TestBed } from '@angular/core/testing';

import { DropZoneComponent } from './drop-zone.component';

describe('DropZoneComponent', () => {
  function drag(type: string, files: File[] = []): DragEvent {
    const dt = new DataTransfer();
    files.forEach((f) => dt.items.add(f));
    return new DragEvent(type, { dataTransfer: dt, bubbles: true, cancelable: true });
  }

  it('highlights while files hover and emits every dropped file', () => {
    const fixture = TestBed.createComponent(DropZoneComponent);
    const emitted: File[][] = [];
    fixture.componentInstance.files.subscribe((f) => emitted.push(f));
    fixture.detectChanges();
    const zone = fixture.nativeElement.querySelector('[data-testid=drop-zone]') as HTMLElement;

    zone.dispatchEvent(drag('dragover'));
    fixture.detectChanges();
    expect(zone.classList).toContain('hover');

    zone.dispatchEvent(drag('dragleave'));
    fixture.detectChanges();
    expect(zone.classList).not.toContain('hover');

    zone.dispatchEvent(drag('dragenter'));
    const files = [new File(['a'], 'a.txt'), new File(['b'], 'b.pdf'), new File(['c'], 'c.csv')];
    const drop = drag('drop', files);
    zone.dispatchEvent(drop);
    fixture.detectChanges();
    expect(drop.defaultPrevented).toBeTrue();
    expect(zone.classList).not.toContain('hover');
    expect(emitted.length).toBe(1);
    expect(emitted[0].map((f) => f.name)).toEqual(['a.txt', 'b.pdf', 'c.csv']);
  });

  it('opens a multi-select picker limited to the supported types', () => {
    const fixture = TestBed.createComponent(DropZoneComponent);
    fixture.detectChanges();
    const input = fixture.nativeElement.querySelector('[data-testid=file-input]') as HTMLInputElement;
    expect(input.multiple).toBeTrue();
    expect(input.accept).toBe('.pdf,.txt,.csv,.json,.xml,.eml');
    const click = spyOn(input, 'click');
    (fixture.nativeElement.querySelector('[data-testid=browse]') as HTMLButtonElement).click();
    expect(click).toHaveBeenCalled();
  });

  it('accepts nothing and explains why while disabled', () => {
    const fixture = TestBed.createComponent(DropZoneComponent);
    const emitted: File[][] = [];
    fixture.componentInstance.files.subscribe((f) => emitted.push(f));
    const reason = 'No LLM token provided — the app cannot process invoices without it. Set XAI_API_KEY in .env and restart the backend.';
    fixture.componentRef.setInput('disabledReason', reason);
    fixture.detectChanges();
    const el = fixture.nativeElement as HTMLElement;
    const zone = el.querySelector('[data-testid=drop-zone]') as HTMLElement;
    expect(zone.classList).toContain('disabled');
    expect(el.querySelector('[data-testid=drop-zone-disabled]')!.textContent).toContain(reason);
    expect((el.querySelector('[data-testid=browse]') as HTMLButtonElement).disabled).toBeTrue();

    zone.dispatchEvent(drag('dragover'));
    fixture.detectChanges();
    expect(zone.classList).not.toContain('hover');
    zone.dispatchEvent(drag('drop', [new File(['a'], 'a.txt')]));
    expect(emitted).toEqual([]);

    fixture.componentRef.setInput('disabledReason', null);
    fixture.detectChanges();
    expect(zone.classList).not.toContain('disabled');
    expect((el.querySelector('[data-testid=browse]') as HTMLButtonElement).disabled).toBeFalse();
  });
});
