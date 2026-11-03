import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
import ts from 'typescript';

function loadTs(relativePath) {
  const source = readFileSync(new URL(relativePath, import.meta.url), 'utf8');
  const m = { exports: {} };
  new Function(
    'module',
    'exports',
    'require',
    ts.transpileModule(source, {
      compilerOptions: {
        module: ts.ModuleKind.CommonJS,
        target: ts.ScriptTarget.ES2022,
      },
    }).outputText,
  )(m, m.exports, () => ({}));
  return m.exports;
}

const {
  STANDALONE_CHAT_PAGES,
  buildQuickQuestionPreviewHash,
  buildStandaloneChatPageUrl,
  buildWelcomePreviewHash,
} = loadTs('../../src/app/home/components/dynamic-form/standaloneChatPages.ts');

test('offers the three standalone chat pages', () => {
  assert.deepEqual(STANDALONE_CHAT_PAGES, [
    'chat.html',
    'chat-jishi.html',
    'default.html',
  ]);
});

test('builds a page URL that targets the bot being edited', () => {
  assert.equal(
    buildStandaloneChatPageUrl(
      'http://192.168.31.66:5300',
      'chat-jishi.html',
      'a1b2c3d4-e5f6-7890-abcd-ef1234567890',
    ),
    'http://192.168.31.66:5300/chat-jishi.html?embed=a1b2c3d4-e5f6-7890-abcd-ef1234567890',
  );
});

test('keeps the console base path and trims the bot uuid', () => {
  assert.equal(
    buildStandaloneChatPageUrl(
      'http://127.0.0.1:3000/',
      'default.html',
      '  bot-1  ',
    ),
    'http://127.0.0.1:3000/default.html?embed=bot-1',
  );
});

test('omits the embed parameter when no bot is selected', () => {
  assert.equal(
    buildStandaloneChatPageUrl('http://127.0.0.1:3000', 'chat.html', '   '),
    'http://127.0.0.1:3000/chat.html',
  );
});

test('encodes the quick-question draft for the test page hash', () => {
  const groups = [{ id: 'g1', label: '考生与家长', questions: ['学费多少？'] }];
  assert.equal(
    buildQuickQuestionPreviewHash(groups),
    `preview=${encodeURIComponent(JSON.stringify(groups))}`,
  );
});

test('keeps an empty draft and ignores non-page-bot forms', () => {
  assert.equal(buildQuickQuestionPreviewHash([]), 'preview=%5B%5D');
  assert.equal(buildQuickQuestionPreviewHash(undefined), '');
  assert.equal(buildQuickQuestionPreviewHash({}), '');
});

test('encodes the welcome-message draft for the test page hash', () => {
  assert.equal(
    buildWelcomePreviewHash('你好，请问想了解什么？'),
    `previewWelcome=${encodeURIComponent('你好，请问想了解什么？')}`,
  );
  // An empty draft is still a real preview: it clears the saved text.
  assert.equal(buildWelcomePreviewHash(''), 'previewWelcome=');
  assert.equal(buildWelcomePreviewHash(undefined), '');
  assert.equal(buildWelcomePreviewHash([]), '');
});

test('every locale carries the test page menu labels', () => {
  const locales = [
    'en-US',
    'zh-Hans',
    'zh-Hant',
    'ja-JP',
    'th-TH',
    'vi-VN',
    'es-ES',
    'ru-RU',
  ];
  const keys = [
    'testPageOpen',
    'testPageTitle',
    'testPageHint',
    'testPageCollege',
    'testPageJishi',
    'testPageDefault',
  ];
  for (const locale of locales) {
    const translations = loadTs(`../../src/i18n/locales/${locale}.ts`).default;
    for (const key of keys) {
      assert.equal(
        typeof translations.bots[key],
        'string',
        `${locale}.bots.${key} must be a string`,
      );
      assert.notEqual(
        translations.bots[key].trim(),
        '',
        `${locale}.bots.${key} is empty`,
      );
    }
  }
});
