export const STANDALONE_CHAT_PAGES = [
  'chat.html',
  'chat-jishi.html',
  'default.html',
] as const;

export type StandaloneChatPage = (typeof STANDALONE_CHAT_PAGES)[number];

/**
 * Build the URL of a standalone chat page for the bot being edited.
 *
 * The pages live at the site root next to the console, so the console origin
 * is the right base in both Vite dev (port 3000) and production (port 5300).
 */
export function buildStandaloneChatPageUrl(
  origin: string,
  page: StandaloneChatPage,
  botUuid: string,
): string {
  const base = origin.replace(/\/+$/, '');
  const url = new URL(`${base}/${page}`);
  const uuid = botUuid.trim();
  if (uuid) url.searchParams.set('embed', uuid);
  return url.toString();
}

/**
 * Turn the quick-question draft into a URL hash for the test page.
 *
 * The test page reads this hash and renders the draft instead of the saved
 * bot groups. Returning an empty string means "not a page-bot form"; an empty
 * array still produces a hash so the preview can explicitly show no tabs.
 */
export function buildQuickQuestionPreviewHash(value: unknown): string {
  if (!Array.isArray(value)) return '';
  return `preview=${encodeURIComponent(JSON.stringify(value))}`;
}

/**
 * Turn the welcome-message draft into a URL hash fragment for the test page.
 *
 * An empty string still produces a fragment so the preview can explicitly
 * clear the welcome text; non-strings mean "not a page-bot form".
 */
export function buildWelcomePreviewHash(value: unknown): string {
  if (typeof value !== 'string') return '';
  return `previewWelcome=${encodeURIComponent(value)}`;
}
