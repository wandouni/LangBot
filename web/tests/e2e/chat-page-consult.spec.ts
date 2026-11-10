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

type QuickQuestionGroup = {
  id: string;
  label: string;
  questions: string[];
};

const COLLEGE_ROLE_GROUPS: QuickQuestionGroup[] = [
  { id: 'prospective-student-parent', label: '考生与家长', questions: [] },
  {
    id: 'internal-teacher',
    label: '校内教师',
    questions: [
      '在哪里查看学校公开校历？',
      '学校有哪些公开教研活动？',
      '教师培训信息在哪里查询？',
      '如何了解对外交流合作项目？',
      '校内个人业务应从哪个正式入口办理？',
    ],
  },
  {
    id: 'external-teacher',
    label: '校外教师',
    questions: [
      '如何咨询访学交流？',
      '如何了解公开教研活动？',
      '教师培训有哪些报名渠道？',
      '校际合作应联系哪个部门？',
      '来校学术交流需要办理哪些手续？',
    ],
  },
  { id: 'alumni', label: '校友', questions: ['如何申请成绩单？'] },
  {
    id: 'campus-visitor',
    label: '来校访客',
    questions: ['学校各校区的地址是什么？'],
  },
  { id: 'other', label: '其他', questions: ['学校有哪些对外公开服务？'] },
];

const JISHI_ROLE_GROUPS: QuickQuestionGroup[] = [
  {
    id: 'prospective-student-parent',
    label: '考生与家长',
    questions: [
      '学院招收初中毕业生还是高中毕业生？',
      '学院有哪些招生专业？',
      '报名需要什么条件？',
      '学费和住宿费多少？',
      '有哪些奖助学金？',
      '怎么联系招生办？',
    ],
  },
  {
    id: 'internal-teacher',
    label: '校内教师',
    questions: ['公开校历在哪里查看？'],
  },
  {
    id: 'partner-company',
    label: '合作企业',
    questions: ['如何开展校企合作？'],
  },
  { id: 'alumni', label: '校友', questions: ['如何补办毕业证明？'] },
  {
    id: 'campus-visitor',
    label: '来校访客',
    questions: ['学院各校区地址是什么？'],
  },
  { id: 'other', label: '其他', questions: ['学院有哪些公开服务？'] },
];

function previewUrl(
  path: string,
  groups: QuickQuestionGroup[],
  welcome?: string,
) {
  const params = [`preview=${encodeURIComponent(JSON.stringify(groups))}`];
  if (welcome !== undefined) {
    params.push(`previewWelcome=${encodeURIComponent(welcome)}`);
  }
  return `${path}#${params.join('&')}`;
}

function widgetSource(origin: string, roleGroups: QuickQuestionGroup[] = []) {
  return WIDGET_TEMPLATE.replaceAll('__LANGBOT_LOCALE__', 'zh_Hans')
    .replaceAll('__LANGBOT_BOT_UUID__', 'bot-1')
    .replaceAll('__LANGBOT_BASE_URL__', origin)
    .replaceAll('__LANGBOT_TURNSTILE_SITE_KEY__', '')
    .replaceAll('__LANGBOT_BUBBLE_ICON__', 'chat')
    .replaceAll('"__LANGBOT_ROLE_GROUPS__"', JSON.stringify(roleGroups))
    .replaceAll('"__LANGBOT_WELCOME_MESSAGE__"', JSON.stringify(''));
}

// The quick link menu is driven by the inline #chat-config JSON. These are the
// six production entries; keep the expected hrefs in sync with chat.html.
const QUICK_LINKS = [
  {
    label: '广州校区VR全景',
    href: 'https://www.720yun.com/vr/89cjtgkkrw7?s=19327510',
  },
  {
    label: '清远校区VR全景',
    href: 'https://www.720yun.com/vr/408jtgkkuO1?s=19217486',
  },
  { label: '录取查询', href: 'https://lnc.edu.cn/zsw/xszn/lqcxl' },
  { label: '招生计划', href: 'https://lnc.edu.cn/zsw/zsjh/byaejbejqq' },
  { label: '招生简章', href: 'https://lnc.edu.cn/zsw/zsjz/2021nzsjz' },
  { label: '新生指南', href: 'https://lnc.edu.cn/zsw/xszn/jtzn' },
];

