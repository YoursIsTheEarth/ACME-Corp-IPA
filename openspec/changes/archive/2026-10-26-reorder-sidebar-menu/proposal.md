# Proposal

## Why

The sidebar should follow the order work actually moves through the app: an invoice is uploaded, processed, and then either queued for payment or held for review. Putting Payment Queue and Elevated Review right after Invoice Queue keeps the pages that need action together, and leaves the two history pages (Resolution Audit, Payments) at the end.

## What Changes

- The sidebar menu order becomes: Home, Invoice Queue, Payment Queue, Invoice Elevated Review, Invoice Resolution Audit, Payments.
- Routes, page titles, badges, icons, and the collapsed (icon-only) sidebar keep their behavior; only the order changes, in both the full and collapsed layouts.
- The source design doc's "App shell and sidebar" bullet and the F21 row list the new order.

## Capabilities

### New Capabilities
- None.

### Modified Capabilities
- `web-app`: the "App shell and sidebar navigation (F21)" requirement's menu order.

## Impact

- `frontend/src/app/shell/shell.component.ts` (`NAV_ITEMS` order) and `shell.component.spec.ts` (the order assertion).
- No backend, API, or route changes. The e2e test navigates by test id, not position, so it is unaffected.
