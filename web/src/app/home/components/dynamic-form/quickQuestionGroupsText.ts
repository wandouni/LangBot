export interface QuickQuestionGroup {
  id: string;
  label: string;
  questions: string[];
}

const MAX_QUICK_QUESTION_GROUPS = 6;
const MAX_QUICK_QUESTIONS_PER_GROUP = 12;
const MAX_QUICK_QUESTION_LENGTH = 200;
const MAX_QUICK_QUESTION_GROUP_LABEL_LENGTH = 32;

export {
  MAX_QUICK_QUESTION_GROUPS,
  MAX_QUICK_QUESTIONS_PER_GROUP,
  MAX_QUICK_QUESTION_LENGTH,
  MAX_QUICK_QUESTION_GROUP_LABEL_LENGTH,
};

function createGroupId() {
  if (
    typeof crypto !== 'undefined' &&
    typeof crypto.randomUUID === 'function'
  ) {
    return `qg-${crypto.randomUUID()}`;
  }
  return `qg-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}

function clip(value: string, maxLength: number) {
  return Array.from(value).slice(0, maxLength).join('').trim();
}

function stripTrailingColon(value: string) {
  return value.replace(/[：:]\s*$/, '').trim();
}

export function coerceQuickQuestionGroups(
  value: unknown,
): QuickQuestionGroup[] {
  if (!Array.isArray(value)) return [];
  return value
    .filter(
      (item): item is Record<string, unknown> =>
        item != null && typeof item === 'object' && !Array.isArray(item),
    )
    .map((item, index) => ({
      id:
        typeof item.id === 'string' && item.id ? item.id : `group-${index + 1}`,
      label: typeof item.label === 'string' ? item.label : '',
      questions: Array.isArray(item.questions)
        ? item.questions.filter(
            (question): question is string => typeof question === 'string',
          )
        : [],
    }));
}

/**
 * Parse the plain-text editor format:
 *
 *   Group name
 *   First question
 *   Second question
 *
 *   Another group
 *   Another question
 *
 * A blank line starts the next group. The first line of each block is the
 * group name; every remaining line is a question. A trailing colon on the
 * group name is accepted for convenience.
 */
export function parseQuickQuestionGroupsText(
  text: string,
  previousGroups: QuickQuestionGroup[] = [],
): QuickQuestionGroup[] {
  const blocks = text.replace(/\r\n?/g, '\n').split(/\n[ \t]*\n/);
  const groups: QuickQuestionGroup[] = [];
  const usedIds = new Set<string>();

  for (const block of blocks) {
    if (groups.length >= MAX_QUICK_QUESTION_GROUPS) break;

    const lines = block
      .split('\n')
      .map((line) => line.trim())
      .filter(Boolean);
    if (lines.length === 0) continue;

    const label = clip(
      stripTrailingColon(lines[0]),
      MAX_QUICK_QUESTION_GROUP_LABEL_LENGTH,
    );
    if (!label) continue;

    const questions: string[] = [];
    const seenQuestions = new Set<string>();
    for (const line of lines.slice(1)) {
      if (questions.length >= MAX_QUICK_QUESTIONS_PER_GROUP) break;
      const question = clip(line, MAX_QUICK_QUESTION_LENGTH);
      if (!question || seenQuestions.has(question)) continue;
      seenQuestions.add(question);
      questions.push(question);
    }

    let id = previousGroups[groups.length]?.id;
    if (!id || usedIds.has(id)) id = createGroupId();
    let uniqueId = id;
    let suffix = 2;
    while (usedIds.has(uniqueId)) {
      uniqueId = `${id}-${suffix}`;
      suffix += 1;
    }
    usedIds.add(uniqueId);

    groups.push({ id: uniqueId, label, questions });
  }

  return groups;
}

export function serializeQuickQuestionGroups(groups: QuickQuestionGroup[]) {
  return groups
    .map((group) => {
      const label = group.label.trim();
      if (!label) return '';
      return [label, ...group.questions.map((question) => question.trim())]
        .filter(Boolean)
        .join('\n');
    })
    .filter(Boolean)
    .join('\n\n');
}