type ChatConfig = {
  links?: Array<{ label: string; url: string }>;
};

// Rewrite the inline config before the page script parses it. Registered with
// page.route() before goto so the test never touches the real chat.html file.
function rewriteChatConfig(html: string, mutate: (config: ChatConfig) => void) {
  return html.replace(
    /(<script type="application\/json" id="chat-config">)([\s\S]*?)(<\/script>)/,
    (_match, open: string, body: string, close: string) => {
      const config = JSON.parse(body) as ChatConfig;
      mutate(config);
      return `${open}\n${JSON.stringify(config, null, 2)}\n${close}`;
    },
  );
}

async function serveChatHtml(page: Page, mutate: (config: ChatConfig) => void) {
  const html = fs.readFileSync(
    path.resolve(process.cwd(), 'public/chat.html'),
    'utf8',
  );
  await page.route('**/chat.html', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'text/html',
      body: rewriteChatConfig(html, mutate),
    }),
  );
}

async function mockChatBackend(
  page: Page,
  roleGroups: QuickQuestionGroup[] = [],
) {
  await page.route('**/api/v1/embed/*/widget.js*', async (route) => {
    const origin = new URL(route.request().url()).origin;
    await route.fulfill({
      status: 200,
      contentType: 'application/javascript',
      body: widgetSource(origin, roleGroups),
    });
  });
  // The widget signs a session token before opening its WebSocket, even when
  // Turnstile is disabled; without this route the socket never connects.
  await page.route('**/api/v1/embed/*/turnstile/verify', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        code: 0,
        msg: 'ok',
        data: { token: 'chat-page-test-token' },
      }),
    }),
  );
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
  await page.route('**/api/v1/embed/*/consult-messages', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ code: 0, msg: 'ok', data: { ok: true } }),
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

test('chat.html renders no suggestions without saved groups', async ({
  page,
}) => {
  await mockChatBackend(page);
  await page.goto('/chat.html');

  await expect(page.locator('#langbot-widget-root')).toBeAttached();
  await expect(page.locator('.lb-panel')).toHaveClass(/lb-visible/);
  // Standalone pages hide the widget's "Powered by LangBot" line.
  await expect(page.locator('.lb-footer')).toBeHidden();

  // There is no page-level fallback anymore.
  await expect(page.locator('.lb-role-tab')).toHaveCount(0);
  await expect(page.locator('.lb-role-question')).toHaveCount(0);
  await expect(page.locator('.lb-quick-btn')).toHaveCount(0);

  await expect.poll(() => headerBackground(page)).toBe('rgb(114, 3, 12)');
});

test('the preview hash renders the unsaved draft roles', async ({ page }) => {
  await mockChatBackend(page);
  await page.goto(previewUrl('/chat.html', COLLEGE_ROLE_GROUPS));

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

  // The first draft group is intentionally empty.
  await expect(page.locator('.lb-role-question')).toHaveCount(0);
});

test('the preview hash renders the unsaved welcome message', async ({
  page,
}) => {
  await mockChatBackend(page);
  await page.goto(previewUrl('/chat.html', [], '草稿欢迎语：无需保存即可预览'));

  await expect(page.locator('.lb-welcome')).toContainText(
    '草稿欢迎语：无需保存即可预览',
  );
});

