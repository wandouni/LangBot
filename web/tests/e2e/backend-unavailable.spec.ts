import { expect, test } from '@playwright/test';

import { installLangBotApiMocks } from './fixtures/langbot-api';

const RETURN_TO_STORAGE_KEY = 'langbot_backend_unavailable_return_to';

test('renders the outage state with recovery actions', async ({ page }) => {
  await installLangBotApiMocks(page);

  await page.goto('/backend-unavailable');

  await expect(
    page.getByText('Backend unavailable', { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole('heading', { name: 'Unable to connect to server' }),
  ).toBeVisible();
  await expect(
    page.getByRole('button', { name: 'Back to Login' }),
  ).toBeVisible();
  await expect(page.getByRole('button', { name: 'Retry' })).toBeVisible();
});

test('a failed retry keeps the operator on the outage page', async ({
  page,
}) => {
  await installLangBotApiMocks(page);
  await page.route('**/api/v1/system/info', async (route) => {
    await route.fulfill({
      status: 500,
      contentType: 'application/json',
      body: JSON.stringify({ code: 1, msg: 'backend dial failed' }),
    });
  });

  await page.goto('/backend-unavailable');
  await page.getByRole('button', { name: 'Retry' }).click();

  await expect(
    page.getByText(
      'Still cannot connect to the backend. Start the service and try again.',
      { exact: true },
    ),
  ).toBeVisible();
  await expect(page).toHaveURL(/\/backend-unavailable$/);
});

test('a successful retry returns to the path that went offline', async ({
  page,
}) => {
  await installLangBotApiMocks(page);
  await page.addInitScript(
    ({ key }) => {
      sessionStorage.setItem(key, '/home/monitoring');
    },
    { key: RETURN_TO_STORAGE_KEY },
  );

  await page.goto('/backend-unavailable');
  await page.getByRole('button', { name: 'Retry' }).click();

  await expect(page).toHaveURL(/\/home\/monitoring$/);
  const storedReturnTo = await page.evaluate(
    (key) => sessionStorage.getItem(key),
    RETURN_TO_STORAGE_KEY,
  );
  expect(storedReturnTo).toBeNull();
});

test('a successful retry sends an uninitialized instance to the wizard', async ({
  page,
}) => {
  await installLangBotApiMocks(page);
  await page.route('**/api/v1/system/info', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        code: 0,
        message: 'ok',
        data: {
          debug: false,
          version: 'frontend-smoke',
          edition: 'community',
          cloud_service_url: 'https://space.langbot.app',
          enable_marketplace: false,
          allow_modify_login_info: true,
          disable_models_service: false,
          limitation: {
            max_bots: -1,
            max_pipelines: -1,
            max_extensions: -1,
          },
          outbound_ips: [],
          wizard_status: 'none',
          wizard_progress: null,
        },
        timestamp: Date.now(),
      }),
    });
  });

  await page.goto('/backend-unavailable');
  await page.getByRole('button', { name: 'Retry' }).click();

  await expect(page).toHaveURL(/\/wizard$/);
});
