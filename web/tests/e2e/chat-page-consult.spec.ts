import { expect, test, type Page } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';

// Standalone chat pages (/chat.html, /chat-jishi.html) load the embed widget
// through /chat-shell.js and hand it presentation config via data-* attributes.
// The widget template is served by the backend in production, so it is read
// from the repository and fulfilled here.
const WIDGET_TEMPLATE = fs.readFileSync(
  path.resolve(process.cwd(), '../src/langbot/templates/embed/widget.js'),
  'utf8',
);

const QUICK_QUESTIONS = ['2026 年招生有哪些专业？', '如何报名？'];

function widgetSource(origin: string, quickQuestions: string[]) {
  return WIDGET_TEMPLATE.replaceAll('__LANGBOT_LOCALE__', 'zh_Hans')
    .replaceAll('__LANGBOT_BOT_UUID__', 'bot-1')
    .replaceAll('__LANGBOT_BASE_URL__', origin)
    .replaceAll('__LANGBOT_TURNSTILE_SITE_KEY__', '')
    .replaceAll('__LANGBOT_BUBBLE_ICON__', 'chat')
    .replaceAll(
      '"__LANGBOT_QUICK_QUESTIONS__"',
      JSON.stringify(quickQuestions),
    );
}

async function mockChatBackend(page: Page, quickQuestions: string[] = []) {
  await page.route('**/api/v1/embed/*/widget.js*', async (route) => {
    const origin = new URL(route.request().url()).origin;
    await route.fulfill({
      status: 200,
      contentType: 'application/javascript',
      body: widgetSource(origin, quickQuestions),
    });
  });
  await page.route('**/api/v1/embed/*/messages/**', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ code: 0, data: { messages: [] } }),
    }),
  );
  await page.route('**/api/v1/embed/*/reset/**', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ code: 0, data: {} }),
    }),
  );
  await page.routeWebSocket('**/api/v1/embed/*/ws/connect**', (ws) => {
    ws.onMessage((raw) => {
      if (JSON.parse(String(raw)).type === 'authenticate') {
        ws.send(
          JSON.stringify({
            type: 'connected',
            connection_id: 'chat-page-test',
            session_type: 'person',
          }),
        );
      }
    });
  });
}

function headerBackground(page: Page) {
  return page
    .locator('.lb-header')
    .evaluate((el) => getComputedStyle(el).backgroundColor);
}

// The mocked WebSocket accepts the connection but never answers, so the local
// user message added by sendMessage() is enough to leave the welcome state.
async function sendChatMessage(page: Page, text: string) {
  const send = page.locator('.lb-send-btn');
  await page.locator('.lb-input').fill(text);
  await expect(send).toBeEnabled();
  await send.click();
}

test('chat.html renders the six role tabs with the visitor role selected', async ({
  page,
}) => {
  await mockChatBackend(page, QUICK_QUESTIONS);
  await page.goto('/chat.html');

  await expect(page.locator('#langbot-widget-root')).toBeAttached();
  await expect(page.locator('.lb-panel')).toHaveClass(/lb-visible/);
  // Standalone pages hide the widget's "Powered by LangBot" line.
  await expect(page.locator('.lb-footer')).toBeHidden();

  const tabs = page.locator('.lb-role-tab');
  await expect(tabs).toHaveCount(6);
  await expect(tabs).toHaveText([
    '考生与家长',
    '校内教师',
    '校外教师',
    '校友',
    '来校访客',
    '其他',
  ]);
  await expect(tabs.first()).toHaveClass(/lb-role-active/);

  // An empty role question list falls back to the bot's quick questions.
  const questions = page.locator('.lb-role-question');
  await expect(questions).toHaveCount(QUICK_QUESTIONS.length);
  await expect(questions.first()).toContainText(QUICK_QUESTIONS[0]);

  await expect.poll(() => headerBackground(page)).toBe('rgb(114, 3, 12)');
});

test('switching roles swaps the suggestions and fills the composer', async ({
  page,
}) => {
  await mockChatBackend(page);
  await page.goto('/chat.html');

  const tabs = page.locator('.lb-role-tab');
  await expect(tabs).toHaveCount(6);
  await tabs.filter({ hasText: '校内教师' }).click();

  await expect(page.locator('.lb-role-tab.lb-role-active')).toHaveText(
    '校内教师',
  );

  const questions = page.locator('.lb-role-question');
  await expect(questions.first()).toContainText('在哪里查看学校公开校历？');

  await questions.first().click();
  await expect(page.locator('.lb-input')).toHaveValue(
    '在哪里查看学校公开校历？',
  );
});