test('switching roles swaps the suggestions and fills the composer', async ({
  page,
}) => {
  await mockChatBackend(page);
  await page.goto(previewUrl('/chat.html', COLLEGE_ROLE_GROUPS));

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

test('saved bot quick question groups render their tabs', async ({ page }) => {
  const groups: QuickQuestionGroup[] = [
    {
      id: 'g1',
      label: '后台分类一',
      questions: ['后台问题一', '后台问题二'],
    },
    { id: 'g2', label: '后台分类二', questions: ['后台问题三'] },
  ];
  await mockChatBackend(page, groups);
  await page.goto('/chat-jishi.html');

  const tabs = page.locator('.lb-role-tab');
  await expect(tabs).toHaveCount(2);
  await expect(tabs).toHaveText(['后台分类一', '后台分类二']);

  const questions = page.locator('.lb-role-question');
  await expect(questions).toHaveCount(2);
  await expect(questions.first()).toContainText('后台问题一');

  await tabs.filter({ hasText: '后台分类二' }).click();
  await expect(page.locator('.lb-role-tab.lb-role-active')).toHaveText(
    '后台分类二',
  );
  await expect(page.locator('.lb-role-question')).toHaveCount(1);
  await expect(page.locator('.lb-role-question').first()).toContainText(
    '后台问题三',
  );
});

test('an empty bot group renders no suggestions', async ({ page }) => {
  await mockChatBackend(page, [{ id: 'g1', label: '空分类', questions: [] }]);
  await page.goto('/chat-jishi.html');

  await expect(page.locator('.lb-role-tab')).toHaveCount(1);
  await expect(page.locator('.lb-role-tab')).toHaveText('空分类');
  await expect(page.locator('.lb-role-question')).toHaveCount(0);
});

test('resetting the conversation keeps the selected role', async ({ page }) => {
  await mockChatBackend(page);
  await page.goto(previewUrl('/chat.html', COLLEGE_ROLE_GROUPS));

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
  await mockChatBackend(page);
  await page.goto(previewUrl('/chat.html', COLLEGE_ROLE_GROUPS));

  // Select a role with its own questions; the visitor role is intentionally
  // empty and no longer borrows questions from anywhere else.
  await page.locator('.lb-role-tab').filter({ hasText: '校内教师' }).click();
  await expect(page.locator('.lb-role-tab.lb-role-active')).toHaveText(
    '校内教师',
  );

  // Closed until the conversation has at least one message.
  const dock = page.locator('.lb-role-dock');
  await expect(dock).toBeHidden();

  await sendChatMessage(page, '你好');
  // addMessage() hides the welcome block instead of removing it.
  await expect(page.locator('.lb-welcome')).toBeHidden();
  await expect(dock).toBeVisible();

  const preview = page.locator('.lb-role-dock-preview-btn');
  await expect(preview).toHaveCount(3);
  await expect(preview.first()).toHaveText('在哪里查看学校公开校历？');

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
    '校内教师',
  );
  await expect(panel.locator('.lb-role-question')).toHaveCount(5);

  // Switching roles inside the dock refreshes the preview and the full list
  // without dropping the messages already on screen.
  await tabs.filter({ hasText: '校外教师' }).click();
  await expect(panel.locator('.lb-role-tab.lb-role-active')).toHaveText(
    '校外教师',
  );
  await expect(page.locator('.lb-role-dock-preview-btn')).toHaveCount(3);
  await expect(page.locator('.lb-role-dock-preview-btn').first()).toHaveText(
    '如何咨询访学交流？',
  );
  await expect(panel.locator('.lb-role-question')).toHaveCount(5);
  await expect(page.locator('.lb-msg-user')).toHaveCount(1);

  // Picking a question closes the panel and hands the text to the composer.
  await panel.locator('.lb-role-question').nth(1).click();
  await expect(panel).toBeHidden();
  await expect(toggle).toHaveAttribute('aria-expanded', 'false');
  await expect(page.locator('.lb-input')).toHaveValue('如何了解公开教研活动？');
});

test('the technician college dock shows role questions and closes on Escape', async ({
  page,
}) => {
  await mockChatBackend(page);
  await page.goto(previewUrl('/chat-jishi.html', JISHI_ROLE_GROUPS));

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

  await expect.poll(() => headerBackground(page)).toBe('rgb(15, 111, 168)');
});

test('default.html uses the default robot logo and blue', async ({ page }) => {
  await mockChatBackend(page);
  await page.goto('/default.html');

  await expect(page.locator('.lb-welcome-logo')).toHaveAttribute(
    'src',
    /\/api\/v1\/embed\/logo$/,
  );
  await expect.poll(() => headerBackground(page)).toBe('rgb(37, 99, 235)');
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

test('the message board collects a lead from chat.html', async ({ page }) => {
  let submitted: Record<string, string> | null = null;
  await mockChatBackend(page);
  await page.route('**/api/v1/embed/*/consult-messages', async (route) => {
    submitted = route.request().postDataJSON();
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ code: 0, msg: 'ok', data: { ok: true } }),
    });
  });
  await page.goto('/chat.html');

  const launcher = page.locator('#ln-consult-launcher');
  await expect(launcher).toBeVisible();
  await expect(launcher).toHaveText('留言板');
  await launcher.click();

  const dialog = page.locator('#ln-consult-dialog');
  await expect(dialog).toBeVisible();
  await expect(dialog).toContainText(
    '提交后招生办老师根据您的信息提供更加详细的院校和专业建议。',
  );

  await page.locator('#ln-consult-province').fill('广东省');
  await page.locator('#ln-consult-city').fill('广州市');
  await page.locator('#ln-consult-name').fill('张三');
  await page.locator('#ln-consult-score').fill('520');
  await page.locator('#ln-consult-contact').fill('13800000000');
  await page.locator('#ln-consult-save').click();

  await expect(page.locator('#ln-consult-message')).toHaveText(
    '提交成功，招生办老师将尽快与您联系',
  );
  expect(submitted).toMatchObject({
    province: '广东省',
    city: '广州市',
    name: '张三',
    score: '520',
    contact: '13800000000',
  });
  await expect(page.locator('#ln-consult-overlay')).toBeHidden({
    timeout: 3000,
  });
});

