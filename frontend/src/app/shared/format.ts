import { Pipe, PipeTransform } from '@angular/core';

const USD = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' });

/** "$5,940.00" from a backend money string; em dash when unknown. */
export function usd(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === '') return '—';
  const n = Number(value);
  return Number.isFinite(n) ? USD.format(n) : String(value);
}

/** "EUR 4,125.00" for an original foreign amount. */
export function foreign(amount: string | null | undefined, currency: string | null | undefined): string {
  if (!amount || !currency) return '';
  const n = Number(amount);
  const text = Number.isFinite(n) ? n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : amount;
  return `${currency} ${text}`;
}

/** Sum of money strings, rounded to cents. */
export function sumMoney(values: (string | null | undefined)[]): number {
  return Math.round(values.reduce((acc, v) => acc + (Number(v) || 0), 0) * 100) / 100;
}

/** "4s", "3m 05s", "2h 10m", "3d 4h". */
export function duration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return '—';
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ${String(s % 60).padStart(2, '0')}s`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ${m % 60}m`;
  return `${Math.floor(h / 24)}d ${h % 24}h`;
}

/** Local "Oct 25, 4:32 PM". */
export function when(iso: string | null | undefined): string {
  if (!iso) return '—';
  const d = new Date(iso);
  return isNaN(d.getTime())
    ? iso
    : d.toLocaleString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });
}

/** "PRICE_VARIANCE" -> "Price variance". */
export function findingLabel(code: string | null | undefined): string {
  if (!code) return '';
  const words = code.toLowerCase().split('_');
  return [words[0].charAt(0).toUpperCase() + words[0].slice(1), ...words.slice(1)].join(' ');
}

export function fileIcon(format: string | null | undefined): string {
  switch ((format ?? '').toLowerCase()) {
    case 'pdf':
      return 'picture_as_pdf';
    case 'csv':
      return 'table_chart';
    case 'json':
    case 'xml':
      return 'data_object';
    case 'eml':
      return 'mail';
    default:
      return 'description';
  }
}

@Pipe({ name: 'usd', standalone: true })
export class UsdPipe implements PipeTransform {
  transform = usd;
}

@Pipe({ name: 'duration', standalone: true })
export class DurationPipe implements PipeTransform {
  transform = duration;
}

@Pipe({ name: 'when', standalone: true })
export class WhenPipe implements PipeTransform {
  transform = when;
}

@Pipe({ name: 'finding', standalone: true })
export class FindingPipe implements PipeTransform {
  transform = findingLabel;
}

@Pipe({ name: 'fileIcon', standalone: true })
export class FileIconPipe implements PipeTransform {
  transform = fileIcon;
}

export const FORMAT_PIPES = [UsdPipe, DurationPipe, WhenPipe, FindingPipe, FileIconPipe] as const;
