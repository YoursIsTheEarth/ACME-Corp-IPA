import { NgTemplateOutlet } from '@angular/common';
import {
  AfterViewInit,
  ChangeDetectionStrategy,
  Component,
  Directive,
  TemplateRef,
  ViewChild,
  computed,
  contentChild,
  contentChildren,
  effect,
  inject,
  input,
  output,
  signal,
  untracked,
} from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatPaginator, MatPaginatorModule } from '@angular/material/paginator';
import { MatSort, MatSortModule } from '@angular/material/sort';
import { MatTableDataSource, MatTableModule } from '@angular/material/table';

/** One column of the shared table. Cells default to `row[key]`; project `<ng-template appCell="key">` to customize. */
export interface TableColumn<T> {
  key: string;
  header: string;
  sortable?: boolean;
  /** Value used for sorting; defaults to `row[key]`. */
  sortValue?: (row: T) => string | number | null | undefined;
  /** Text the search box matches; defaults to the sort value. */
  searchText?: (row: T) => string | null | undefined;
}

/** `<ng-template appCell="vendor" let-row>` renders the cells of one column. */
@Directive({ selector: 'ng-template[appCell]', standalone: true })
export class CellDefDirective {
  readonly name = input.required<string>({ alias: 'appCell' });
  readonly template = inject(TemplateRef);
}

/** `<ng-template appExpandedRow let-row>` renders the expandable detail under a row. */
@Directive({ selector: 'ng-template[appExpandedRow]', standalone: true })
export class ExpandedRowDirective {
  readonly template = inject(TemplateRef);
}

type Row = object;

function plain(value: unknown): string {
  return value === null || value === undefined ? '' : String(value);
}

/**
 * The one table every page uses: column defs, sort, client-side search over every column's text,
 * pagination, row click, an optional selection column, and an optional expandable row.
 */
@Component({
  selector: 'app-invoice-table',
  standalone: true,
  imports: [
    NgTemplateOutlet,
    MatTableModule,
    MatSortModule,
    MatPaginatorModule,
    MatFormFieldModule,
    MatInputModule,
    MatIconModule,
    MatCheckboxModule,
    MatButtonModule,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './invoice-table.component.html',
  styleUrl: './invoice-table.component.scss',
})
export class InvoiceTableComponent<T extends Row> implements AfterViewInit {
  readonly columns = input.required<TableColumn<T>[]>();
  readonly rows = input<T[] | null | undefined>([]);
  readonly rowId = input<(row: T) => string | number>((row: T) => plain((row as { id?: unknown }).id));
  readonly selectable = input(false);
  readonly canSelect = input<(row: T) => boolean>(() => true);
  readonly loading = input(false);
  readonly emptyMessage = input('Nothing here yet.');
  readonly noun = input('rows');
  readonly pageSize = input(10);

  readonly rowClick = output<T>();
  readonly selectionChange = output<T[]>();
  readonly filteredRowsChange = output<T[]>();

  private readonly cellDefs = contentChildren(CellDefDirective);
  readonly expandedDef = contentChild(ExpandedRowDirective);

  @ViewChild(MatSort) sort?: MatSort;
  @ViewChild(MatPaginator) paginator?: MatPaginator;

  readonly dataSource = new MatTableDataSource<T>([]);
  readonly search = signal('');
  readonly selected = signal<ReadonlySet<string | number>>(new Set());
  readonly expanded = signal<ReadonlySet<string | number>>(new Set());

  readonly templates = computed(() => new Map(this.cellDefs().map((d) => [d.name(), d.template])));
  readonly displayed = computed(() => [
    ...(this.selectable() ? ['select'] : []),
    ...this.columns().map((c) => c.key),
    ...(this.expandedDef() ? ['expand'] : []),
  ]);
  readonly safeRows = computed(() => this.rows() ?? []);
  readonly filteredRows = computed(() => {
    const needle = this.search().trim().toLowerCase();
    return needle ? this.safeRows().filter((row) => this.matches(row, needle)) : this.safeRows();
  });
  readonly selectableRows = computed(() => this.safeRows().filter((r) => this.canSelect()(r)));
  readonly selectedRows = computed(() => {
    const ids = this.selected();
    return this.safeRows().filter((r) => ids.has(this.rowId()(r)));
  });
  readonly allSelected = computed(
    () => this.selectableRows().length > 0 && this.selectedRows().length === this.selectableRows().length,
  );

  readonly trackBy = (_: number, row: T) => this.rowId()(row);
  readonly hasDetail = (_: number, row: T) => !!this.expandedDef() && this.isExpanded(row);

  constructor() {
    this.dataSource.sortingDataAccessor = (row, key) => {
      const column = this.columns().find((c) => c.key === key);
      const value = column?.sortValue ? column.sortValue(row) : (row as Record<string, unknown>)[key];
      if (value === null || value === undefined) return '';
      return typeof value === 'number' ? value : String(value).toLowerCase();
    };
    this.dataSource.filterPredicate = (row, filter) => this.matches(row, filter);

    effect(() => {
      this.dataSource.data = this.safeRows();
      // Drop selections for rows that left (or can no longer be selected).
      const keep = new Set(this.selectableRows().map((r) => this.rowId()(r)));
      const current = untracked(this.selected);
      const pruned = new Set([...current].filter((id) => keep.has(id)));
      if (pruned.size !== current.size) {
        this.selected.set(pruned);
      }
    }, { allowSignalWrites: true });
    effect(() => {
      this.dataSource.filter = this.search().trim().toLowerCase();
      this.paginator?.firstPage();
    });
    effect(() => this.filteredRowsChange.emit(this.filteredRows()));
    effect(() => this.selectionChange.emit(this.selectedRows()));
  }

  ngAfterViewInit(): void {
    if (this.sort) this.dataSource.sort = this.sort;
    if (this.paginator) this.dataSource.paginator = this.paginator;
  }

  private matches(row: T, needle: string): boolean {
    return this.columns().some((c) => {
      const text = c.searchText ? c.searchText(row) : c.sortValue ? c.sortValue(row) : (row as Record<string, unknown>)[c.key];
      return plain(text).toLowerCase().includes(needle);
    });
  }

  cellText(row: T, key: string): string {
    return plain((row as Record<string, unknown>)[key]);
  }

  onSearch(value: string): void {
    this.search.set(value);
  }

  onRowClick(row: T, event: MouseEvent): void {
    const target = event.target as HTMLElement | null;
    if (target?.closest('button, a, input, mat-checkbox, .no-row-click')) return;
    this.rowClick.emit(row);
  }

  isSelected(row: T): boolean {
    return this.selected().has(this.rowId()(row));
  }

  toggle(row: T): void {
    const id = this.rowId()(row);
    const next = new Set(this.selected());
    if (next.has(id)) next.delete(id);
    else next.add(id);
    this.selected.set(next);
  }

  toggleAll(): void {
    this.selected.set(this.allSelected() ? new Set() : new Set(this.selectableRows().map((r) => this.rowId()(r))));
  }

  clearSelection(): void {
    this.selected.set(new Set());
  }

  isExpanded(row: T): boolean {
    return this.expanded().has(this.rowId()(row));
  }

  toggleExpanded(row: T): void {
    const id = this.rowId()(row);
    const next = new Set(this.expanded());
    if (next.has(id)) next.delete(id);
    else next.add(id);
    this.expanded.set(next);
  }
}