test('the message board stays available on the admin preview hash', async ({
  page,
}) => {
  await mockChatBackend(page);
  await page.goto(previewUrl('/chat.html', COLLEGE_ROLE_GROUPS));

  await expect(page.locator('#langbot-widget-root')).toBeAttached();
  const launcher = page.locator('#ln-consult-launcher');
  await expect(launcher).toBeVisible();
  await launcher.click();
  await expect(page.locator('#ln-consult-dialog')).toBeVisible();
});

test('the message board keeps the form open when saving fails', async ({
  page,
}) => {
  await mockChatBackend(page);
  await page.route('**/api/v1/embed/*/consult-messages', (route) =>
    route.fulfill({
      status: 400,
      contentType: 'application/json',
      body: JSON.stringify({ code: -1, msg: 'province is required' }),
    }),
  );
  await page.goto('/chat-jishi.html');

  await page.locator('#ln-consult-launcher').click();
  await page.locator('#ln-consult-province').fill('广东省');
  await page.locator('#ln-consult-city').fill('广州市');
  await page.locator('#ln-consult-name').fill('张三');
  await page.locator('#ln-consult-score').fill('520');
  await page.locator('#ln-consult-contact').fill('13800000000');
  await page.locator('#ln-consult-save').click();

  await expect(page.locator('#ln-consult-message')).toHaveText(
    'province is required',
  );
  await expect(page.locator('#ln-consult-overlay')).toBeVisible();
  await expect(page.locator('#ln-consult-save')).toBeEnabled();
});

test('the message board validates required fields before submitting', async ({
  page,
}) => {
  let submissions = 0;
  await mockChatBackend(page);
  await page.route('**/api/v1/embed/*/consult-messages', async (route) => {
    submissions += 1;
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ code: 0, msg: 'ok', data: { ok: true } }),
    });
  });
  await page.goto('/chat.html');

  await page.locator('#ln-consult-launcher').click();
  await page.locator('#ln-consult-save').click();

  await expect(page.locator('#ln-consult-message')).toHaveText(
    '请填写所有必填项。',
  );
  await expect(page.locator('#ln-consult-province')).toBeFocused();
  expect(submissions).toBe(0);
});

test('the technician college message board uses its accent and can close', async ({
  page,
}) => {
  await mockChatBackend(page);
  await page.goto('/chat-jishi.html');

  const launcher = page.locator('#ln-consult-launcher');
  await expect(launcher).toBeVisible();
  await expect
    .poll(() => launcher.evaluate((el) => getComputedStyle(el).backgroundColor))
    .toBe('rgb(15, 111, 168)');

  await launcher.click();
  await expect(page.locator('#ln-consult-overlay')).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.locator('#ln-consult-overlay')).toBeHidden();
});

test('default.html has no message board entry', async ({ page }) => {
  await mockChatBackend(page);
  await page.goto('/default.html');

  await expect(page.locator('#langbot-widget-root')).toBeAttached();
  await expect(page.locator('#ln-consult-launcher')).toHaveCount(0);
});

