import { HttpErrorResponse } from '@angular/common/http';
import { Type } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { MAT_DIALOG_DATA, MatDialogRef } from '@angular/material/dialog';
import { provideNoopAnimations } from '@angular/platform-browser/animations';
import { Observable, of, throwError } from 'rxjs';

import { ApiClient } from '../core/api-client';
import { PaymentQueueRow, ReviewRow } from '../core/api.models';
import { Stores } from '../core/live-store';
import { ToastService } from '../core/toast.service';
import { NAME_STORAGE_KEY } from '../shared/reviewer-name-field.component';
import { PayConfirmDialog, PayScope } from './pay-confirm.dialog';
import { ReviewDecisionDialog } from './review-decision.dialog';

function reviewRow(partial: Partial<ReviewRow> = {}): ReviewRow {
  return {
    id: 'run-1010',
    file_name: 'invoice_1010.txt',
    format: 'txt',
    invoice_number: 'INV-1010',
    vendor: 'Consolidated Materials Group',
    amount_usd: '7185.00',
    stage: 'Awaiting review',
    status: 'Awaiting review',
    final_status: null,
    decided_by: null,
    uploaded_at: '',
    completed_at: null,
    stage_entered_at: null,
    time_in_stage_s: 1,
    processing_s: null,
    hold_kind: 'warning',
    reason: 'PRICE_VARIANCE: Line 4 WidgetA: billed 300.00 vs reference 250.00 (+20.0%)',
    detail: null,
    last_error: null,
    attempts: null,
    findings: [{ code: 'PRICE_VARIANCE', severity: 'WARNING', message: 'Line 4 WidgetA +20%' }],
    ai_recommendation: 'NEEDS_REVIEW',
    ai_rationale: 'Confirm the price with the vendor.',
    overpaid_usd: null,
    paid_amount_usd: null,
    payee_threshold: null,
    pulled: false,
    waiting_since: null,
    waiting_s: 3,
    ...partial,
  };
}

function queueRow(id: number, amount: string): PaymentQueueRow {
  return {
    id,
    run_id: `run-${id}`,
    file_name: null,
    invoice_number: `INV-${1000 + id}`,
    revision: 0,
    vendor: 'Widgets Inc.',
    amount_usd: amount,
    kind: 'full',
    approved_by: 'Auto (rules)',
    queued_at: '',
    status: 'queued',
    attempts: 0,
    last_error: null,
    batch_id: null,
  };
}

const conflict = () => throwError(() => new HttpErrorResponse({ status: 409, error: { detail: { message: 'x' } } }));

