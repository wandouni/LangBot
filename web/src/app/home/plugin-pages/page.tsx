import EntityLoadState from '@/components/EntityLoadState';
import LoadErrorState from '@/components/LoadErrorState';
import { useSearchParams } from 'react-router-dom';
import { httpClient } from '@/app/infra/http/HttpClient';
import { useEffect, useRef, useState, useCallback } from 'react';
import { useSidebarData } from '@/app/home/components/home-sidebar/SidebarDataContext';
import { useTranslation } from 'react-i18next';
import { useTheme } from '@/components/providers/theme-provider';
import { useAuthenticatedPluginAsset } from '@/hooks/useAuthenticatedPluginResource';

const PAGE_PREFERENCE_PREFIX = 'langbot:plugin-page-preferences:';
const MAX_PREFERENCE_KEYS = 20;
const MAX_PREFERENCE_KEY_LENGTH = 64;
const MAX_PREFERENCE_VALUE_LENGTH = 512;

function pagePreferenceStorageKey(
  author: string,
  pluginName: string,
  pageId: string,
): string {
  return `${PAGE_PREFERENCE_PREFIX}${author}/${pluginName}/${pageId}`;
}

function sanitizePagePreferences(value: unknown): Record<string, string> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return {};
  const result: Record<string, string> = {};
  for (const [key, item] of Object.entries(value)) {
    if (Object.keys(result).length >= MAX_PREFERENCE_KEYS) break;
    if (typeof item !== 'string') continue;
    if (!key || key.length > MAX_PREFERENCE_KEY_LENGTH) continue;
    result[key] = item.slice(0, MAX_PREFERENCE_VALUE_LENGTH);
  }
  return result;
}

function formatPageApiError(error: unknown): string {
  if (error instanceof Error) return error.message;
  if (error && typeof error === 'object') {
    const candidate = error as { msg?: unknown; message?: unknown };
    if (typeof candidate.msg === 'string' && candidate.msg) {
      return candidate.msg;
    }
    if (typeof candidate.message === 'string' && candidate.message) {
      return candidate.message;
    }
    try {
      return JSON.stringify(error);
    } catch {
      return String(error);
    }
  }
  return String(error);
}

function readPagePreferences(storageKey: string): Record<string, string> {
  if (typeof window === 'undefined') return {};
  try {
    const raw = window.localStorage.getItem(storageKey);
    if (!raw) return {};
    return sanitizePagePreferences(JSON.parse(raw));
  } catch {
    return {};
  }
}

function writePagePreferences(
  storageKey: string,
  preferences: Record<string, string>,
): void {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(storageKey, JSON.stringify(preferences));
  } catch {
    // Sandboxed/private contexts may deny storage; the page still keeps its
    // in-memory selection for this session.
  }
}

/**
 * Plugin page that renders a plugin-provided HTML page in an iframe.
 * URL format: /home/plugin-pages?id=author/name/pageId
 *
 * The iframe communicates with the parent via postMessage:
 *
 * Parent → iframe:
 *   { type: 'langbot:context', theme: 'light'|'dark', language: 'zh-Hans'|'en-US', preferences: Record<string,string> }
 *
 * iframe → Parent:
 *   { type: 'langbot:api', requestId: string, endpoint: string, method: string, body?: any }
 *   { type: 'langbot:preferences', preferences: Record<string,string> }
 *
 * Parent → iframe (response):
 *   { type: 'langbot:api:response', requestId: string, data?: any, error?: string }
 */
export default function PluginPagesPage() {
  const [searchParams] = useSearchParams();
  const id = searchParams.get('id');
  const { t } = useTranslation();
  const { setDetailEntityName, pluginPages, refreshPlugins } = useSidebarData();
  const [lookupCompleteForId, setLookupCompleteForId] = useState<string | null>(
    null,
  );

  // Find the matching page for breadcrumb
  const page = pluginPages.find((p) => p.id === id);

  useEffect(() => {
    setDetailEntityName(page?.name ?? id ?? '');
    return () => setDetailEntityName(null);
  }, [page, id, setDetailEntityName]);

  useEffect(() => {
    if (!id || page) return;
    let cancelled = false;
    setLookupCompleteForId(null);
    refreshPlugins().finally(() => {
      if (!cancelled) setLookupCompleteForId(id);
    });
    return () => {
      cancelled = true;
    };
  }, [id, page, refreshPlugins]);

  if (!id) {
    return (
      <div className="flex items-center justify-center h-full text-muted-foreground">
        {t('pluginPages.selectFromSidebar')}
      </div>
    );
  }

  // Parse "author/name/pageId"
  const parts = id.split('/');
  if (parts.length < 3) {
    return (
      <div className="flex items-center justify-center h-full text-muted-foreground">
        {t('pluginPages.invalidPage')}
      </div>
    );
  }

  const author = parts[0];
  const pluginName = parts[1];
  if (!page) {
    if (lookupCompleteForId === id) {
      return (
        <div className="flex items-center justify-center h-full text-muted-foreground">
          {t('pluginPages.invalidPage')}
        </div>
      );
    }
    return <EntityLoadState />;
  }

  const assetPath = page.path;
  const pageId = page.pageId;

  return (
    <PluginPageIframe
      author={author}
      pluginName={pluginName}
      pagePath={assetPath}
      pageId={pageId}
    />
  );
}

