import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
import ts from 'typescript';

function loadTs(relativePath) {
  const source = readFileSync(new URL(relativePath, import.meta.url), 'utf8');
  const m = { exports: {} };
  // Locale catalogs import their own sub-catalogs; those are irrelevant to the
  // keys asserted here, so every relative import resolves to an empty module.
  const requireShim = () => ({});
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
  )(m, m.exports, requireShim);
  return m.exports;
}

const LOCALES = [
  'en-US',
  'zh-Hans',
  'zh-Hant',
  'ja-JP',
  'th-TH',
  'vi-VN',
  'es-ES',
  'ru-RU',
];

const EXPECTED_KEYS = ['editorLabel', 'hint', 'placeholder'];

test('every locale carries the same quick question group keys', () => {
  for (const locale of LOCALES) {
    const translations = loadTs(`../../src/i18n/locales/${locale}.ts`).default;
    const groups = translations.quickQuestionGroups;
    assert.ok(groups, `${locale} is missing quickQuestionGroups`);
    assert.deepEqual(
      Object.keys(groups).sort(),
      [...EXPECTED_KEYS].sort(),
      `${locale} quickQuestionGroups keys differ`,
    );
    for (const key of EXPECTED_KEYS) {
      assert.equal(
        typeof groups[key],
        'string',
        `${locale}.quickQuestionGroups.${key} must be a string`,
      );
      assert.notEqual(
        groups[key].trim(),
        '',
        `${locale}.quickQuestionGroups.${key} is empty`,
      );
    }
  }
});
