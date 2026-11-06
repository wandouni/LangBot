import { expect, test } from '@playwright/test';

import { installLangBotApiMocks } from './fixtures/langbot-api';

test('an uninitialized instance forwards login to the registration form', async ({
  page,
}) => {
  await installLangBotApiMocks(page, { initialized: false });

  await page.goto('/login');

  await expect(page).toHaveURL(/\/register$/);
  await expect(
    page.getByText('Initialize LangBot 👋', { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole('button', { name: 'Register with email and password' }),
  ).toBeVisible();
});

test('an initialized instance redirects the registration form to login', async ({
  page,
}) => {
  await installLangBotApiMocks(page);

  await page.goto('/register');

  await expect(page).toHaveURL(/\/login$/);
  await expect(page.getByPlaceholder('Enter email address')).toBeVisible();
});

test('registers the admin account and returns to the login form', async ({
  page,
}) => {
  await installLangBotApiMocks(page, { initialized: false });
  await page.goto('/register');

  await page.getByPlaceholder('Enter email address').fill('admin@example.com');
  await page.getByPlaceholder('Enter password').fill('s3cret-password');

  const initRequest = page.waitForRequest(
    (request) =>
      new URL(request.url()).pathname === '/api/v1/user/init' &&
      request.method() === 'POST',
  );
  await page
    .getByRole('button', { name: 'Register with email and password' })
    .click();

  expect((await initRequest).postDataJSON()).toMatchObject({
    user: 'admin@example.com',
    password: 's3cret-password',
  });
  await expect(
    page.getByText('Initialization successful, please login', { exact: true }),
  ).toBeVisible();
  await expect(page).toHaveURL(/\/login$/);
  await expect(page.getByPlaceholder('Enter email address')).toBeVisible();
});

test('rejects an invalid email before contacting the backend', async ({
  page,
}) => {
  await installLangBotApiMocks(page, { initialized: false });
  await page.goto('/register');

  let initPosts = 0;
  page.on('request', (request) => {
    if (
      new URL(request.url()).pathname === '/api/v1/user/init' &&
      request.method() === 'POST'
    ) {
      initPosts += 1;
    }
  });

  await page.getByPlaceholder('Enter email address').fill('not-an-email');
  await page.getByPlaceholder('Enter password').fill('s3cret-password');
  await page
    .getByRole('button', { name: 'Register with email and password' })
    .click();

  await expect(
    page.getByText('Please enter a valid email address', { exact: true }),
  ).toBeVisible();
  await expect(page).toHaveURL(/\/register$/);
  expect(initPosts).toBe(0);
});

test('shows the backend error when initialization fails', async ({ page }) => {
  await installLangBotApiMocks(page, { initialized: false });
  await page.route('**/api/v1/user/init', async (route) => {
    if (route.request().method() === 'POST') {
      await route.fulfill({
        status: 500,
        contentType: 'application/json',
        body: JSON.stringify({ code: 1, msg: 'registration closed' }),
      });
      return;
    }
    await route.fallback();
  });

  await page.goto('/register');
  await page.getByPlaceholder('Enter email address').fill('admin@example.com');
  await page.getByPlaceholder('Enter password').fill('s3cret-password');
  await page
    .getByRole('button', { name: 'Register with email and password' })
    .click();

  await expect(
    page.getByText('Initialization failed: registration closed', {
      exact: true,
    }),
  ).toBeVisible();
  await expect(page).toHaveURL(/\/register$/);
});

test('hides local registration when the backend disables password login', async ({
  page,
}) => {
  await installLangBotApiMocks(page, {
    initialized: false,
    passwordLoginEnabled: false,
  });

  await page.goto('/register');

  await expect(
    page.getByRole('button', { name: 'Initialize with LangBot Account' }),
  ).toBeVisible();
  await expect(
    page.getByRole('button', { name: 'Register with email and password' }),
  ).toHaveCount(0);
  await expect(page.getByPlaceholder('Enter password')).toHaveCount(0);
});