describe('dialogs', () => {
  let api: jasmine.SpyObj<ApiClient>;
  let refreshed: string[];
  let toasts: string[];
  let closedWith: unknown;

  function setup<T>(component: Type<T>, data: unknown): ComponentFixture<T> {
    TestBed.configureTestingModule({
      imports: [component],
      providers: [
        provideNoopAnimations(),
        { provide: ApiClient, useValue: api },
        { provide: Stores, useValue: { refresh: (...n: string[]) => refreshed.push(...n) } },
        { provide: ToastService, useValue: { show: (m: string) => toasts.push(m) } },
        { provide: MatDialogRef, useValue: { close: (v: unknown) => (closedWith = v) } },
        { provide: MAT_DIALOG_DATA, useValue: data },
      ],
    });
    const fixture = TestBed.createComponent(component);
    fixture.detectChanges();
    return fixture;
  }

  function type(fixture: ComponentFixture<unknown>, selector: string, value: string): void {
    const input = fixture.nativeElement.querySelector(selector) as HTMLInputElement;
    input.value = value;
    input.dispatchEvent(new Event('input'));
    fixture.detectChanges();
  }

  const confirmButton = (f: ComponentFixture<unknown>) => f.nativeElement.querySelector('[data-testid=confirm]') as HTMLButtonElement;

  beforeEach(() => {
    localStorage.removeItem(NAME_STORAGE_KEY);
    api = jasmine.createSpyObj<ApiClient>('ApiClient', ['submitReview', 'executeBatch']);
    refreshed = [];
    toasts = [];
    closedWith = undefined;
  });

  afterEach(() => localStorage.removeItem(NAME_STORAGE_KEY));

  describe('ReviewDecisionDialog', () => {
    it('keeps confirm disabled until name and 15-character rationale are valid, then approves', () => {
      api.submitReview.and.returnValue(of({ id: 'run-1010', decision: 'approve', reviewer: 'Dana Reyes', status: 'Resuming' }));
      const f = setup(ReviewDecisionDialog, { row: reviewRow(), decision: 'approve' });
      const text = f.nativeElement.textContent;
      expect(text).toContain('Approve INV-1010');
      expect(text).toContain('Price variance');
      expect(text).toContain('AI recommends NEEDS_REVIEW');
      expect(confirmButton(f).disabled).toBeTrue();

      type(f, '[data-testid=name-input]', '  Dana Reyes ');
      type(f, '[data-testid=rationale]', 'looks fine');
      expect(confirmButton(f).disabled).toBeTrue();
      type(f, '[data-testid=rationale]', 'Rush pricing agreed by procurement');
      expect(confirmButton(f).disabled).toBeFalse();

      confirmButton(f).click();
      expect(api.submitReview).toHaveBeenCalledWith('run-1010', {
        decision: 'approve',
        reviewer: 'Dana Reyes',
        rationale: 'Rush pricing agreed by procurement',
      });
      expect(closedWith).toEqual({ ok: true });
      expect(refreshed).toEqual(jasmine.arrayContaining(['review', 'queue', 'paymentQueue', 'stats']));
      expect(toasts[0]).toContain('INV-1010 approved by Dana Reyes');
      expect(localStorage.getItem(NAME_STORAGE_KEY)).toBe('Dana Reyes');
    });

    it('shows "already decided" on 409 and refreshes the review list', () => {
      api.submitReview.and.returnValue(conflict());
      const f = setup(ReviewDecisionDialog, { row: reviewRow(), decision: 'reject' });
      type(f, '[data-testid=name-input]', 'Sam Ortiz');
      type(f, '[data-testid=rationale]', 'Vendor could not justify the price');
      confirmButton(f).click();
      f.detectChanges();
      expect(f.nativeElement.querySelector('[data-testid=conflict]').textContent).toContain('Already decided by someone else');
      expect(refreshed).toContain('review');
      expect(closedWith).toBeUndefined();
      expect(confirmButton(f)).toBeNull();
      expect(localStorage.getItem(NAME_STORAGE_KEY)).toBeNull(); // stored only after the server accepts
    });

    it('relabels a credit hold and never refreshes the payment queue', () => {
      api.submitReview.and.returnValue(of({ id: 'run-r2', decision: 'approve', reviewer: 'Dana', status: 'Resuming' }));
      const row = reviewRow({ hold_kind: 'credit', amount_usd: '5000.00', overpaid_usd: '940.00', findings: [] });
      const f = setup(ReviewDecisionDialog, { row, decision: 'approve' });
      const text = f.nativeElement.textContent;
      expect(text).toContain('Credit confirmed INV-1010');
      expect(text).toContain('$940.00 overpaid');
      expect(text).toContain('credit note or refund');
      type(f, '[data-testid=name-input]', 'Dana');
      type(f, '[data-testid=rationale]', 'Credit note CN-88 for $940 agreed with vendor');
      expect(confirmButton(f).textContent).toContain('Credit confirmed');
      confirmButton(f).click();
      expect(refreshed).not.toContain('paymentQueue');
      expect(toasts[0]).toContain('Nothing will be paid');

      TestBed.inject(MAT_DIALOG_DATA).decision = 'reject';
      const reject = TestBed.createComponent(ReviewDecisionDialog);
      expect(reject.componentInstance.label).toBe('Reject revision');
    });
  });

  describe('ReviewDecisionDialog on a payee threshold hold', () => {
    it('approving a pulled invoice returns it to the Payment Queue', () => {
      api.submitReview.and.returnValue(of({ id: 'run-1018', decision: 'approve', reviewer: 'Dana', status: 'Resuming' }));
      const row = reviewRow({
        id: 'run-1018', invoice_number: 'INV-1018', hold_kind: 'payee_threshold', reason: 'Payee cumulative threshold',
        pulled: true, findings: [{ code: 'PAYEE_CUMULATIVE_THRESHOLD', severity: 'WARNING', message: 'Payee total $29,000.00' }],
      });
      const f = setup(ReviewDecisionDialog, { row, decision: 'approve' });
      expect(f.componentInstance.label).toBe('Approve');
      type(f, '[data-testid=name-input]', 'Dana');
      type(f, '[data-testid=rationale]', 'Three separate purchase orders confirmed');
      confirmButton(f).click();
      expect(api.submitReview).toHaveBeenCalledWith('run-1018', jasmine.objectContaining({ decision: 'approve' }));
      expect(refreshed).toEqual(jasmine.arrayContaining(['review', 'paymentQueue']));
      expect(toasts[0]).toContain('INV-1018 approved by Dana; it is now in the Payment Queue');
    });
  });

  describe('PayConfirmDialog', () => {
    const rows = [queueRow(1, '5000.00'), queueRow(2, '3690.00')];

    function pay(scope: PayScope, selected: PaymentQueueRow[], response: Observable<unknown>) {
      api.executeBatch.and.returnValue(response as never);
      localStorage.setItem(NAME_STORAGE_KEY, 'Sam Ortiz');
      const f = setup(PayConfirmDialog, { scope, rows: selected });
      return f;
    }

    it('pays all without ids, using the remembered name', () => {
      const f = pay('all', rows, of({ batch_id: 'B-0001', trigger: 'pay_all', released_by: 'Sam Ortiz' }));
      expect(f.nativeElement.querySelector('[data-testid=pay-summary]').textContent).toContain('2 payments');
      expect(f.nativeElement.textContent).toContain('$8,690.00');
      confirmButton(f).click();
      expect(api.executeBatch).toHaveBeenCalledWith({ released_by: 'Sam Ortiz' });
      expect(closedWith).toEqual(jasmine.objectContaining({ batch_id: 'B-0001' }));
      expect(refreshed).toContain('paymentQueue');
    });

    it('pays the selected rows by id', () => {
      const f = pay('selected', rows, of({ batch_id: 'B-0002', trigger: 'pay_selected', released_by: 'Sam Ortiz' }));
      expect(f.nativeElement.textContent).toContain('Pay selected');
      confirmButton(f).click();
      expect(api.executeBatch).toHaveBeenCalledWith({ ids: [1, 2], released_by: 'Sam Ortiz' });
    });

    it('pays one row with Pay now', () => {
      const f = pay('one', [rows[1]], of({ batch_id: 'B-0003', trigger: 'pay_now', released_by: 'Sam Ortiz' }));
      expect(f.nativeElement.textContent).toContain('1 payment');
      expect(f.nativeElement.textContent).toContain('$3,690.00');
      confirmButton(f).click();
      expect(api.executeBatch).toHaveBeenCalledWith({ ids: [2], released_by: 'Sam Ortiz' });
    });

    it('disables confirm without a name', () => {
      api.executeBatch.and.returnValue(of());
      const f = setup(PayConfirmDialog, { scope: 'all', rows });
      expect(confirmButton(f).disabled).toBeTrue();
    });

    it('shows a message when a batch is already running', () => {
      const f = pay('all', rows, conflict());
      confirmButton(f).click();
      f.detectChanges();
      expect(f.nativeElement.querySelector('[data-testid=conflict]').textContent).toContain('A batch is already running');
      expect(closedWith).toBeUndefined();
    });
  });
});
