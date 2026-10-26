import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';

import { Stores } from './live-store';
import { MAX_BYTES, UploadService, refusal } from './upload.service';

function file(name: string, size: number): File {
  const f = new File(['x'], name);
  Object.defineProperty(f, 'size', { value: size });
  return f;
}

describe('UploadService', () => {
  let service: UploadService;
  let http: HttpTestingController;
  let refreshed: string[];

  beforeEach(() => {
    refreshed = [];
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: Stores, useValue: { refresh: (...names: string[]) => refreshed.push(...names) } },
      ],
    });
    service = TestBed.inject(UploadService);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  it('refuses wrong type, over 10 MB, and empty files before upload', () => {
    expect(refusal(file('invoice.pdf', 200 * 1024))).toBeNull();
    expect(refusal(file('INVOICE.EML', 10))).toBeNull();
    expect(refusal(file('photo.png', 10))).toContain('Wrong file type');
    expect(refusal(file('big.pdf', MAX_BYTES + 1))).toBe('File is over 10 MB');
    expect(refusal(file('invoice.txt', 0))).toBe('Empty file');
  });

  it('uploads only valid files, at most 3 at once, and reports per-row results', () => {
    let summary: { accepted: number; total: number } | undefined;
    service
      .add([
        file('a.txt', 10),
        file('photo.png', 10),
        file('big.pdf', MAX_BYTES + 1),
        file('b.csv', 10),
        file('c.json', 10),
        file('d.xml', 10),
        file('empty.txt', 0),
      ])
      .subscribe((s) => (summary = s));

    const byName = () => Object.fromEntries(service.items().map((i) => [i.name, i]));
    expect(byName()['photo.png'].error).toContain('Wrong file type');
    expect(byName()['big.pdf'].error).toBe('File is over 10 MB');
    expect(byName()['empty.txt'].error).toBe('Empty file');

    // Only three in flight; the fourth waits.
    const first = http.match('/api/invoices');
    expect(first.length).toBe(3);
    let pending = first;
    expect(byName()['d.xml'].state).toBe('pending');

    const ok = (name: string, id: string) =>
      ({ files: [{ id, file_name: name, status: 'Uploaded', size: 10, error: null }], accepted: 1, rejected: 0, server_time: '' });
    pending[0].flush(ok('a.txt', 'run-a'), { status: 202, statusText: 'Accepted' });
    pending[1].flush(
      { files: [{ id: null, file_name: 'b.csv', status: 'rejected', size: 10, error: 'Unsupported file type' }], accepted: 0, rejected: 1, server_time: '' },
      { status: 202, statusText: 'Accepted' },
    );
    pending = http.match('/api/invoices'); // d.xml started after a slot freed
    expect(pending.length).toBe(1);
    expect((pending[0].request.body as FormData).get('files')).toEqual(jasmine.any(File));
    pending[0].flush({ detail: 'Upload directory is full' }, { status: 413, statusText: 'Too large' });
    first[2].flush(ok('c.json', 'run-c'), { status: 202, statusText: 'Accepted' });

    expect(byName()['a.txt'].state).toBe('queued');
    expect(byName()['a.txt'].runId).toBe('run-a');
    expect(byName()['b.csv'].error).toBe('Unsupported file type');
    expect(byName()['d.xml'].error).toBe('Upload directory is full');
    expect(byName()['c.json'].state).toBe('queued');
    expect(summary).toEqual({ accepted: 2, total: 7 });
    expect(refreshed).toContain('queue');
  });

  it('shows the API message when uploads are refused for a missing LLM key (503)', () => {
    let summary: { accepted: number; total: number } | undefined;
    service.add([file('a.txt', 10)]).subscribe((s) => (summary = s));
    const message =
      'No LLM token provided: set XAI_API_KEY for Grok (in .env or the environment). The app cannot process invoices without it.';
    http
      .expectOne('/api/invoices')
      .flush(
        { detail: { code: 'llm_not_configured', message, missing_key: 'XAI_API_KEY' } },
        { status: 503, statusText: 'Service Unavailable' },
      );
    const [item] = service.items();
    expect(item.state).toBe('error');
    expect(item.error).toBe(message);
    expect(summary).toEqual({ accepted: 0, total: 1 });
    expect(refreshed).toEqual([]);
  });
});
