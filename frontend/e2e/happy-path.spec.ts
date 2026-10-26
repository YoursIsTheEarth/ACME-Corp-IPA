import { expect, test } from '@playwright/test';
import path from 'node:path';

const invoices = path.resolve(__dirname, '../../data/invoices');
const files = ['invoice_1001.txt', 'invoice_1006.csv', 'invoice_1010.txt'].map((f) => path.join(invoices, f));

test('upload 3, approve INV-1010, pay all, see them in Payments', async ({ page }) => {
  // Home: upload three files through the picker.
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'Welcome to ACME Corp IPA' })).toBeVisible();
  await expect(page.getByTestId('llm-provider')).toHaveText('Grok'); // the test-only fake stands in for Grok
  await expect(page.getByTestId('llm-banner')).toHaveCount(0);
  await page.getByTestId('file-input').setInputFiles(files);
  await expect(page.getByTestId('upload-status').filter({ hasText: 'Queued' })).toHaveCount(3);
  await expect(page.getByText('3 files were accepted')).toBeVisible();

  // Elevated Review: INV-1010 is held for a price variance; approve it.
  await page.getByTestId('view-queue').click();
  await expect(page).toHaveURL(/\/queue$/);
  await page.getByTestId('nav-/review').first().click();
  const held = page.locator('tr.data-row', { hasText: 'INV-1010' });
  await expect(held).toBeVisible();
  await expect(held).toContainText('Price variance');
  await held.getByTestId('approve').click();
  const dialog = page.getByRole('dialog');
  await dialog.getByTestId('name-input').fill('Dana Reyes');
  await dialog.getByTestId('rationale').fill('Rush pricing agreed by procurement');
  await dialog.getByTestId('confirm').click();
  await expect(page.getByText('INV-1010 approved by Dana Reyes')).toBeVisible();
  await expect(held).toHaveCount(0);

  // Payment Queue: all three are queued; Pay all.
  await page.getByTestId('nav-/payment-queue').first().click();
  for (const inv of ['INV-1001', 'INV-1006', 'INV-1010']) {
    await expect(page.locator('tr.data-row', { hasText: inv })).toBeVisible();
  }
  await expect(page.getByTestId('pq-count')).toHaveText('3');
  await page.getByTestId('pay-all').click();
  const pay = page.getByRole('dialog');
  await expect(pay.getByTestId('pay-summary')).toContainText('3 payments');
  await expect(pay.getByTestId('name-input')).toHaveValue('Dana Reyes'); // remembered from the review
  await pay.getByTestId('confirm').click();
  await expect(page.getByText(/Batch B-\d+: 3 paid, \$/)).toBeVisible();
  await expect(page.getByText('Nothing is waiting to be paid.')).toBeVisible();

  // Payments: all three were paid, released by Dana Reyes.
  await page.getByTestId('nav-/payments').first().click();
  for (const inv of ['INV-1001', 'INV-1006', 'INV-1010']) {
    const row = page.locator('tr.data-row', { hasText: inv });
    await expect(row).toBeVisible();
    await expect(row).toContainText('Dana Reyes');
  }
  await expect(page.getByTestId('payments-total')).toContainText('3 payments');
});

// Runs after the happy path (same backend): invoice_1006.csv was already paid there, so this step
// uploads invoice_1015.csv, another clean invoice, to show payment at approval.
test('turn delay off on Admin, then an approved invoice is paid without clicking Pay', async ({ page }) => {
  // Admin: the defaults keep approved invoices in the Payment Queue; turn delay off and save as Dana Reyes.
  await page.goto('/');
  await page.getByTestId('nav-/admin').first().click();
  await expect(page).toHaveURL(/\/admin$/);
  await expect(page.getByTestId('mode')).toContainText('Approved invoices wait in the Payment Queue');
  await page.getByTestId('delay-toggle').getByRole('switch').click();
  await expect(page.getByTestId('batch-options')).toHaveCount(0);
  await expect(page.getByTestId('pays-queue-warning')).toBeVisible();
  await page.getByTestId('save').click();
  const dialog = page.getByRole('dialog');
  await expect(dialog.getByTestId('change-summary')).toContainText('Delay payments: On → Off');
  await dialog.getByTestId('name-input').fill('Dana Reyes');
  await dialog.getByTestId('confirm').click();
  await expect(page.getByText('Payment settings saved by Dana Reyes.')).toBeVisible();
  await expect(page.getByTestId('last-saved')).toContainText('Last saved by Dana Reyes');
  await expect(page.getByTestId('mode')).toContainText('paid as soon as they are approved');

  // Payment Queue: the header says payments are made at approval and links to Admin.
  await page.getByTestId('nav-/payment-queue').first().click();
  await expect(page.getByTestId('pq-mode')).toHaveText('Paid at approval');
  await expect(page.getByTestId('pq-admin-link')).toHaveAttribute('href', '/admin');

  // Home: upload one clean invoice; it is paid as soon as it is approved.
  await page.getByTestId('nav-/').first().click();
  await page.getByTestId('file-input').setInputFiles(path.join(invoices, 'invoice_1015.csv'));
  await expect(page.getByText('1 file was accepted')).toBeVisible();

  // Payments: paid by an immediate batch released by System; nobody clicked Pay.
  await page.getByTestId('nav-/payments').first().click();
  const row = page.locator('tr.data-row', { hasText: 'INV-1015' });
  await expect(row).toBeVisible();
  await expect(row).toContainText('Immediate (at approval)');
  await expect(row).toContainText('System');
  await page.getByTestId('nav-/payment-queue').first().click();
  await expect(page.getByText('Nothing is waiting to be paid.')).toBeVisible();
});
