import { expect, Page, test } from '@playwright/test';

import { installLangBotApiMocks } from './fixtures/langbot-api';

const PORTAL_ENABLED = {
  enabled: true,
  sqlbot_enabled: true,
  langbot_path: '/home/monitoring',
  sqlbot_path: '/sqlbot/',
};

async function installPortalMocks(
  page: Page,
  options: { sqlbotEnabled?: boolean } = {},
) {
  await installLangBotApiMocks(page);
  const portal = {
    ...PORTAL_ENABLED,
    sqlbot_enabled: options.sqlbotEnabled ?? true,
  };
  await page.route('**/api/v1/system/info', (route) =>
    route.fulfill({
      json: {
        code: 0,
        message: 'ok',
        data: {
          debug: false,
          version: 'frontend-smoke',
          edition: 'community',
          cloud_service_url: 'https://space.langbot.app',
          enable_marketplace: true,
          allow_modify_login_info: true,
          disable_models_service: false,
          limitation: {
            max_bots: -1,
            max_pipelines: -1,
            max_extensions: -1,
          },
          outbound_ips: [],
          wizard_status: 'completed',
          wizard_progress: null,
          portal,
        },
      },
    }),
  );
  await page.route('**/api/v1/user/sqlbot/sso-ticket', (route) =>
    route.fulfill({
      json: {
        code: 0,
        message: 'ok',
        data: {
          redirect_url: '/sqlbot/#/login?sso_ticket=ticket-playwright',
          expires_in: 60,
        },
      },
    }),
  );
  // Only the document navigation to /sqlbot/; a broader pattern would also
  // swallow the API calls whose path contains "sqlbot".
  await page.route(/\/sqlbot\/$/, (route) =>
    route.fulfill({
      contentType: 'text/html',
      body: '<!doctype html><title>SqlBot</title><p>SqlBot shell</p>',
    }),
  );
}

async function login(page: Page) {
  await page.goto('/login');
  await page.getByPlaceholder('Enter email address').fill('admin@example.com');
  await page.getByPlaceholder('Enter password').fill('password');
  await page.getByRole('button', { name: 'Login with password' }).click();
  await expect(page).toHaveURL(/\/portal$/);
}

function card(page: Page, title: string) {
  return page.locator('[data-slot="card"]').filter({ hasText: title });
}

test('portal-enabled login lands on the application center without home chrome', async ({
  page,
}) => {
  await installPortalMocks(page);
  await login(page);

  await expect(
    page.getByRole('heading', { name: 'Welcome back, admin@example.com' }),
  ).toBeVisible();
  await expect(card(page, 'LangBot')).toBeVisible();
  await expect(card(page, 'SqlBot')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Dashboard' })).toHaveCount(0);
});

test('LangBot card opens the monitoring home', async ({ page }) => {
  await installPortalMocks(page);
  await login(page);

  await card(page, 'LangBot').getByRole('button', { name: 'Open' }).click();

  await expect(page).toHaveURL(/\/home\/monitoring$/);
  await expect(page.getByRole('button', { name: 'Dashboard' })).toBeVisible();
});

test('SqlBot card requests a ticket and hands off to the subpath', async ({
  page,
}) => {
  let ticketRequests = 0;
  await installPortalMocks(page);
  await login(page);

  page.on('request', (request) => {
    if (new URL(request.url()).pathname === '/api/v1/user/sqlbot/sso-ticket') {
      ticketRequests += 1;
    }
  });

  await page.evaluate(() => {
    localStorage.setItem('sqlbot_token', 'stale-token');
    sessionStorage.setItem('sqlbot_platform', 'stale-platform');
  });

  await card(page, 'SqlBot').getByRole('button', { name: 'Open' }).click();

  await page.waitForURL(/\/sqlbot\/#\/login\?sso_ticket=ticket-playwright$/);
  await expect(page.getByText('SqlBot shell')).toBeVisible();
  expect(ticketRequests).toBe(1);
  expect(
    await page.evaluate(() => ({
      local: localStorage.getItem('sqlbot_token'),
      session: sessionStorage.getItem('sqlbot_platform'),
    })),
  ).toEqual({ local: null, session: null });
});

test('disabled SqlBot card stays unavailable', async ({ page }) => {
  await installPortalMocks(page, { sqlbotEnabled: false });
  await login(page);

  await expect(
    card(page, 'SqlBot').getByRole('button', { name: 'Not available' }),
  ).toBeDisabled();
});

test('portal sign out clears LangBot and SqlBot local state', async ({
  page,
}) => {
  await installPortalMocks(page);
  await login(page);

  await page.evaluate(() => {
    localStorage.setItem('sqlbot_token', 'stale-token');
  });
  // The login page auto-resumes on check-token; keep it signed out after the
  // portal drops the token.
  await page.route('**/api/v1/user/check-token', (route) =>
    route.fulfill({
      json: { code: 0, message: 'ok', data: { token: '' } },
    }),
  );

  await page.getByRole('button', { name: 'Sign out' }).click();

  await expect(page).toHaveURL(/\/login$/);
  await expect(
    page.getByRole('button', { name: 'Login with password' }),
  ).toBeVisible();
  expect(
    await page.evaluate(() => ({
      token: localStorage.getItem('token'),
      sqlbot: localStorage.getItem('sqlbot_token'),
    })),
  ).toEqual({ token: null, sqlbot: null });
});

test('SqlBot handoff logout clears both sessions and the query parameter', async ({
  page,
}) => {
  await installPortalMocks(page);
  await page.route('**/api/v1/user/check-token', (route) =>
    route.fulfill({
      json: { code: 0, message: 'ok', data: { token: '' } },
    }),
  );

  await page.goto('/login');
  await page.evaluate(() => {
    localStorage.setItem('token', 'langbot-token');
    localStorage.setItem('userEmail', 'admin@example.com');
    localStorage.setItem('sqlbot_portal_session', '1');
    localStorage.setItem('sqlbot_user.token', 'sqlbot-token');
  });

  await page.goto('/login?logout=1');

  await expect(page).toHaveURL(/\/login$/);
  expect(
    await page.evaluate(() => ({
      token: localStorage.getItem('token'),
      userEmail: localStorage.getItem('userEmail'),
      sqlbotKeys: Object.keys(localStorage).filter((key) =>
        key.startsWith('sqlbot_'),
      ),
    })),
  ).toEqual({ token: null, userEmail: null, sqlbotKeys: [] });
});
