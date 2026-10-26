import { OverlayContainer } from '@angular/cdk/overlay';
import { TestBed } from '@angular/core/testing';
import { provideNoopAnimations } from '@angular/platform-browser/animations';

import { ToastService } from './toast.service';

describe('ToastService', () => {
  it('shows the message text', () => {
    TestBed.configureTestingModule({ providers: [provideNoopAnimations()] });
    const toast = TestBed.inject(ToastService);
    const overlay = TestBed.inject(OverlayContainer).getContainerElement();

    const ref = toast.show('2 files accepted', 'View in Invoice Queue');
    TestBed.flushEffects();
    ref.containerInstance.enter();

    expect(overlay.textContent).toContain('2 files accepted');
    expect(overlay.textContent).toContain('View in Invoice Queue');
    ref.dismiss();
  });
});
