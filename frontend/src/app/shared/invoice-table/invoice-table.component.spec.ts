import { Component, signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideNoopAnimations } from '@angular/platform-browser/animations';

import { CellDefDirective, ExpandedRowDirective, InvoiceTableComponent, TableColumn } from './invoice-table.component';

interface Item {
  id: number;
  vendor: string;
  amount: number;
}

@Component({
  standalone: true,
  imports: [InvoiceTableComponent, CellDefDirective, ExpandedRowDirective],
  template: `
    <app-invoice-table
      [columns]="columns"
      [rows]="rows()"
      [selectable]="selectable"
      noun="invoices"
      (rowClick)="clicked = $event"
      (selectionChange)="selection = $event"
      (filteredRowsChange)="filtered = $event"
    >
      <ng-template appCell="amount" let-row><b class="amt">{{ row.amount }}</b></ng-template>
      <ng-template appExpandedRow let-row><div class="detail">Timeline for {{ row.vendor }}</div></ng-template>
    </app-invoice-table>
  `,
})
class HostComponent {
  columns: TableColumn<Item>[] = [
    { key: 'vendor', header: 'Vendor', sortable: true },
    { key: 'amount', header: 'Amount', sortable: true },
  ];
  rows = signal<Item[]>([]);
  selectable = true;
  clicked?: Item;
  selection: Item[] = [];
  filtered: Item[] = [];
}

function makeRows(n: number): Item[] {
  return Array.from({ length: n }, (_, i) => ({
    id: i + 1,
    vendor: i % 3 === 0 ? `Widgets Inc ${i}` : `Gadget Co ${i}`,
    amount: (i * 37) % 100,
  }));
}

describe('InvoiceTableComponent', () => {
  let fixture: ComponentFixture<HostComponent>;
  let host: HostComponent;
  let el: HTMLElement;

  const dataRows = () => Array.from(el.querySelectorAll('tr.data-row'));
  const firstCells = () => dataRows().map((r) => r.querySelectorAll('td')[1].textContent!.trim());

  async function render(): Promise<void> {
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();
  }

  async function setRows(rows: Item[]): Promise<void> {
    host.rows.set(rows);
    await render();
  }

  async function search(text: string): Promise<void> {
    const input = el.querySelector('[data-testid=table-search]') as HTMLInputElement;
    input.value = text;
    input.dispatchEvent(new Event('input'));
    await render();
  }

  async function click(target: Element): Promise<void> {
    (target as HTMLElement).click();
    await render();
  }

  beforeEach(() => {
    TestBed.configureTestingModule({ imports: [HostComponent], providers: [provideNoopAnimations()] });
    fixture = TestBed.createComponent(HostComponent);
    host = fixture.componentInstance;
    el = fixture.nativeElement;
    fixture.detectChanges();
  });

  it('renders custom cell templates and the empty message', async () => {
    expect(el.textContent).toContain('Nothing here yet.');
    await setRows(makeRows(3));
    expect(el.querySelectorAll('.amt').length).toBe(3);
  });

  it('sorts by a column header', async () => {
    await setRows([
      { id: 1, vendor: 'b', amount: 2 },
      { id: 2, vendor: 'c', amount: 1 },
      { id: 3, vendor: 'a', amount: 3 },
    ]);
    const header = el.querySelectorAll('th .mat-sort-header-container')[0] as HTMLElement;
    await click(header);
    expect(firstCells()).toEqual(['a', 'b', 'c']);
    await click(header);
    expect(firstCells()).toEqual(['c', 'b', 'a']);
  });

  it('filters by search text and recounts pagination', async () => {
    await setRows(makeRows(30));
    expect(dataRows().length).toBe(10);
    expect(el.querySelector('.mat-mdc-paginator-range-label')!.textContent).toContain('of 30');

    await search('widgets inc');
    expect(host.filtered.length).toBe(10);
    expect(el.querySelector('[data-testid=table-count]')!.textContent).toContain('10 of 30 invoices');
    expect(el.querySelector('.mat-mdc-paginator-range-label')!.textContent).toContain('of 10');
    expect(firstCells().every((v) => v.startsWith('Widgets Inc'))).toBeTrue();

    await search('nothing-matches');
    expect(el.textContent).toContain('No invoices match');
  });

  it('paginates', async () => {
    await setRows(makeRows(23));
    const next = el.querySelector('button.mat-mdc-paginator-navigation-next') as HTMLButtonElement;
    await click(next);
    expect(el.querySelector('.mat-mdc-paginator-range-label')!.textContent).toContain('11 – 20 of 23');
    await click(next);
    expect(dataRows().length).toBe(3);
  });

  it('emits rowClick, selection, and expands a detail row', async () => {
    await setRows(makeRows(3));
    (dataRows()[1].querySelectorAll('td')[1] as HTMLElement).click();
    expect(host.clicked?.id).toBe(2);

    await click(el.querySelectorAll('tr.data-row input[type=checkbox]')[0]);
    expect(host.selection.map((r) => r.id)).toEqual([1]);
    expect(host.clicked?.id).toBe(2); // the checkbox click is not a row click

    await click(el.querySelector('[data-testid=expand]')!);
    expect(el.querySelector('.detail')!.textContent).toContain('Timeline for Widgets Inc 0');

    await setRows(makeRows(3).slice(1)); // row 1 leaves: its selection is dropped
    expect(host.selection).toEqual([]);
  });
});
