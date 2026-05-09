import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  base: '/admin/',
  build: { outDir: 'dist' },
  server: { proxy: { '/api': 'http://localhost:8000' } }
})
