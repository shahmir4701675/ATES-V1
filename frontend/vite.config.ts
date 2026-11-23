import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import precompress from './build/precompress.mjs'

export default defineConfig(({ mode }) => ({
  // Optional build-time static-asset origin; authenticated API traffic is separate.
  base: loadEnv(mode, '.', 'ATES_').ATES_ASSET_BASE || '/',
  plugins: [react(), precompress()],
  build: {
    manifest: true,
    minify: 'esbuild',
    cssMinify: true,
    rollupOptions: { output: { manualChunks: { react: ['react', 'react-dom'] } } },
  },
  server: {
    host: '0.0.0.0',
    port: 3000,
  },
}))
