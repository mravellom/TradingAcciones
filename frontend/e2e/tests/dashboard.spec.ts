import { test, expect } from '@playwright/test';

test.describe('Dashboard', () => {
  test.beforeEach(async ({ page }) => {
    // Mock API responses to avoid needing a running backend
    await page.route('**/api/v1/system/health', (route) =>
      route.fulfill({
        json: { status: 'healthy', system_status: 'RUNNING', checks: { database: { status: 'healthy' }, redis: { status: 'healthy' } }, timestamp: new Date().toISOString() },
      })
    );
    await page.route('**/api/v1/portfolio*', (route) =>
      route.fulfill({
        json: { total_balance: '10000.00', available_balance: '8000.00', daily_pnl: '150.00', total_pnl: '500.00', max_drawdown: '0.02' },
      })
    );
    await page.route('**/api/v1/positions/open', (route) =>
      route.fulfill({ json: [] })
    );
    await page.route('**/api/v1/trades*', (route) =>
      route.fulfill({ json: [] })
    );
    await page.route('**/api/v1/signals*', (route) =>
      route.fulfill({ json: [] })
    );
    await page.route('**/api/v1/trades/win-rate', (route) =>
      route.fulfill({ json: { win_rate: 0.65 } })
    );
    await page.route('**/api/v1/analytics/summary', (route) =>
      route.fulfill({ json: { total_trades: 20, wins: 13, losses: 7, avg_return: '1.5', avg_duration_seconds: 120 } })
    );
    await page.route('**/api/v1/analytics/per-strategy', (route) =>
      route.fulfill({ json: [] })
    );
    await page.route('**/api/v1/analytics/pnl*', (route) =>
      route.fulfill({ json: [] })
    );
    await page.route('**/api/v1/orders/pending-approval', (route) =>
      route.fulfill({ json: [] })
    );

    await page.goto('/dashboard');
  });

  test('should display dashboard', async ({ page }) => {
    await expect(page.locator('.dashboard')).toBeVisible();
  });

  test('should show system status', async ({ page }) => {
    await expect(page.locator('.status-bar')).toContainText('RUNNING');
  });

  test('should show portfolio cards', async ({ page }) => {
    await expect(page.locator('.cards-grid')).toBeVisible();
    await expect(page.locator('.card-value').first()).toContainText('10,000.00');
  });

  test('should show trading summary', async ({ page }) => {
    await expect(page.locator('.summary-grid')).toBeVisible();
  });
});
