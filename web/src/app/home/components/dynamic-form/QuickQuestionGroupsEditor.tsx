import { useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Textarea } from '@/components/ui/textarea';
import {
  coerceQuickQuestionGroups,
  parseQuickQuestionGroupsText,
  serializeQuickQuestionGroups,
  type QuickQuestionGroup,
} from './quickQuestionGroupsText';

/**
 * Plain-text editor for the bot's quick question groups.
 *
 * The value is persisted as ``adapter_config.quick_question_groups``; the
 * backend and the embed widget sanitize it again before rendering.
 */
export default function QuickQuestionGroupsEditor({
  value,
  onChange,
}: {
  value: unknown;
  onChange: (value: QuickQuestionGroup[]) => void;
}) {
  const { t } = useTranslation();
  const groups = useMemo(() => coerceQuickQuestionGroups(value), [value]);
  const serialized = useMemo(
    () => serializeQuickQuestionGroups(groups),
    [groups],
  );
  const [text, setText] = useState(serialized);
  const lastEmittedText = useRef(serialized);

  // Only rewrite the textarea when the form value changes from outside the
  // editor. While the operator types, the raw text stays untouched so the
  // cursor does not jump as the parsed groups are saved back into the form.
  useEffect(() => {
    if (serialized !== lastEmittedText.current) {
      lastEmittedText.current = serialized;
      setText(serialized);
    }
  }, [serialized]);

  const handleChange = (nextText: string) => {
    const nextGroups = parseQuickQuestionGroupsText(nextText, groups);
    setText(nextText);
    lastEmittedText.current = serializeQuickQuestionGroups(nextGroups);
    onChange(nextGroups);
  };

  return (
    <div className="w-full max-w-3xl space-y-2">
      <p className="text-xs text-muted-foreground">
        {t('quickQuestionGroups.hint')}
      </p>
      <Textarea
        value={text}
        onChange={(event) => handleChange(event.target.value)}
        aria-label={t('quickQuestionGroups.editorLabel')}
        placeholder={t('quickQuestionGroups.placeholder')}
        className="min-h-[220px] w-full resize-y font-mono text-sm leading-6"
      />
    </div>
  );
}

export type { QuickQuestionGroup };
