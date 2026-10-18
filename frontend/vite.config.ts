import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

const env = (globalThis as { process?: { env?: Record<string, string | undefined> } }).process?.env;

export default defineConfig({
  base: env?.VITE_BASE || '/',
  plugins: [react()],
  worker: { format: 'iife' },
  server: { strictPort: true, proxy: { '/api': 'http://127.0.0.1:8000' } },
});
