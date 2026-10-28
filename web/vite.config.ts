import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'path';

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '');
  const apiProxyTarget = env.VITE_API_PROXY_TARGET || 'http://127.0.0.1:5300';
  // Local application-center testing: serve SqlBot under the same origin.
  const sqlbotProxyTarget = env.VITE_SQLBOT_PROXY_TARGET || 'http://127.0.0.1:8001';

  return {
    plugins: [react()],
    resolve: {
      alias: {
        '@': path.resolve(__dirname, './src'),
      },
    },
    server: {
      host: '0.0.0.0',
      port: 3000,
      proxy: {
        '/api': {
          target: apiProxyTarget,
          changeOrigin: true,
          // Preserve the browser-facing Host so the CAS callback can match it
          // against the registered service_base_url (see sso.cas config).
          xfwd: true,
          ws: true,
        },
        '/mcp': {
          target: apiProxyTarget,
          changeOrigin: true,
        },
        '/bots': {
          target: apiProxyTarget,
          changeOrigin: true,
        },
        '/sqlbot': {
          target: sqlbotProxyTarget,
          changeOrigin: true,
          ws: true,
        },
      },
    },
    build: {
      outDir: 'dist',
    },
  };
});
