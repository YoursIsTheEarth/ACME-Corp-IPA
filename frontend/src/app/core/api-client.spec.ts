import { HttpEventType, provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';

import { ApiClient, csvUrl } from './api-client';

describe('ApiClient', () => {
  let api: ApiClient;
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({ providers: [provideHttpClient(), provideHttpClientTesting()] });
    api = TestBed.inject(ApiClient);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  function expectCall(method: string, url: string) {
    const req = http.expectOne((r) => r.method === method && r.urlWithParams === url);
    req.flush({});
    return req;
  }

  it('GETs the three invoice views', () => {
    api.queue().subscribe();
    expectCall('GET', '/api/invoices?view=queue');
    api.review().subscribe();
    expectCall('GET', '/api/invoices?view=review');
    api.audit({ status: 'Rejected', date_from: '2026-10-01', search: ' ' }).subscribe();
    expectCall('GET', '/api/invoices?view=audit&status=Rejected&date_from=2026-10-01');
  });

  it('GETs invoice detail and the original file', () => {
    api.invoice('run-1').subscribe();
    expectCall('GET', '/api/invoices/run-1');
    api.file('run-1').subscribe();
    const req = http.expectOne('/api/invoices/run-1/file');
    expect(req.request.responseType).toBe('blob');
    req.flush(new Blob(['x']));
  });

  it('POSTs one multipart file per upload with progress events', () => {
    const file = new File(['abc'], 'invoice_1001.txt');
    let sawResponse = false;
    api.upload(file).subscribe((e) => (sawResponse ||= e.type === HttpEventType.Response));
    const req = http.expectOne('/api/invoices');
    expect(req.request.method).toBe('POST');
    expect(req.request.reportProgress).toBeTrue();
    expect((req.request.body as FormData).get('files')).toEqual(jasmine.any(File));
    req.flush({ files: [], accepted: 1, rejected: 0, server_time: '' }, { status: 202, statusText: 'Accepted' });
    expect(sawResponse).toBeTrue();
  });

  it('POSTs a review decision', () => {
    api.submitReview('run-1', { decision: 'approve', reviewer: 'Dana', rationale: 'x'.repeat(15) }).subscribe();
    const req = expectCall('POST', '/api/invoices/run-1/review');
    expect(req.request.body.decision).toBe('approve');
  });

  it('covers the payment endpoints and stats', () => {
    api.paymentQueue().subscribe();
    expectCall('GET', '/api/payment-queue');
    api.executeBatch({ ids: [1, 2], released_by: 'Sam' }).subscribe();
    const req = expectCall('POST', '/api/payment-queue/execute');
    expect(req.request.body).toEqual({ ids: [1, 2], released_by: 'Sam' });
    api.payments({ vendor: 'Widgets' }).subscribe();
    expectCall('GET', '/api/payments?vendor=Widgets');
    api.batches().subscribe();
    expectCall('GET', '/api/payment-batches');
    api.stats().subscribe();
    expectCall('GET', '/api/stats');
  });

  it('GETs and PUTs the admin settings', () => {
    api.getAdminSettings().subscribe();
    expectCall('GET', '/api/admin/settings');
    const body = {
      delay_payments: false,
      pay_at_end_of_day: false,
      end_of_day_time: '17:00',
      end_of_day_timezone: 'America/Chicago',
      pay_when_queue_empty: true,
      updated_by: 'Dana',
    };
    api.saveAdminSettings(body).subscribe();
    const req = expectCall('PUT', '/api/admin/settings');
    expect(req.request.body).toEqual(body);
  });

  it('builds CSV export links with the current filter', () => {
    expect(csvUrl('invoices.csv', { status: 'Rejected', search: '' })).toBe('/api/invoices.csv?status=Rejected');
    expect(csvUrl('payments.csv')).toBe('/api/payments.csv');
  });
});