test('resetting the conversation keeps the selected role', async ({ page }) => {
  await mockChatBackend(page);
  await page.goto('/chat.html');

  await page.locator('.lb-role-tab').filter({ hasText: '校内教师' }).click();
  await expect(page.locator('.lb-role-tab.lb-role-active')).toHaveText(
    '校内教师',
  );

  await page.locator('.lb-header-btn[aria-label="重置对话"]').click();

  // renderMessages() rebuilds the welcome block after a reset; the role choice
  // is kept in state, so the same tab must come back selected.
  await expect(page.locator('.lb-welcome')).toBeVisible();
  await expect(page.locator('.lb-role-tab')).toHaveCount(6);
  await expect(page.locator('.lb-role-tab.lb-role-active')).toHaveText(
    '校内教师',
  );
  await expect(page.locator('.lb-role-question').first()).toContainText(
    '在哪里查看学校公开校历？',
  );
});

test('the role dock previews questions and expands into tabbed lists', async ({
  page,
}) => {
  await mockChatBackend(page, QUICK_QUESTIONS);
  await page.goto('/chat.html');

  // Closed until the conversation has at least one message.
  const dock = page.locator('.lb-role-dock');
  await expect(dock).toBeHidden();

  await sendChatMessage(page, '你好');
  // addMessage() hides the welcome block instead of removing it.
  await expect(page.locator('.lb-welcome')).toBeHidden();
  await expect(dock).toBeVisible();

  // The first role has no questions of its own, so the preview falls back to
  // the bot's quick questions.
  const preview = page.locator('.lb-role-dock-preview-btn');
  await expect(preview).toHaveCount(QUICK_QUESTIONS.length);
  await expect(preview.first()).toHaveText(QUICK_QUESTIONS[0]);

  const toggle = page.locator('.lb-role-dock-toggle');
  await expect(toggle).toHaveAttribute('aria-expanded', 'false');
  await expect(toggle).toContainText('更多');

  await toggle.click();
  await expect(toggle).toHaveAttribute('aria-expanded', 'true');

  const panel = page.locator('.lb-role-dock-panel');
  await expect(panel).toBeVisible();
  const tabs = panel.locator('.lb-role-tab');
  await expect(tabs).toHaveCount(6);
  await expect(panel.locator('.lb-role-tab.lb-role-active')).toHaveText(
    '考生与家长',
  );

  // Switching roles inside the dock refreshes the preview and the full list
  // without dropping the messages already on screen.
  await tabs.filter({ hasText: '校内教师' }).click();
  await expect(panel.locator('.lb-role-tab.lb-role-active')).toHaveText(
    '校内教师',
  );
  await expect(page.locator('.lb-role-dock-preview-btn')).toHaveCount(3);
  await expect(page.locator('.lb-role-dock-preview-btn').first()).toHaveText(
    '在哪里查看学校公开校历？',
  );
  await expect(panel.locator('.lb-role-question')).toHaveCount(5);
  await expect(page.locator('.lb-msg-user')).toHaveCount(1);

  // Picking a question closes the panel and hands the text to the composer.
  await panel.locator('.lb-role-question').nth(1).click();
  await expect(panel).toBeHidden();
  await expect(toggle).toHaveAttribute('aria-expanded', 'false');
  await expect(page.locator('.lb-input')).toHaveValue(
    '学校有哪些公开教研活动？',
  );
});

test('the technician college dock shows role questions and closes on Escape', async ({
  page,
}) => {
  await mockChatBackend(page);
  await page.goto('/chat-jishi.html');

  await sendChatMessage(page, '你好');

  const preview = page.locator('.lb-role-dock-preview-btn');
  await expect(preview).toHaveCount(3);
  await expect(preview.first()).toHaveText(
    '学院招收初中毕业生还是高中毕业生？',
  );

  const toggle = page.locator('.lb-role-dock-toggle');
  await toggle.click();

  const panel = page.locator('.lb-role-dock-panel');
  await expect(panel).toBeVisible();
  await expect(panel.locator('.lb-role-tab')).toHaveCount(6);
  await expect(panel.locator('.lb-role-question')).toHaveCount(6);

  await page.keyboard.press('Escape');
  await expect(panel).toBeHidden();
  await expect(toggle).toHaveAttribute('aria-expanded', 'false');
});

test('chat-jishi.html uses the technician college accent', async ({ page }) => {
  await mockChatBackend(page);
  await page.goto('/chat-jishi.html');

  await expect(page.locator('.lb-role-tab')).toHaveCount(6);
  await expect(page.locator('.lb-role-tab').first()).toHaveText('考生与家长');
  await expect.poll(() => headerBackground(page)).toBe('rgb(15, 111, 168)');
});

test('URL parameters override the inline page config', async ({ page }) => {
  await mockChatBackend(page);
  await page.goto(
    '/chat.html?title=%E6%B5%8B%E8%AF%95%E5%92%A8%E8%AF%A2&theme=%23123456',
  );

  await expect(page).toHaveTitle('测试咨询');
  await expect(page.locator('.lb-header-title')).toHaveText('测试咨询');
  await expect.poll(() => headerBackground(page)).toBe('rgb(18, 52, 86)');
});
