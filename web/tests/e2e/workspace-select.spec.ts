import { expect, test } from '@playwright/test';

import {
  installLangBotApiMocks,
  makeWorkspaceEntry,
} from './fixtures/langbot-api';

const twoWorkspaces = () => [
  makeWorkspaceEntry('workspace-alpha', 'Alpha Workspace'),
  makeWorkspaceEntry('workspace-beta', 'Beta Workspace'),
];

test('choosing a Workspace scopes the session and honors the return path', async ({
  page,
}) => {
  const selectedWorkspaceHeaders: string[] = [];
  page.on('request', (request) => {
    const path = new URL(request.url()).pathname;
    const workspace = request.headers()['x-workspace-id'];
    if (path === '/api/v1/workspaces/current' && workspace) {
      selectedWorkspaceHeaders.push(workspace);
    }
  });

  await installLangBotApiMocks(page, {
    authenticated: true,
    workspaces: twoWorkspaces(),
  });

  await page.goto('/workspaces/select?returnTo=/home/monitoring');

  await expect(
    page.getByRole('heading', { name: 'Choose a Workspace' }),
  ).toBeVisible();
  await expect(page.getByText('Alpha Workspace')).toBeVisible();
  await expect(page.getByText('Beta Workspace')).toBeVisible();

  await page.getByRole('button', { name: /Beta Workspace/ }).click();

  await expect(page).toHaveURL(/\/home\/monitoring$/);
  expect(selectedWorkspaceHeaders).toContain('workspace-beta');
  expect(selectedWorkspaceHeaders).not.toContain('workspace-alpha');
});

test('an untrusted return path falls back to home', async ({ page }) => {
  await installLangBotApiMocks(page, {
    authenticated: true,
    workspaces: twoWorkspaces(),
  });

  await page.goto('/workspaces/select?returnTo=//evil.example/phish');

  await expect(
    page.getByRole('heading', { name: 'Choose a Workspace' }),
  ).toBeVisible();
  await page.getByRole('button', { name: /Alpha Workspace/ }).click();

  await expect(page).toHaveURL(/\/home$/);
  expect(new URL(page.url()).hostname).toBe('127.0.0.1');
});

test('a failed bootstrap shows an error and the retry reloads the list', async ({
  page,
}) => {
  await installLangBotApiMocks(page, {
    authenticated: true,
    workspaces: twoWorkspaces(),
  });

  let bootstrapAttempts = 0;
  let backendAvailable = false;
  await page.route('**/api/v1/workspaces/bootstrap', async (route) => {
    bootstrapAttempts += 1;
    if (!backendAvailable) {
      await route.fulfill({
        status: 500,
        contentType: 'application/json',
        body: JSON.stringify({ code: 1, msg: 'database unavailable' }),
      });
      return;
    }
    await route.fallback();
  });

  await page.goto('/workspaces/select');

  await expect(
    page.getByText('Your Workspaces could not be loaded. Please try again.', {
      exact: true,
    }),
  ).toBeVisible();
  await expect(page.getByText('Alpha Workspace')).toHaveCount(0);

  backendAvailable = true;
  await page.getByRole('button', { name: 'Retry' }).click();

  await expect(page.getByText('Alpha Workspace')).toBeVisible();
  await expect(page.getByText('Beta Workspace')).toBeVisible();
  await expect(
    page.getByText('Your Workspaces could not be loaded. Please try again.', {
      exact: true,
    }),
  ).toHaveCount(0);
  expect(bootstrapAttempts).toBeGreaterThanOrEqual(2);
});

test('signing out clears the stored session', async ({ page }) => {
  await installLangBotApiMocks(page, {
    authenticated: true,
    workspaces: twoWorkspaces(),
  });

  await page.goto('/workspaces/select');
  await expect(
    page.getByRole('heading', { name: 'Choose a Workspace' }),
  ).toBeVisible();

  await page.getByRole('button', { name: 'Logout' }).click();

  await expect(page).toHaveURL(/\/login$/);
  await expect(page.getByPlaceholder('Enter email address')).toBeVisible();
  await expect(
    page.getByRole('heading', { name: 'Choose a Workspace' }),
  ).toHaveCount(0);
});