function PluginPageIframe({
  author,
  pluginName,
  pagePath,
  pageId,
}: {
  author: string;
  pluginName: string;
  pagePath: string;
  pageId: string;
}) {
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const [loadedAssetUrl, setLoadedAssetUrl] = useState('');
  const { resolvedTheme } = useTheme();
  const { t, i18n } = useTranslation();
  const { url: assetUrl, error: assetError } = useAuthenticatedPluginAsset(
    author,
    pluginName,
    pagePath,
  );
  const loading = !assetUrl || loadedAssetUrl !== assetUrl;
  const preferenceStorageKey = pagePreferenceStorageKey(
    author,
    pluginName,
    pageId,
  );
  const preferencesRef = useRef<Record<string, string>>(
    readPagePreferences(preferenceStorageKey),
  );

  useEffect(() => {
    preferencesRef.current = readPagePreferences(preferenceStorageKey);
  }, [preferenceStorageKey]);

  // Send context (theme + language + persisted page preferences) to iframe.
  // Use '*' as targetOrigin because sandboxed iframe has opaque (null) origin.
  const sendContext = useCallback(() => {
    const iframe = iframeRef.current;
    if (iframe?.contentWindow) {
      iframe.contentWindow.postMessage(
        {
          type: 'langbot:context',
          theme: resolvedTheme,
          language: i18n.language,
          preferences: preferencesRef.current,
        },
        '*',
      );
    }
  }, [resolvedTheme, i18n.language]);

  // Re-send context when theme or language changes
  useEffect(() => {
    if (!loading) {
      sendContext();
    }
  }, [resolvedTheme, i18n.language, loading, sendContext]);

  // Handle messages from iframe (API calls)
  useEffect(() => {
    const handleMessage = async (event: MessageEvent) => {
      // Validate source — only accept messages from our specific iframe window
      // This is more secure than origin checking: works with sandboxed (null-origin) iframes
      // and prevents spoofing from other windows/iframes
      if (event.source !== iframeRef.current?.contentWindow) return;

      const data = event.data;
      if (!data || typeof data !== 'object') return;

      if (data.type === 'langbot:preferences') {
        const preferences = sanitizePagePreferences(data.preferences);
        if (Object.keys(preferences).length === 0) return;
        preferencesRef.current = {
          ...preferencesRef.current,
          ...preferences,
        };
        writePagePreferences(preferenceStorageKey, preferencesRef.current);
        return;
      }

      // Validate requestId format to prevent injection
      if (data.type === 'langbot:api') {
        const { requestId, endpoint, method, body } = data;
        if (typeof requestId !== 'string' || typeof endpoint !== 'string')
          return;
        // Sanitize endpoint — must start with / and not contain ..
        if (!endpoint.startsWith('/') || endpoint.includes('..')) return;
        const normalizedMethod =
          typeof method === 'string' ? method.toUpperCase() : 'POST';
        if (
          !['GET', 'POST', 'PUT', 'PATCH', 'DELETE'].includes(normalizedMethod)
        )
          return;
        try {
          const result = await httpClient.pluginPageApi(
            author,
            pluginName,
            pageId,
            endpoint,
            normalizedMethod,
            body,
          );
          iframeRef.current?.contentWindow?.postMessage(
            {
              type: 'langbot:api:response',
              requestId,
              data: result,
            },
            '*',
          );
        } catch (err: unknown) {
          const errorMsg = formatPageApiError(err);
          iframeRef.current?.contentWindow?.postMessage(
            {
              type: 'langbot:api:response',
              requestId,
              error: errorMsg,
            },
            '*',
          );
        }
      }
    };

    window.addEventListener('message', handleMessage);
    return () => window.removeEventListener('message', handleMessage);
  }, [author, pluginName, pageId, preferenceStorageKey]);

  return (
    <div className="flex flex-col h-full w-full">
      {assetError ? (
        <LoadErrorState
          title={t('plugins.loadFailed')}
          className="flex-1"
          onRetry={() => window.location.reload()}
        />
      ) : loading || !assetUrl ? (
        <EntityLoadState />
      ) : null}
      {!assetError && assetUrl && (
        <iframe
          ref={iframeRef}
          src={assetUrl}
          className="flex-1 w-full border-0 rounded-md"
          style={{ display: loading ? 'none' : 'block' }}
          onLoad={() => {
            setLoadedAssetUrl(assetUrl);
            sendContext();
          }}
          sandbox="allow-scripts allow-forms"
          title={`${author}/${pluginName} - ${pagePath}`}
        />
      )}
    </div>
  );
}
