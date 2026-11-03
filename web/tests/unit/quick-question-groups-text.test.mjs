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
  coerceQuickQuestionGroups,
  parseQuickQuestionGroupsText,
  serializeQuickQuestionGroups,
  MAX_QUICK_QUESTION_GROUPS,
  MAX_QUICK_QUESTIONS_PER_GROUP,
} = loadTs(
  '../../src/app/home/components/dynamic-form/quickQuestionGroupsText.ts',
);

test('parses blank-line separated groups', () => {
  const groups = parseQuickQuestionGroupsText(`
    考生与家长：
    学校今年开设哪些专业？
    学费多少？
    学校今年开设哪些专业？

    在校学生
    宿舍几人间？
  `);

  assert.deepEqual(
    groups.map(({ label, questions }) => ({ label, questions })),
    [
      {
        label: '考生与家长',
        questions: ['学校今年开设哪些专业？', '学费多少？'],
      },
      { label: '在校学生', questions: ['宿舍几人间？'] },
    ],
  );
});

test('serializes groups back to the plain-text format', () => {
  const groups = [
    { id: 'a', label: '考生与家长', questions: ['问题一', '问题二'] },
    { id: 'b', label: '在校学生', questions: ['问题三'] },
  ];

  assert.equal(
    serializeQuickQuestionGroups(groups),
    '考生与家长\n问题一\n问题二\n\n在校学生\n问题三',
  );
  assert.deepEqual(
    parseQuickQuestionGroupsText(
      serializeQuickQuestionGroups(groups),
      groups,
    ).map(({ id, label, questions }) => ({ id, label, questions })),
    groups,
  );
});

test('keeps existing ids by position and bounds the input', () => {
  const previous = [{ id: 'keep-me', label: 'Old', questions: [] }];
  const groups = parseQuickQuestionGroupsText(
    Array.from({ length: 10 }, (_, index) => {
      const label = `G${index}`;
      const questions = Array.from(
        { length: MAX_QUICK_QUESTIONS_PER_GROUP + 3 },
        (_, questionIndex) => `Q${questionIndex}`,
      );
      return [label, ...questions].join('\n');
    }).join('\n\n'),
    previous,
  );

  assert.equal(groups.length, MAX_QUICK_QUESTION_GROUPS);
  assert.equal(groups[0].id, 'keep-me');
  assert.equal(groups[0].questions.length, MAX_QUICK_QUESTIONS_PER_GROUP);
});

test('treats an empty editor as no groups', () => {
  assert.deepEqual(parseQuickQuestionGroupsText('  \n\n  '), []);
  assert.deepEqual(coerceQuickQuestionGroups(null), []);
});
