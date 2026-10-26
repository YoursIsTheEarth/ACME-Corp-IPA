import { Routes } from '@angular/router';

/** One lazy route per page, in sidebar order (Admin is pinned at the bottom of the sidebar). */
export const routes: Routes = [
  { path: '', title: 'Home · ACME Corp IPA', loadComponent: () => import('./pages/home/home.page').then((m) => m.HomePage) },
  { path: 'queue', title: 'Invoice Queue · ACME Corp IPA', loadComponent: () => import('./pages/queue.page').then((m) => m.QueuePage) },
  { path: 'audit', title: 'Invoice Resolution Audit · ACME Corp IPA', loadComponent: () => import('./pages/audit.page').then((m) => m.AuditPage) },
  { path: 'review', title: 'Invoice Elevated Review · ACME Corp IPA', loadComponent: () => import('./pages/review.page').then((m) => m.ReviewPage) },
  {
    path: 'payment-queue',
    title: 'Payment Queue · ACME Corp IPA',
    loadComponent: () => import('./pages/payment-queue.page').then((m) => m.PaymentQueuePage),
  },
  { path: 'payments', title: 'Payments · ACME Corp IPA', loadComponent: () => import('./pages/payments.page').then((m) => m.PaymentsPage) },
  { path: 'admin', title: 'Admin · ACME Corp IPA', loadComponent: () => import('./pages/admin.page').then((m) => m.AdminPage) },
  { path: '**', redirectTo: '' },
];
