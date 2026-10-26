import { HttpClient, HttpEvent, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import {
  AdminSettings,
  AdminSettingsRequest,
  AuditFilter,
  AuditRow,
  BatchRow,
  ExecuteRequest,
  ExecuteResponse,
  InvoiceDetail,
  InvoiceListResponse,
  ListResponse,
  PaymentQueueResponse,
  PaymentsFilter,
  PaymentsResponse,
  QueueRow,
  ReviewRequest,
  ReviewResponse,
  ReviewRow,
  Stats,
  UploadResponse,
} from './api.models';

export const API = '/api';

/** Drops empty values so they never reach the query string. */
export function queryParams(filter: object = {}): HttpParams {
  let params = new HttpParams();
  for (const [key, value] of Object.entries(filter)) {
    if (value !== undefined && value !== null && String(value).trim() !== '') {
      params = params.set(key, String(value).trim());
    }
  }
  return params;
}

/** Query string for the CSV export links (same filters as the JSON endpoints). */
export function csvUrl(path: 'invoices.csv' | 'payments.csv', filter: object = {}): string {
  const qs = queryParams(filter).toString();
  return `${API}/${path}${qs ? '?' + qs : ''}`;
}

/** Thin typed wrapper over every `backend-api` endpoint the app uses. */
@Injectable({ providedIn: 'root' })
export class ApiClient {
  private readonly http = inject(HttpClient);

  queue(): Observable<InvoiceListResponse<QueueRow>> {
    return this.http.get<InvoiceListResponse<QueueRow>>(`${API}/invoices`, { params: { view: 'queue' } });
  }

  review(): Observable<InvoiceListResponse<ReviewRow>> {
    return this.http.get<InvoiceListResponse<ReviewRow>>(`${API}/invoices`, { params: { view: 'review' } });
  }

  audit(filter: AuditFilter = {}): Observable<InvoiceListResponse<AuditRow>> {
    return this.http.get<InvoiceListResponse<AuditRow>>(`${API}/invoices`, {
      params: queryParams({ view: 'audit', ...filter }),
    });
  }

  invoice(id: string): Observable<InvoiceDetail> {
    return this.http.get<InvoiceDetail>(`${API}/invoices/${encodeURIComponent(id)}`);
  }

  fileUrl(id: string): string {
    return `${API}/invoices/${encodeURIComponent(id)}/file`;
  }

  file(id: string): Observable<Blob> {
    return this.http.get(this.fileUrl(id), { responseType: 'blob' });
  }

  /** One file per request so each upload row gets its own progress and error. */
  upload(file: File): Observable<HttpEvent<UploadResponse>> {
    const body = new FormData();
    body.append('files', file, file.name);
    return this.http.post<UploadResponse>(`${API}/invoices`, body, { reportProgress: true, observe: 'events' });
  }

  submitReview(id: string, body: ReviewRequest): Observable<ReviewResponse> {
    return this.http.post<ReviewResponse>(`${API}/invoices/${encodeURIComponent(id)}/review`, body);
  }

  paymentQueue(): Observable<PaymentQueueResponse> {
    return this.http.get<PaymentQueueResponse>(`${API}/payment-queue`);
  }

  executeBatch(body: ExecuteRequest): Observable<ExecuteResponse> {
    return this.http.post<ExecuteResponse>(`${API}/payment-queue/execute`, body);
  }

  payments(filter: PaymentsFilter = {}): Observable<PaymentsResponse> {
    return this.http.get<PaymentsResponse>(`${API}/payments`, { params: queryParams(filter) });
  }

  batches(): Observable<ListResponse<BatchRow>> {
    return this.http.get<ListResponse<BatchRow>>(`${API}/payment-batches`);
  }

  stats(): Observable<Stats> {
    return this.http.get<Stats>(`${API}/stats`);
  }

  getAdminSettings(): Observable<AdminSettings> {
    return this.http.get<AdminSettings>(`${API}/admin/settings`);
  }

  saveAdminSettings(body: AdminSettingsRequest): Observable<AdminSettings> {
    return this.http.put<AdminSettings>(`${API}/admin/settings`, body);
  }
}
