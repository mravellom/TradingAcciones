import { test, expect } from '@playwright/test';

test.describe('Error Handling', () => {
  test('should show error toast when API returns 500', async ({ page }) => {
    // Mock all API endpoints to return 500
    await page.route('**/api/v1/**', (route) =>
      route.fulfill({ status: 500, json: { message: 'Internal server error' } })
    );

    await page.goto('/dashboard');

    // Wait for error toast to appear
    await expect(page.locator('.toast--error')).toBeVisible({ timeout: 10000 });
  });

  test('should show 404 page for unknown routes', async ({ page }) => {
    await page.goto('/nonexistent-page');
    await expect(page.locator('.error-page__code')).toContainText('404');
    await expect(page.locator('.error-page__link')).toBeVisible();
  });

  test('should navigate back from 404 page', async ({ page }) => {
    // Mock API to prevent errors
    await page.route('**/api/v1/**', (route) =>
      route.fulfill({ json: {} })
    );

    await page.goto('/nonexistent-page');
    await page.click('.error-page__link');
    await expect(page).toHaveURL(/dashboard/);
  });
});
