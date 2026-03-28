import { Routes } from '@angular/router';

export const routes: Routes = [
  {
    path: '',
    redirectTo: 'dashboard',
    pathMatch: 'full',
  },
  {
    path: 'dashboard',
    loadComponent: () =>
      import('./features/dashboard/dashboard.component').then(
        (m) => m.DashboardComponent
      ),
  },
  {
    path: 'trades',
    loadComponent: () =>
      import('./features/trades/trades.component').then(
        (m) => m.TradesComponent
      ),
  },
  {
    path: 'strategies',
    loadComponent: () =>
      import('./features/strategies/strategies.component').then(
        (m) => m.StrategiesComponent
      ),
  },
  {
    path: 'risk',
    loadComponent: () =>
      import('./features/risk-panel/risk-panel.component').then(
        (m) => m.RiskPanelComponent
      ),
  },
  {
    path: 'analytics',
    loadComponent: () =>
      import('./features/analytics/analytics.component').then(
        (m) => m.AnalyticsComponent
      ),
  },
  {
    path: 'error',
    loadComponent: () =>
      import('./features/server-error/server-error.component').then(
        (m) => m.ServerErrorComponent
      ),
  },
  {
    path: '**',
    loadComponent: () =>
      import('./features/not-found/not-found.component').then(
        (m) => m.NotFoundComponent
      ),
  },
];
