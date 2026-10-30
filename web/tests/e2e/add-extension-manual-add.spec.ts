import { expect, test } from '@playwright/test';

import { installLangBotApiMocks } from './fixtures/langbot-api';

// When a deployment turns the Space marketplace off (`plugin.enable_marketplace:
// false`), the page used to return early and hide every manual add entry, so
// "upload local package / MCP / GitHub" links from the sidebar landed on a
// blank page. The manual add entry must stay reachable without the marketplace.
test.describe('add-extension page without the marketplace', () => {
  test('keeps the manual add entry and opens it from ?manual=1', async ({
    page,
  }) => {
    await installLangBotApiMocks(page, {
      authenticated: true,
      marketplaceEnabled: false,
    });

    await page.goto('/home/add-extension?manual=1');

    await expect(
      page.getByText('Extension marketplace is unavailable'),
    ).toBeVisible();
    await expect(
      page.getByRole('button', { name: 'Manual Add' }),
    ).toBeVisible();

    // `?manual=1` is how the sidebar deep-links into the popover; the query
    // param must still open it when the marketplace listing is hidden.
    await expect(
      page.getByText('Drag & drop or click to upload'),
    ).toBeVisible();
    await expect(page.getByText('Install from GitHub')).toBeVisible();
    await expect(page.getByText('Create New Skill')).toBeVisible();
  });

  test('renders the marketplace when it is enabled', async ({ page }) => {
    await installLangBotApiMocks(page, {
      authenticated: true,
      marketplaceEnabled: true,
    });

    await page.goto('/home/add-extension');

    await expect(
      page.getByText('Extension marketplace is unavailable'),
    ).toHaveCount(0);
    await expect(
      page.getByRole('button', { name: 'Manual Add' }),
    ).toBeVisible();
  });
});
