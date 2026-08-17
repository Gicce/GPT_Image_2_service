import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// Backend FastAPI runs on port 8000 (see backend/Dockerfile, docker-compose.yml,
// nginx/nginx.conf upstream). Override with API_PROXY_TARGET if backend runs elsewhere.
const proxyTarget = process.env.API_PROXY_TARGET || 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [vue()],
  base: '/admin/',
  build: { outDir: 'dist' },
  server: {
    host: '0.0.0.0',
    port: 5000,
    proxy: {
      '/api': {
        target: proxyTarget,
        changeOrigin: true,
        secure: false,
      }
    }
  }
})
