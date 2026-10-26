# ACME Corp IPA: frontend

Angular 18 (standalone components, Angular Material, RxJS). Setup and run commands are in the repo
root README ("Web app: ACME Corp IPA").

```bash
npm ci
npm start              # ng serve on :4200, /api proxied to :8000 (proxy.conf.json)
npm run build          # production build into dist/frontend
npm run test:ci        # component tests, headless Chrome (CHROME_BIN or Playwright's Chromium)
npm run e2e            # Playwright: backend with the test-only fake model on a fresh DB (port 8100), ng serve (4300)
```

Layout: `src/app/core` (API client and DTOs, live stores, SSE, uploads, toasts), `src/app/shared`
(table, status chips, name field, stage strip), `src/app/pages` (one lazy route per page),
`src/app/dialogs` (review and pay), `src/app/detail` (drawer and rationale timeline), `src/app/shell`.