test('the quick link button sits left of the message board', async ({
  page,
}) => {
  await mockChatBackend(page);
  await page.goto('/chat.html');

  const toggle = page.locator('#ln-quick-toggle');
  const launcher = page.locator('#ln-consult-launcher');
  await expect(toggle).toBeVisible();
  await expect(toggle).toHaveAttribute('aria-haspopup', 'menu');
  await expect(toggle).toHaveAttribute('aria-expanded', 'false');
  await expect(toggle).toHaveAttribute('aria-label', '快捷链接导航');
  await expect(page.locator('#ln-quick-menu')).toBeHidden();

  await expect(launcher).toBeVisible();
  const toggleBox = await toggle.boundingBox();
  const launcherBox = await launcher.boundingBox();
  const viewport = page.viewportSize();
  expect(toggleBox).not.toBeNull();
  expect(launcherBox).not.toBeNull();
  expect(viewport).not.toBeNull();

  // Both buttons share the fixed right offset: the message board keeps the
  // original 88px gap to the widget's own reset/close actions.
  expect(viewport!.width - (launcherBox!.x + launcherBox!.width)).toBeCloseTo(
    88,
    0,
  );
  expect(toggleBox!.x + toggleBox!.width).toBeLessThanOrEqual(launcherBox!.x);
});

test('hovering the quick link button opens six external links', async ({
  page,
}) => {
  await mockChatBackend(page);
  await page.goto('/chat.html');

  const toggle = page.locator('#ln-quick-toggle');
  const menu = page.locator('#ln-quick-menu');
  await toggle.hover();
  await expect(menu).toBeVisible();
  await expect(toggle).toHaveAttribute('aria-expanded', 'true');

  const items = menu.locator('[role="menuitem"]');
  await expect(items).toHaveCount(QUICK_LINKS.length);
  await expect(menu.locator('.ln-quick-text')).toHaveText(
    QUICK_LINKS.map((link) => link.label),
  );

  for (let index = 0; index < QUICK_LINKS.length; index += 1) {
    await expect(items.nth(index)).toHaveAttribute(
      'href',
      QUICK_LINKS[index].href,
    );
    await expect(items.nth(index)).toHaveAttribute('target', '_blank');
    await expect(items.nth(index)).toHaveAttribute(
      'rel',
      'noopener noreferrer',
    );
  }

  // The menu must stay inside the hover container, otherwise crossing the 8px
  // gap between button and menu closes it.
  expect(await menu.evaluate((node) => node.parentElement?.id)).toBe(
    'ln-quick-nav',
  );
});

test('moving the pointer away closes the quick link menu', async ({ page }) => {
  await mockChatBackend(page);
  await page.goto('/chat.html');

  const menu = page.locator('#ln-quick-menu');
  await page.locator('#ln-quick-toggle').hover();
  await expect(menu).toBeVisible();

  await page.mouse.move(20, 500);
  await expect(menu).toBeHidden();
});

test('Escape closes the quick link menu and restores focus', async ({
  page,
}) => {
  await mockChatBackend(page);
  await page.goto('/chat.html');

  const toggle = page.locator('#ln-quick-toggle');
  const menu = page.locator('#ln-quick-menu');
  await toggle.focus();
  await page.keyboard.press('Enter');
  await expect(menu).toBeVisible();

  await page.keyboard.press('Escape');
  await expect(menu).toBeHidden();
  await expect(toggle).toHaveAttribute('aria-expanded', 'false');
  await expect(toggle).toBeFocused();
});

test('the quick link menu supports arrow, Home and End keys', async ({
  page,
}) => {
  await mockChatBackend(page);
  await page.goto('/chat.html');

  const toggle = page.locator('#ln-quick-toggle');
  const menu = page.locator('#ln-quick-menu');
  const items = menu.locator('[role="menuitem"]');

  await toggle.focus();
  await page.keyboard.press('Enter');
  await page.keyboard.press('ArrowDown');
  await expect(items.nth(0)).toBeFocused();

  await page.keyboard.press('ArrowDown');
  await expect(items.nth(1)).toBeFocused();

  await page.keyboard.press('End');
  await expect(items.nth(QUICK_LINKS.length - 1)).toBeFocused();

  await page.keyboard.press('Home');
  await expect(items.nth(0)).toBeFocused();

  await page.keyboard.press('Escape');
  await expect(menu).toBeHidden();
  await expect(toggle).toBeFocused();
});

