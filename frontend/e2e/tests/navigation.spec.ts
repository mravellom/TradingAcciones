import { test, expect } from '@playwright/test';

test.describe('Navigation', () => {
  test('should redirect root to dashboard', async ({ page }) => {
    await page.goto('/');
    await expect(page).toHaveURL(/dashboard/);
  });

  test('should navigate to trades page', async ({ page }) => {
    await page.goto('/');
    await page.click('a[href="/trades"]');
    await expect(page).toHaveURL(/trades/);
  });

  test('should navigate to strategies page', async ({ page }) => {
    await page.goto('/');
    await page.click('a[href="/strategies"]');
    await expect(page).toHaveURL(/strategies/);
  });

  test('should navigate to risk panel', async ({ page }) => {
    await page.goto('/');
    await page.click('a[href="/risk"]');
    await expect(page).toHaveURL(/risk/);
  });

  test('should navigate to analytics', async ({ page }) => {
    await page.goto('/');
    await page.click('a[href="/analytics"]');
    await expect(page).toHaveURL(/analytics/);
  });

  test('should show 404 for unknown routes', async ({ page }) => {
    await page.goto('/this-does-not-exist');
    await expect(page.locator('.error-page__code')).toContainText('404');
  });

  test('should have sidebar with all links', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('.nav-links a')).toHaveCount(5);
  });
});
