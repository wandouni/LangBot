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
