import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import {
  ArrowRight,
  Database,
  LogOut,
  MessageSquareText,
  RefreshCw,
} from 'lucide-react';
import langbotIcon from '@/app/assets/langbot-logo.webp';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { LoadingSpinner } from '@/components/ui/loading-spinner';
import { LanguageSelector } from '@/components/ui/language-selector';
import { ThemeToggle } from '@/components/ui/theme-toggle';
import {
  clearSqlbotSession,
  httpClient,
  initializeSystemInfo,
  isSupportAdminSession,
  systemInfo,
} from '@/app/infra/http';

type CardState = 'idle' | 'loading';

/**
 * Post-login application center.
 *
 * Deliberately independent of HomeLayout: it is the only screen between the
 * login page and either application, so it must not bootstrap or render any
 * LangBot Workspace chrome. LangBot itself is entered through the normal
 * /home routes, which perform the Workspace bootstrap there.
 */
export default function PortalPage() {
  const navigate = useNavigate();
  const { t } = useTranslation();
  const [ready, setReady] = useState(false);
  const [loadError, setLoadError] = useState(false);
  const [account, setAccount] = useState('');
  const [sqlbotState, setSqlbotState] = useState<CardState>('idle');
  const [sqlbotError, setSqlbotError] = useState<string | null>(null);

  const leaveToLogin = useCallback(() => {
    clearSqlbotSession();
    localStorage.removeItem('token');
    localStorage.removeItem('userEmail');
    localStorage.removeItem('authPrincipalType');
    window.location.href = '/login';
  }, []);

  const load = useCallback(async () => {
    setLoadError(false);
    if (!localStorage.getItem('token')) {
      navigate('/login', { replace: true });
      return;
    }
    if (isSupportAdminSession()) {
      navigate('/home', { replace: true });
      return;
    }

    try {
      if (systemInfo.portal === undefined) {
        await initializeSystemInfo({ throwOnError: true });
      }
      if (systemInfo.portal?.enabled !== true) {
        // Direct visits on a portal-disabled instance keep the legacy flow.
        navigate('/home', { replace: true });
        return;
      }
      const user = await httpClient.getUserInfo();
      setAccount(user.user);
      setReady(true);
    } catch {
      setLoadError(true);
    }
  }, [navigate]);

  useEffect(() => {
    void load();
  }, [load]);

  const openLangbot = () => {
    navigate(systemInfo.portal?.langbot_path || '/home/monitoring');
  };

  const openSqlbot = async () => {
    if (sqlbotState === 'loading') return;
    setSqlbotError(null);
    setSqlbotState('loading');
    try {
      const result = await httpClient.getSqlbotSsoTicket();
      // Only same-origin subpaths are valid; never follow an absolute URL.
      if (!result.redirect_url.startsWith('/sqlbot/')) {
        throw new Error('Invalid SqlBot redirect');
      }
      clearSqlbotSession();
      window.location.assign(result.redirect_url);
    } catch {
      setSqlbotState('idle');
      setSqlbotError(t('portal.sqlbotUnavailable'));
    }
  };

  if (loadError) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-4 bg-background px-6 text-center">
        <p className="text-lg font-medium">{t('portal.loadError')}</p>
        <Button variant="outline" onClick={() => void load()}>
          <RefreshCw className="mr-2 h-4 w-4" />
          {t('portal.retry')}
        </Button>
      </div>
    );
  }

  if (!ready) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background">
        <LoadingSpinner size="lg" text="" />
      </div>
    );
  }

  const sqlbotEnabled = systemInfo.portal?.sqlbot_enabled === true;

  return (
    <div className="relative flex min-h-screen flex-col bg-background">
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 bg-gradient-to-b from-primary/5 to-background"
      />

      <header className="relative z-10 flex items-center justify-between px-6 py-5 sm:px-10">
        <div className="flex items-center gap-3">
          <img src={langbotIcon} alt="LangBot" className="size-9 rounded-lg" />
          <span className="text-lg font-semibold">{t('portal.title')}</span>
        </div>
        <div className="flex items-center gap-2">
          <LanguageSelector />
          <ThemeToggle />
          <Button variant="ghost" size="sm" onClick={leaveToLogin}>
            <LogOut className="mr-2 h-4 w-4" />
            {t('portal.logout')}
          </Button>
        </div>
      </header>

      <main className="relative z-10 mx-auto flex w-full max-w-5xl flex-1 flex-col justify-center px-6 pb-16 sm:px-10">
        <div className="mb-10 space-y-2">
          <h1 className="text-3xl font-semibold tracking-tight sm:text-4xl">
            {t('portal.welcome', { account })}
          </h1>
          <p className="text-muted-foreground">{t('portal.subtitle')}</p>
        </div>

        <div className="grid gap-5 sm:grid-cols-2">
          <Card className="group border-border/70 transition-shadow hover:shadow-lg">
            <CardContent className="flex h-full flex-col gap-5 p-6">
              <div className="flex size-12 items-center justify-center rounded-xl bg-primary/10 text-primary">
                <MessageSquareText className="size-6" />
              </div>
              <div className="space-y-1.5">
                <h2 className="text-xl font-semibold">
                  {t('portal.langbotTitle')}
                </h2>
                <p className="text-sm text-muted-foreground">
                  {t('portal.langbotDescription')}
                </p>
              </div>
              <Button className="mt-auto w-full" onClick={openLangbot}>
                {t('portal.open')}
                <ArrowRight className="ml-2 h-4 w-4" />
              </Button>
            </CardContent>
          </Card>

          <Card className="group border-border/70 transition-shadow hover:shadow-lg">
            <CardContent className="flex h-full flex-col gap-5 p-6">
              <div className="flex size-12 items-center justify-center rounded-xl bg-emerald-500/10 text-emerald-600 dark:text-emerald-400">
                <Database className="size-6" />
              </div>
              <div className="space-y-1.5">
                <h2 className="text-xl font-semibold">
                  {t('portal.sqlbotTitle')}
                </h2>
                <p className="text-sm text-muted-foreground">
                  {t('portal.sqlbotDescription')}
                </p>
              </div>
              {sqlbotError ? (
                <p className="text-sm text-destructive" role="alert">
                  {sqlbotError}
                </p>
              ) : null}
              <Button
                className="mt-auto w-full"
                variant="secondary"
                disabled={!sqlbotEnabled || sqlbotState === 'loading'}
                onClick={() => void openSqlbot()}
              >
                {sqlbotState === 'loading'
                  ? t('portal.opening')
                  : sqlbotEnabled
                    ? t('portal.open')
                    : t('portal.disabled')}
                {sqlbotState === 'loading' ? (
                  <LoadingSpinner size="sm" text="" className="ml-2" />
                ) : (
                  <ArrowRight className="ml-2 h-4 w-4" />
                )}
              </Button>
            </CardContent>
          </Card>
        </div>
      </main>
    </div>
  );
}
