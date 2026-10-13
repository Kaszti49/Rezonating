import { defineConfig } from 'vite';
import { svelte } from '@sveltejs/vite-plugin-svelte';

// Dev: start the lab server with `rzlab serve --dev`, then `npm run dev` serves on 5173 and proxies /api and /ws
// to it (WEB_API.md section 1). Host and Origin pass through unchanged (changeOrigin: false); the server accepts
// port 5173 only when it was started with --dev (without it, 5173 is a foreign origin and gets 403).
const target = 'http://127.0.0.1:8765';

export default defineConfig({
  plugins: [svelte()],
  server: {
    host: '127.0.0.1',
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': { target, changeOrigin: false },
      '/ws': { target, ws: true, changeOrigin: false },
    },
  },
  build: {
    outDir: '../src/rezonating_lab/static',
    emptyOutDir: true,
    target: 'es2022',
    sourcemap: false,
  },
});
