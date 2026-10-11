import { defineConfig } from 'vite';

// base './' lets the built app be served from any folder (GitHub Pages, a release zip...).
export default defineConfig({
  base: './',
  server: { port: 5173, open: false },
  build: { target: 'es2020', chunkSizeWarningLimit: 1000 },
});
