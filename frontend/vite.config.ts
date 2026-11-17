import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Dev: `npm run dev` on :5180 proxies /api to `karaoke serve` on :8321.
// Prod: `npm run build` -> dist/, served by `karaoke serve` itself.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5180,
    strictPort: true,
    proxy: { '/api': 'http://127.0.0.1:8321' },
  },
})
