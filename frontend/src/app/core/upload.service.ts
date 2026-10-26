import { HttpEventType } from '@angular/common/http';
import { Injectable, inject, signal } from '@angular/core';
import { Observable, catchError, from, map, mergeMap, of, tap, toArray } from 'rxjs';

import { ApiClient } from './api-client';
import { errorMessage } from './http-errors';
import { Stores } from './live-store';

export const ACCEPTED_EXTENSIONS = ['.pdf', '.txt', '.csv', '.json', '.xml', '.eml'];
export const MAX_BYTES = 10 * 1024 * 1024;
export const MAX_CONCURRENT = 3;

export type UploadState = 'pending' | 'uploading' | 'queued' | 'error';

export interface UploadItem {
  key: number;
  name: string;
  size: number;
  state: UploadState;
  progress: number;
  error: string | null;
  runId: string | null;
}

export interface UploadSummary {
  accepted: number;
  total: number;
}

/** Client-side refusal before upload; the backend repeats these checks. */
export function refusal(file: File): string | null {
  const dot = file.name.lastIndexOf('.');
  const ext = dot >= 0 ? file.name.slice(dot).toLowerCase() : '';
  if (!ACCEPTED_EXTENSIONS.includes(ext)) return `Wrong file type; use ${ACCEPTED_EXTENSIONS.join(', ')}`;
  if (file.size > MAX_BYTES) return 'File is over 10 MB';
  if (file.size === 0) return 'Empty file';
  return null;
}

/** Validates files, then sends each valid one as its own POST (at most 3 at once) with progress. */
@Injectable({ providedIn: 'root' })
export class UploadService {
  private readonly api = inject(ApiClient);
  private readonly stores = inject(Stores);
  private nextKey = 1;

  readonly items = signal<UploadItem[]>([]);

  /** Adds a batch; emits once when every file in it has finished, with the accepted count. */
  add(files: File[]): Observable<UploadSummary> {
    const batch = files.map((file) => {
      const error = refusal(file);
      const item: UploadItem = {
        key: this.nextKey++,
        name: file.name,
        size: file.size,
        state: error ? 'error' : 'pending',
        progress: 0,
        error,
        runId: null,
      };
      return { file, item };
    });
    this.items.update((items) => [...batch.map((b) => b.item), ...items]);
    const valid = batch.filter((b) => b.item.state === 'pending');

    return from(valid).pipe(
      mergeMap(({ file, item }) => this.send(file, item.key), MAX_CONCURRENT),
      toArray(),
      map((results) => ({ accepted: results.filter(Boolean).length, total: files.length })),
      tap((summary) => summary.accepted && this.stores.refresh('queue', 'stats')),
    );
  }

  clear(): void {
    this.items.update((items) => items.filter((i) => i.state === 'pending' || i.state === 'uploading'));
  }

  private patch(key: number, change: Partial<UploadItem>): void {
    this.items.update((items) => items.map((i) => (i.key === key ? { ...i, ...change } : i)));
  }

  /** Emits true when the backend accepted the file. */
  private send(file: File, key: number): Observable<boolean> {
    this.patch(key, { state: 'uploading' });
    return this.api.upload(file).pipe(
      mergeMap((event) => {
        if (event.type === HttpEventType.UploadProgress) {
          this.patch(key, { progress: event.total ? Math.round((100 * event.loaded) / event.total) : 50 });
          return [];
        }
        if (event.type !== HttpEventType.Response) return [];
        const result = event.body?.files?.[0];
        if (result && result.status === 'Uploaded' && result.id) {
          this.patch(key, { state: 'queued', progress: 100, runId: result.id });
          return [true];
        }
        this.patch(key, { state: 'error', error: result?.error ?? 'The server refused this file' });
        return [false];
      }),
      catchError((err) => {
        this.patch(key, { state: 'error', error: errorMessage(err) });
        return of(false);
      }),
    );
  }
}
