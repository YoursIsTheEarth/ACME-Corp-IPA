# Tasks

## 1. Sidebar order

- [ ] 1.1 Reorder `NAV_ITEMS` in `frontend/src/app/shell/shell.component.ts` to Home, Invoice Queue, Payment Queue, Invoice Elevated Review, Invoice Resolution Audit, Payments (paths, labels, icons, and badges unchanged). Verify the sidebar renders in that order by running `npm --prefix frontend start` and checking the page.
- [ ] 1.2 Update the order assertion in `frontend/src/app/shell/shell.component.spec.ts` and add an assertion that the collapsed (icon-only) layout uses the same order. Verify `npm --prefix frontend run test:ci` passes.
- [ ] 1.3 Verify `npm --prefix frontend run build` succeeds and the Playwright happy path (`make e2e`) still passes, since it navigates by test id.