test('clicking outside closes the quick link menu', async ({ page }) => {
  await mockChatBackend(page);
  await page.goto('/chat.html');

  const menu = page.locator('#ln-quick-menu');
  await page.locator('#ln-quick-toggle').focus();
  await page.keyboard.press('Enter');
  await expect(menu).toBeVisible();

  await page.mouse.click(20, 500);
  await expect(menu).toBeHidden();
});

test('closing the chat hides the page tools until it reopens', async ({
  page,
}) => {
  await mockChatBackend(page);
  await page.goto('/chat.html');

  const tools = page.locator('#ln-consult-tools');
  const panel = page.locator('.lb-panel');
  const bubble = page.locator('.lb-bubble');
  await expect(panel).toHaveClass(/lb-visible/);
  await expect(tools).toBeVisible();

  // While the panel is open the floating bubble doubles as its close button.
  await bubble.click();
  await expect(panel).not.toHaveClass(/lb-visible/);
  await expect(tools).toBeHidden();

  await bubble.click();
  await expect(panel).toHaveClass(/lb-visible/);
  await expect(tools).toBeVisible();

  // chat-shell injects the full-viewport override as soon as the widget root
  // appears, so the default bottom-right popup never paints. It also disables
  // the widget's scale/fade entrance, which would shrink the whole page.
  const override = await page
    .locator('#langbot-widget-root')
    .evaluate((root) => {
      const style = root.shadowRoot?.querySelector(
        'style[data-layout-override]',
      );
      return style?.textContent ?? '';
    });
  expect(override).toContain('transition: none');
});

test.describe('quick links on a phone', () => {
  test.use({
    viewport: { width: 390, height: 844 },
    hasTouch: true,
    isMobile: true,
  });

  test('tap toggles the menu and keeps it inside the viewport', async ({
    page,
  }) => {
    await mockChatBackend(page);
    await page.goto('/chat.html');

    const toggle = page.locator('#ln-quick-toggle');
    const menu = page.locator('#ln-quick-menu');
    await expect(toggle.locator('.ln-quick-label-short')).toBeVisible();
    await expect(toggle.locator('.ln-quick-label-full')).toBeHidden();

    await toggle.tap();
    await expect(menu).toBeVisible();
    const box = await menu.boundingBox();
    expect(box).not.toBeNull();
    expect(box!.x).toBeGreaterThanOrEqual(0);
    expect(box!.x + box!.width).toBeLessThanOrEqual(390);
    expect(box!.y + box!.height).toBeLessThanOrEqual(844);

    await toggle.tap();
    await expect(menu).toBeHidden();

    await toggle.tap();
    await expect(menu).toBeVisible();
    await page.touchscreen.tap(20, 500);
    await expect(menu).toBeHidden();
  });
});

test('quick links skip non-http(s) urls', async ({ page }) => {
  await serveChatHtml(page, (config) => {
    config.links![0].url = 'javascript:alert(1)';
    config.links![3].url = 'ftp://example.com/x';
  });
  await mockChatBackend(page);
  await page.goto('/chat.html');

  await page.locator('#ln-quick-toggle').hover();
  const items = page.locator('#ln-quick-menu [role="menuitem"]');
  await expect(items).toHaveCount(QUICK_LINKS.length - 2);
  await expect(
    page.locator('#ln-quick-menu a[href^="javascript:"]'),
  ).toHaveCount(0);
  await expect(page.locator('#ln-quick-menu a[href^="ftp:"]')).toHaveCount(0);
  await expect(page.locator('#ln-quick-menu .ln-quick-text')).toHaveText([
    QUICK_LINKS[1].label,
    QUICK_LINKS[2].label,
    QUICK_LINKS[4].label,
    QUICK_LINKS[5].label,
  ]);
});

test('an empty links array hides the quick link button', async ({ page }) => {
  await serveChatHtml(page, (config) => {
    config.links = [];
  });
  await mockChatBackend(page);
  await page.goto('/chat.html');

  await expect(page.locator('#ln-quick-nav')).toBeHidden();
  await expect(page.locator('#ln-consult-launcher')).toBeVisible();
});

test('the quick link navigation is chat.html only', async ({ page }) => {
  await mockChatBackend(page);
  await page.goto('/chat-jishi.html');
  await expect(page.locator('#ln-quick-toggle')).toHaveCount(0);

  await page.goto('/default.html');
  await expect(page.locator('#ln-quick-toggle')).toHaveCount(0);
});
