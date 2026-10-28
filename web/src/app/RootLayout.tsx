import { Outlet, useLocation } from 'react-router-dom';
import { useDocumentTitle } from '@/hooks/useDocumentTitle';
import { CloudBanner } from '@/components/CloudBanner';

// Top-level route layout: drives the dynamic document title from the active
// route and renders the matched child route via <Outlet />. The Cloud-only
// instance notice lives here so it is present on every route (login included);
// it publishes `--cloud-banner-height` for the fixed shell to offset itself.
export default function RootLayout() {
  useDocumentTitle();
  const { pathname } = useLocation();
  // The application center owns the whole viewport; an instance notice above
  // it would be the only piece of LangBot chrome on the page.
  const isPortal = pathname === '/portal';
  return (
    <>
      {!isPortal && <CloudBanner />}
      <Outlet />
    </>
  );
}
